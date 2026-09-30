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
from pydantic import BaseModel, Field

from .config import settings
from .errors import NexusError
from .llm.router import get_router
from .memory.db import Database
from .models import ChatRequest, ChatResponse, SessionResponse
from .pipeline import Nexus
from .orchestrator.task_director import team_catalog
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
_LIMITED = ("/api/chat", "/api/stt", "/api/assemblyai/token", "/api/voice-token", "/api/voice/resolve", "/api/tool/execute", "/api/diagnostics", "/api/selftest", "/api/run")


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
        "assemblyai_voice_agent": {"enabled": settings.assemblyai_voice_agent, "configured": bool(settings.assemblyai_api_key)},
        "free_stt_configured": bool(settings.groq_api_key),
        "code_execution": settings.enable_code_execution,
        "receptionist": {"enabled": settings.receptionist_enabled, "business_name": settings.receptionist_business_name, "timezone": settings.receptionist_timezone, "hours": settings.receptionist_hours},
        "workspaces": {"enabled": settings.workspaces_enabled},
        "modes": {
            "hackathon": {"stt": "assemblyai", "ready": bool(settings.assemblyai_api_key)},
            "personal": {"stt": "groq_whisper | browser", "ready": True},
        },
        "setup": {
            "assemblyai": "Set ASSEMBLYAI_API_KEY for hackathon voice mode.",
            "llm": "Set at least one of GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY.",
        },
    }


@app.get("/api/agent-teams")
async def agent_teams():
    """Catalog of Agency-inspired team presets used by Astra's task director."""
    return {"teams": team_catalog()}




@app.get("/api/workspaces")
async def workspaces_catalog():
    if not settings.workspaces_enabled:
        return {"workspaces": []}
    from .workspaces.hub import workspace_hub
    return {"workspaces": workspace_hub.metadata()}


@app.get("/api/workspaces/{workspace}/state")
async def workspace_state(workspace: str):
    if not settings.workspaces_enabled:
        raise HTTPException(503, "Workspaces are disabled")
    from .workspaces.hub import workspace_hub
    result = workspace_hub.state(workspace)
    if result.get("ok") is False and result.get("message") == "Unknown workspace.":
        raise HTTPException(404, result["message"])
    return result


class WorkspaceToolRequest(BaseModel):
    workspace: str
    tool: str
    arguments: dict = Field(default_factory=dict)
    session_id: str = "dashboard"


@app.post("/api/workspaces/tool")
async def workspace_tool(req: WorkspaceToolRequest):
    if not settings.workspaces_enabled:
        raise HTTPException(503, "Workspaces are disabled")
    from .workspaces.hub import workspace_hub
    return await workspace_hub.execute(req.workspace, req.tool, req.arguments, req.session_id)

@app.get("/api/diagnostics")
async def diagnostics():
    """Sends one tiny request to each configured AI provider - use it right after deploying."""
    return {"providers": await get_router().ping()}


SELFTEST_CASES = [
    ("math (no AI needed)", "solve x^2 - 5x + 6 = 0", "math_agent"),
    ("casual chat", "mare ghare javu che", "general_agent"),
    ("general question", "what is the capital of France?", "general_agent"),
    ("code", "Write a python function add(a, b)", "code_agent"),
    ("live web", "what is the latest news about python programming", "web_agent"),
]


@app.get("/api/selftest")
async def selftest():
    """Runs a few real prompts through the whole orchestrator and reports routing, provider, timing and any error.
    Uses about 3-4 free-tier AI calls. Paste the result to whoever is debugging."""
    import uuid
    from .models import ChatRequest

    sid = "selftest-" + uuid.uuid4().hex[:8]
    results = []
    router = get_router()
    for label, prompt, expected in SELFTEST_CASES:
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(nexus.chat(ChatRequest(session_id=sid, message=prompt, mode="personal")), timeout=90)
            agents = [t.agent for t in r.trace]
            results.append({
                "case": label, "prompt": prompt, "expected_agent": expected, "agents": agents,
                "routing_ok": expected in agents,
                "ok": r.error is None and r.response.response_type != "error",
                "response_type": r.response.response_type, "provider": router.last_used,
                "ms": int((time.monotonic() - t0) * 1000),
                "error": r.error.model_dump() if r.error else None,
                "provider_errors": router.last_errors[-3:] if r.error else [],
                "preview": r.response.plain_text()[:120],
            })
        except Exception as exc:
            results.append({"case": label, "prompt": prompt, "expected_agent": expected, "ok": False, "routing_ok": False,
                            "error": {"kind": "selftest_crash", "message": f"{type(exc).__name__}: {exc}"}, "ms": int((time.monotonic() - t0) * 1000)})
    db.delete_session(sid)
    return {"version": settings.version, "all_ok": all(x.get("ok") and x.get("routing_ok") for x in results),
            "providers": router.status(), "results": results}


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


