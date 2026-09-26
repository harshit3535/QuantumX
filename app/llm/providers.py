"""LLM providers. Each one turns (system, messages) into text.

Free-tier friendly: short timeouts, clear error mapping (rate limit / auth /
model-not-found / network) so the router can fall back to the next provider.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

import httpx

from ..config import settings
from ..errors import LLMError, LLMRateLimited


class Provider(Protocol):
    name: str

    def configured(self) -> bool: ...

    async def complete(
        self, system: str, messages: list[dict[str, str]], *, json_mode: bool = False,
        temperature: float = 0.3, max_tokens: int = 2048, timeout: float = 30.0,
    ) -> str: ...


def _raise_for_status(name: str, r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    detail = ""
    try:
        detail = str(r.json())[:300]
    except Exception:
        detail = r.text[:300]
    if r.status_code == 429:
        raise LLMRateLimited(f"{name}: rate limit reached")
    if r.status_code in (401, 403):
        raise LLMError(f"{name}: API key rejected ({r.status_code})", kind="llm_auth_failed", recoverable=False)
    if r.status_code == 404:
        raise LLMError(f"{name}: model not found - change the model in your environment. {detail}", kind="llm_model_not_found", recoverable=False)
    raise LLMError(f"{name}: HTTP {r.status_code} {detail}")


class GeminiProvider:
    name = "gemini"

    def configured(self) -> bool:
        return bool(settings.gemini_api_key)

    async def complete(self, system, messages, *, json_mode=False, temperature=0.3, max_tokens=2048, timeout=30.0) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages
        ]
        gen: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"gemini: network error ({type(exc).__name__})") from exc
        _raise_for_status(self.name, r)
        data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"gemini: empty response ({reason})")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMError(f"gemini: empty text (finish={cands[0].get('finishReason')})")
        return text


class OpenAICompatProvider:
    """Groq and OpenRouter both speak the OpenAI chat-completions dialect."""

    def __init__(self, name: str, base_url: str, key_attr: str, model_attr: str,
                 extra_headers: Callable[[], dict[str, str]] | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._key_attr = key_attr
        self._model_attr = model_attr
        self._extra_headers = extra_headers

    @property
    def key(self) -> str:
        return getattr(settings, self._key_attr)

    @property
    def model(self) -> str:
        return getattr(settings, self._model_attr)

    def configured(self) -> bool:
        return bool(self.key)

    def _headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self._extra_headers:
            h.update(self._extra_headers())
        return h

    async def complete(self, system, messages, *, json_mode=False, temperature=0.3, max_tokens=2048, timeout=30.0) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
        body: dict[str, Any] = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
                if r.status_code == 400 and json_mode:      # some models reject response_format
                    body.pop("response_format", None)
                    r = await client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name}: network error ({type(exc).__name__})") from exc
        _raise_for_status(self.name, r)
        data = r.json()
        try:
            text = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"{self.name}: unexpected response shape") from exc
        if not text.strip():
            raise LLMError(f"{self.name}: empty text")
        return text


def build_provider(name: str) -> Provider | None:
    name = name.strip().lower()
    if name == "gemini":
        return GeminiProvider()
    if name == "groq":
        return OpenAICompatProvider("groq", "https://api.groq.com/openai/v1", "groq_api_key", "groq_model")
    if name == "openrouter":
        return OpenAICompatProvider(
            "openrouter", "https://openrouter.ai/api/v1", "openrouter_api_key", "openrouter_model",
            extra_headers=lambda: {"HTTP-Referer": settings.openrouter_site_url, "X-Title": settings.openrouter_app_name},
        )
    return None
