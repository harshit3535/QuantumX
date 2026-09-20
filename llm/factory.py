from __future__ import annotations

from config import settings
from llm.base import LLMClient
from llm.mock import MockLLM
from llm.openai_compat import OpenAICompatibleLLM


def build_llm() -> LLMClient:
    if settings.llm_provider.lower() in {"openai_compat", "openai-compatible", "openai"}:
        return OpenAICompatibleLLM()
    return MockLLM()
