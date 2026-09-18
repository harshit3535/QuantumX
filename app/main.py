from __future__ import annotations

import os
import time
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .core import Core
from .db import Database
from .models import ChatRequest, ChatResponse, SessionResponse

BASE = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE, "static")

db = Database(settings.database_url)
core = Core(db)
app = FastAPI(title=settings.app_name, version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
async def health():
    assembly_ready = bool(settings.assemblyai_api_key)
    llm_ready = (
        (settings.llm_provider == "gemini" and bool(settings.gemini_api_key))
        or (settings.llm_provider == "openrouter" and bool(settings.openrouter_api_key))
        or settings.llm_provider == "mock"
    )
    return {
        "ok": True,
        "app": settings.app_name,
        "llm_provider": settings.llm_provider,
        "llm_configured": llm_ready,
        "assemblyai_configured": assembly_ready,
        "voice_ready": assembly_ready,
        "voice_supported_languages": ["en"],
        "setup": {
            "assemblyai": "Add ASSEMBLYAI_API_KEY in Render Environment Variables for English voice input.",
            "llm": "Add GEMINI_API_KEY or OPENROUTER_API_KEY in Render Environment Variables for full AI responses."
        },
    }


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
    return {"session_id": session_id, "messages": db.history(session_id, settings.max_history_messages)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        return await core.handle(req.session_id, req.message, req.source, req.language)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Core error: {exc}")


@app.get("/api/assemblyai/token")
async def assemblyai_token(language: str = Query("en", pattern="^(en|hi|gu)$")):
    if not settings.assemblyai_api_key:
        raise HTTPException(503, "ASSEMBLYAI_API_KEY is not configured")

    ttl = max(1, min(settings.assemblyai_token_ttl, 600))
    model = settings.assemblyai_stream_model if language == "en" else "whisper-rt"
    params = {"expires_in_seconds": ttl}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://streaming.assemblyai.com/v3/token",
            params=params,
            headers={"Authorization": f"Bearer {settings.assemblyai_api_key}"},
        )
        r.raise_for_status()
        return {
            "token": r.json()["token"],
            "expires_in_seconds": ttl,
            "sample_rate": 16000,
            "speech_model": model,
            "language_detection": language != "en",
        }
