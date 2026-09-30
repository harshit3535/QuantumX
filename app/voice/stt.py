"""Free STT input adapter (personal mode, push-to-talk): Groq-hosted Whisper."""
from __future__ import annotations

import httpx

from ..config import settings
from ..errors import NetworkError, STTError

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_BYTES = 12 * 1024 * 1024


async def transcribe(audio: bytes, filename: str, content_type: str, language: str = "auto") -> dict:
    if not settings.groq_api_key:
        raise STTError("GROQ_API_KEY is not configured, so free voice input is unavailable", kind="stt_not_configured", recoverable=False)
    if not audio:
        raise STTError("The recording was empty - check the microphone", kind="microphone_failure", layer="input")
    if len(audio) > MAX_BYTES:
        raise STTError("Recording too long. Keep it under about a minute.", kind="stt_audio_too_large")

    data = {"model": settings.groq_stt_model, "response_format": "json", "temperature": "0"}
    if language in {"en", "gu", "hi"}:
        data["language"] = language
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post(
                URL, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, data=data,
                files={"file": (filename or "audio.webm", audio, content_type or "audio/webm")},
            )
    except httpx.HTTPError as exc:
        raise NetworkError(f"Could not reach the speech service ({type(exc).__name__})") from exc
    if r.status_code in (401, 403):
        raise STTError("Groq rejected the API key", kind="stt_auth_failed", recoverable=False)
    if r.status_code == 429:
        raise STTError("Speech quota is busy. Try again in a few seconds.", kind="stt_rate_limited")
    if r.status_code >= 400:
        raise STTError(f"Speech-to-text failed (HTTP {r.status_code})")
    text = (r.json().get("text") or "").strip()
    return {"text": text, "language": language, "provider": "groq_whisper", "model": settings.groq_stt_model}
