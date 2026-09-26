from __future__ import annotations

import json
from typing import Any

import requests

from config import settings
from llm.base import LLMClient


class OpenAICompatibleLLM(LLMClient):
    """Works with OpenAI, Groq, OpenRouter, Ollama and similar /v1 chat APIs."""

    def __init__(self) -> None:
        self.base_url = settings.llm_base_url
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model

    def is_configured(self) -> bool:
        # Ollama/local servers commonly work without a key.
        return bool(self.model and self.base_url and (self.api_key or "localhost" in self.base_url or "127.0.0.1" in self.base_url))

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        if not self.is_configured():
            raise RuntimeError("OpenAI-compatible LLM is not fully configured. Set OPENAI_COMPAT_MODEL and provider settings in .env.")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM response: {data}") from exc

    def info(self) -> dict[str, str]:
        return {"provider": "openai_compatible", "model": self.model, "base_url": self.base_url}
