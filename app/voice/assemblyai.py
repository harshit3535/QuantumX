"""AssemblyAI = the hackathon-mode STT *input adapter*.

The permanent API key never leaves the server. The browser asks for a one-time
temporary token and opens the streaming WebSocket itself.

Docs (checked Sep 2026):
  token   GET https://streaming.assemblyai.com/v3/token?expires_in_seconds=N
          header  Authorization: <API KEY>            (no "Bearer" prefix)
  socket  wss://streaming.assemblyai.com/v3/ws?speech_model=...&sample_rate=16000&token=<token>
  Turn messages: {"type":"Turn","transcript":"...","end_of_turn":true|false}
"""
from __future__ import annotations

import httpx

from ..config import settings
from ..errors import APIError, NetworkError, STTError

WS_URL = "wss://streaming.assemblyai.com/v3/ws"
TOKEN_URL = "https://streaming.assemblyai.com/v3/token"


def model_for(language: str) -> str:
    return {"en": settings.assemblyai_model_en, "hi": settings.assemblyai_model_hi, "gu": settings.assemblyai_model_gu}.get(
        language, settings.assemblyai_model_en
    )


def stream_params(language: str) -> dict[str, str | int | bool]:
    model = model_for(language)
    params: dict[str, str | int | bool] = {"speech_model": model, "sample_rate": 16000, "encoding": "pcm_s16le"}
    if model.startswith("universal-3") or model.startswith("u3-"):
        params["min_turn_silence"] = 100
        params["max_turn_silence"] = 1000            # AssemblyAI's default; longer = fewer cut-off sentences
    elif model == "whisper-rt":
        params["language_detection"] = "true"
    else:                                            # universal-streaming-*
        params["format_turns"] = "true"
    return params


async def create_token(language: str = "en") -> dict:
    if not settings.assemblyai_api_key:
        raise STTError("ASSEMBLYAI_API_KEY is not configured on the server", kind="assemblyai_not_configured", recoverable=False)
    ttl = max(1, min(settings.assemblyai_token_ttl, 600))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                TOKEN_URL,
                params={"expires_in_seconds": ttl, "max_session_duration_seconds": 1800},
                headers={"Authorization": settings.assemblyai_api_key},
            )
    except httpx.HTTPError as exc:
        raise NetworkError(f"Could not reach AssemblyAI ({type(exc).__name__})") from exc
    if r.status_code in (401, 403):
        raise STTError("AssemblyAI rejected the API key", kind="assemblyai_auth_failed", recoverable=False)
    if r.status_code >= 400:
        raise APIError(f"AssemblyAI token request failed (HTTP {r.status_code})")
    token = r.json().get("token")
    if not token:
        raise APIError("AssemblyAI returned no token")
    return {"token": token, "ws_url": WS_URL, "params": stream_params(language), "expires_in_seconds": ttl, "language": language}
