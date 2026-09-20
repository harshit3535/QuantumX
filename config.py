from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    default_mode: str = os.getenv("APP_MODE", os.getenv("DEFAULT_MODE", "personal"))

    llm_provider: str = os.getenv("AOB_LLM_PROVIDER", "openai_compat" if os.getenv("OPENROUTER_API_KEY") else "mock")
    llm_base_url: str = os.getenv("OPENROUTER_BASE_URL", os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    llm_api_key: str = os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_COMPAT_API_KEY", ""))
    llm_model: str = os.getenv("OPENROUTER_MODEL", os.getenv("OPENAI_COMPAT_MODEL", ""))

    assemblyai_api_key: str = os.getenv("ASSEMBLYAI_API_KEY", "")
    assemblyai_speech_model: str = os.getenv("ASSEMBLYAI_SPEECH_MODEL", "universal-3-5-pro")
    assemblyai_mode: str = os.getenv("ASSEMBLYAI_MODE", "balanced")
    assemblyai_sample_rate: int = int(os.getenv("ASSEMBLYAI_SAMPLE_RATE", "16000"))
    assemblyai_min_turn_silence: int = int(os.getenv("ASSEMBLYAI_MIN_TURN_SILENCE", "160"))
    assemblyai_max_turn_silence: int = int(os.getenv("ASSEMBLYAI_MAX_TURN_SILENCE", "2400"))
    assemblyai_min_confidence: float = float(os.getenv("ASSEMBLYAI_MIN_CONFIDENCE", "0.50"))

    personal_stt_model: str = os.getenv("PERSONAL_STT_MODEL", "small")
    personal_stt_language: str = os.getenv("PERSONAL_STT_LANGUAGE", "")
    personal_stt_device: str = os.getenv("PERSONAL_STT_DEVICE", "cpu")
    personal_stt_compute_type: str = os.getenv("PERSONAL_STT_COMPUTE_TYPE", "int8")
    personal_record_seconds: int = int(os.getenv("PERSONAL_RECORD_SECONDS", "12"))

    tts_enabled: bool = _env_bool("TTS_ENABLED", True)
    tts_rate: int = int(os.getenv("TTS_RATE", "185"))
    tts_volume: float = float(os.getenv("TTS_VOLUME", "1.0"))

    history_file: Path = BASE_DIR / os.getenv("HISTORY_FILE", "data/history.json")
    history_max_turns: int = int(os.getenv("HISTORY_MAX_TURNS", "40"))


settings = Settings()
settings.history_file.parent.mkdir(parents=True, exist_ok=True)
