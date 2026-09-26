from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .errors import NexusError
from .llm.router import get_router
from .memory.db import Database
from .models import ChatRequest, ChatResponse, SessionResponse
from .pipeline import Nexus
from .tools.pyrunner import run_python
from .voice import assemblyai, stt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE, "static")

db = Database(settings.database_url)
nexus = Nexus(db)

@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio
    from .tools.mathsolve import _kill_pool, warm_up
    task = asyncio.create_task(warm_up())          # start the math worker early so the first question is fast
    yield
    task.cancel()
    _kill_pool()


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

# ------------------------------------------------------------------ rate limit
_hits: dict[str, deque[float]] = defaultdict(deque)
_LIMITED = ("/api/chat", "/api/stt", "/api/assemblyai/token", "/api/diagnostics", "/api/run")


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if request.method != "OPTIONS" and path.startswith(_LIMITED):
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
        now = time.monotonic()
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.rate_limit_per_min:
            return JSONResponse({"error": {"kind": "rate_limited", "layer": "network", "message": "Too many requests. Wait a moment.", "recoverable": True}}, status_code=429)
        q.append(now)
        if len(_hits) > 5000:                       # keep memory bounded
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60]:
                _hits.pop(k, None)
    return await call_next(request)


@app.exception_handler(NexusError)
async def nexus_error_handler(_: Request, exc: NexusError):
    status = 503 if not exc.recoverable else 502
    return JSONResponse({"error": exc.info().model_dump()}, status_code=status)


# ------------------------------------------------------------------------ pages
@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ----------------------------------------------------------------------- status
@app.get("/api/health")
async def health():
    router = get_router()
    llm = router.status()
    return {
        "ok": True,
        "app": settings.app_name,
        "version": settings.version,
        "llm_configured": router.available(),
        "llm_providers": llm,
        "assemblyai_configured": bool(settings.assemblyai_api_key),
        "free_stt_configured": bool(settings.groq_api_key),
        "code_execution": settings.enable_code_execution,
        "modes": {
            "hackathon": {"stt": "assemblyai", "ready": bool(settings.assemblyai_api_key)},
            "personal": {"stt": "groq_whisper | browser", "ready": True},
        },
        "setup": {
            "assemblyai": "Set ASSEMBLYAI_API_KEY for hackathon voice mode.",
            "llm": "Set at least one of GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY.",
        },
    }


@app.get("/api/diagnostics")
async def diagnostics():
    """Sends one tiny request to each configured AI provider - use it right after deploying."""
    return {"providers": await get_router().ping()}


# --------------------------------------------------------------------- sessions
@app.post("/api/sessions", response_model=SessionResponse)
async def new_session():
    sid = db.create_session("New mission")
    return SessionResponse(session_id=sid, title="New mission")


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": db.sessions()}


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    return {"session_id": session_id, "messages": db.history(session_id, 100)}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    db.delete_session(session_id)
    return {"ok": True}


# ------------------------------------------------------------------------- chat
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    return await nexus.chat(req)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Server-Sent Events: live plan/step progress while the AOB works, then one
    'final' event with the same payload /api/chat returns. This is what lets the
    UI show 'planning -> math agent running -> done' as it actually happens,
    instead of only after the whole request finishes."""
    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def worker() -> None:
        try:
            result = await nexus.chat(req, emit=emit)
            await queue.put({"type": "final", "data": result.model_dump()})
        except Exception as exc:  # pragma: no cover - nexus.chat already guards itself
            logging.getLogger("nexus.stream").exception("stream worker crashed")
            await queue.put({"type": "final", "data": {"error": {"kind": "system_error", "layer": "system",
                             "message": str(exc), "recoverable": True}}})
        finally:
            await queue.put(DONE)

    async def events():
        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is DONE:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------------ voice
@app.get("/api/assemblyai/token")
async def assemblyai_token(language: str = Query("en", pattern="^(en|hi|gu)$")):
    return await assemblyai.create_token(language)


@app.post("/api/stt")
async def free_stt(audio: UploadFile = File(...), language: str = Form("auto")):
    data = await audio.read()
    return await stt.transcribe(data, audio.filename or "audio.webm", audio.content_type or "audio/webm", language)


# -------------------------------------------------------------------- code run
class RunRequest(BaseModel):
    code: str
    language: str = "python"


@app.post("/api/run")
async def run_code(req: RunRequest):
    if not settings.enable_code_execution:
        raise HTTPException(403, "Code execution is disabled on this server")
    if req.language.lower() not in {"python", "py"}:
        raise HTTPException(400, "Only Python can be run")
    if len(req.code) > 20000:
        raise HTTPException(413, "Code too long")
    return await run_python(req.code)