# ---------------------------------------------------------------- mission audit / receptionist
@app.get("/api/sessions/{session_id}/events")
async def mission_events(session_id: str, limit: int = Query(500, ge=1, le=2000)):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    return {"session_id": session_id, "events": db.mission_events(session_id, limit)}

@app.get("/api/sessions/{session_id}/replay")
async def mission_replay(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    events = db.mission_events(session_id, 2000)
    state = db.get_task_state(session_id)
    return {"session_id": session_id, "events": events, "state": state, "event_count": len(events)}

@app.get("/api/sessions/{session_id}/report")
async def mission_report(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    events = db.mission_events(session_id, 2000)
    state = db.get_task_state(session_id)
    inputs = [e for e in events if e["event_type"] == "input"]
    plans = [e for e in events if e["event_type"] == "plan"]
    evidence = [e for e in events if e["event_type"] == "evidence"]
    return {"session_id": session_id, "summary": {
        "request": (inputs[0].get("payload", {}).get("text", "") if inputs else ""),
        "mission_type": state.get("mission_type", "general"),
        "status": state.get("last_status") or ("awaiting_confirmation" if state.get("pending_action") else "completed"),
        "event_count": len(events),
        "plan_count": len(plans),
        "evidence_count": sum(len((e.get("payload") or {}).get("items", [])) for e in evidence),
    }, "events": events[-100:], "state": state}

@app.get("/api/receptionist/profile")
async def receptionist_profile():
    if not settings.receptionist_enabled:
        raise HTTPException(503, "Receptionist mode is disabled")
    from .tools.receptionist import profile
    return profile()

@app.get("/api/receptionist/bookings")
async def receptionist_bookings(limit: int = Query(100, ge=1, le=500)):
    return {"bookings": db.booking_slots_for_dashboard(limit)}

@app.get("/api/receptionist/messages")
async def receptionist_messages(limit: int = Query(100, ge=1, le=500)):
    return {"messages": db.receptionist_messages(limit)}

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


@app.get("/api/voice-token")
async def voice_agent_token():
    """Mint a short-lived browser token for AssemblyAI's managed Voice Agent API."""
    if not settings.assemblyai_voice_agent:
        raise HTTPException(503, "AssemblyAI Voice Agent mode is disabled")
    if not settings.assemblyai_api_key:
        raise HTTPException(503, "ASSEMBLYAI_API_KEY is not configured")
    import httpx
    ttl = max(1, min(settings.assemblyai_voice_token_ttl, 600))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://agents.assemblyai.com/v1/token",
                params={"expires_in_seconds": ttl},
                headers={"Authorization": f"Bearer {settings.assemblyai_api_key}"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach AssemblyAI: {type(exc).__name__}") from exc
    if r.status_code >= 400:
        raise HTTPException(r.status_code, "AssemblyAI Voice Agent token request failed")
    token = r.json().get("token")
    if not token:
        raise HTTPException(502, "AssemblyAI returned no Voice Agent token")
    return {"token": token, "expires_in_seconds": ttl, "ws_url": "wss://agents.assemblyai.com/v1/ws", "voice": settings.assemblyai_voice}


class VoiceResolveRequest(BaseModel):
    session_id: str
    message: str
    workspace: str | None = None


@app.post("/api/voice/resolve")
async def voice_resolve(req: VoiceResolveRequest):
    """Bridge the managed AssemblyAI voice agent into Astra's existing AOB brain."""
    from .models import ChatRequest
    result = await nexus.chat(ChatRequest(
        workspace=req.workspace, session_id=req.session_id, message=req.message, source="voice", mode="hackathon", output="text", stt_provider="assemblyai"
    ))
    return {
        "text": result.response.plain_text(),
        "response": result.response.model_dump(),
        "plan": result.plan.model_dump(),
        "trace": [t.model_dump() for t in result.trace],
        "normalized": result.normalized,
        "error": result.error.model_dump() if result.error else None,
    }


class ToolExecuteRequest(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


@app.post("/api/tool/execute")
async def tool_execute(req: ToolExecuteRequest):
    """Public, allowlisted read-only tool surface for demo clients."""
    from .tools.operator import check_url, run_public_search
    if req.name == "check_url":
        return {"name": req.name, "result": await check_url(str(req.arguments.get("url", "")))}
    if req.name == "web_search":
        return {"name": req.name, "result": await run_public_search(str(req.arguments.get("query", "")))}
    raise HTTPException(400, "Tool is not available in the public read-only toolset")


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
