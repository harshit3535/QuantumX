"""Central configuration. Everything comes from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "Astra"))
    version: str = "1.0.0"
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./data/nexus.db"))

    # AssemblyAI
    assemblyai_api_key: str = field(default_factory=lambda: _env("ASSEMBLYAI_API_KEY"))
    assemblyai_model_en: str = field(default_factory=lambda: _env("ASSEMBLYAI_MODEL_EN", "universal-3-5-pro"))
    assemblyai_model_hi: str = field(default_factory=lambda: _env("ASSEMBLYAI_MODEL_HI", "universal-3-5-pro"))
    assemblyai_model_gu: str = field(default_factory=lambda: _env("ASSEMBLYAI_MODEL_GU", "whisper-rt"))
    assemblyai_token_ttl: int = field(default_factory=lambda: _int("ASSEMBLYAI_TOKEN_TTL", 120))

    # LLM providers
    llm_providers: str = field(default_factory=lambda: _env("LLM_PROVIDERS", "gemini,groq,openrouter"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-flash-latest"))
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_stt_model: str = field(default_factory=lambda: _env("GROQ_STT_MODEL", "whisper-large-v3-turbo"))
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    openrouter_model: str = field(default_factory=lambda: _env("OPENROUTER_MODEL", "openai/gpt-oss-120b:free"))
    openrouter_site_url: str = field(default_factory=lambda: _env("OPENROUTER_SITE_URL", "http://localhost:8000"))
    openrouter_app_name: str = field(default_factory=lambda: _env("OPENROUTER_APP_NAME", "Astra"))

    # Orchestrator limits
    max_history_messages: int = field(default_factory=lambda: _int("MAX_HISTORY_MESSAGES", 30))
    max_iterations: int = field(default_factory=lambda: _int("MAX_ITERATIONS", 3))
    max_agent_calls: int = field(default_factory=lambda: _int("MAX_AGENT_CALLS", 8))
    max_step_retries: int = field(default_factory=lambda: _int("MAX_STEP_RETRIES", 1))
    agent_timeout: int = field(default_factory=lambda: _int("AGENT_TIMEOUT", 45))
    request_deadline: int = field(default_factory=lambda: _int("REQUEST_DEADLINE", 75))
    goal_check: str = field(default_factory=lambda: _env("GOAL_CHECK", "auto").lower())

    # Safety
    rate_limit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MIN", 40))
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "*"))
    enable_code_execution: bool = field(default_factory=lambda: _bool("ENABLE_CODE_EXECUTION", False))
    code_exec_timeout: int = field(default_factory=lambda: _int("CODE_EXEC_TIMEOUT", 4))


settings = Settings()
