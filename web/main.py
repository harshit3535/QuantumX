from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import settings
from core.history import HistoryManager
from core.models import InputEnvelope
from core.orchestrator import AgentOrchestrator
from llm.factory import build_llm

BASE_DIR = Path(__file__).resolve().parent

llm = build_llm()
history = HistoryManager()
orchestrator = AgentOrchestrator(llm, history)

app = FastAPI(title="QuantumX Personal AI", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    input_mode: str = "text"


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health():
    info = llm.info()
    return {
        "status": "ok",
        "mode": settings.default_mode,
        "llm_provider": info.get("provider", "unknown"),
        "model": info.get("model", ""),
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    envelope = InputEnvelope(
        text=text,
        mode=settings.default_mode,
        input_mode=request.input_mode if request.input_mode in {"text", "voice"} else "text",
        provider="text" if request.input_mode != "voice" else "browser_speech",
    )

    try:
        response = orchestrator.handle(envelope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AOB error: {exc}") from exc

    return {
        "segments": [asdict(segment) for segment in response.segments],
        "spoken_text": response.spoken_text,
        "metadata": response.metadata,
    }


@app.post("/api/history/clear")
def clear_history():
    history.clear()
    return {"status": "cleared"}
