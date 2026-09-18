from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "NEXUS")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/nexus.db")
    assemblyai_api_key: str = os.getenv("ASSEMBLYAI_API_KEY", "")
    assemblyai_stream_model: str = os.getenv("ASSEMBLYAI_STREAM_MODEL", "u3-rt-pro")
    assemblyai_token_ttl: int = int(os.getenv("ASSEMBLYAI_TOKEN_TTL", "120"))
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock").lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000")
    openrouter_app_name: str = os.getenv("OPENROUTER_APP_NAME", "NEXUS")
    enable_code_execution: bool = os.getenv("ENABLE_CODE_EXECUTION", "false").lower() == "true"
    code_exec_timeout: int = int(os.getenv("CODE_EXEC_TIMEOUT", "4"))
    max_history_messages: int = int(os.getenv("MAX_HISTORY_MESSAGES", "30"))


settings = Settings()
