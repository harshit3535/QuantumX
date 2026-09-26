"""LLM router: one interface, many free providers, automatic fallback.

The rest of the system only calls `router.complete(...)`. It never knows which
provider answered, which is what makes "no single specific AI API" true.
"""
from __future__ import annotations

import time
from typing import Any

from ..config import settings
from ..errors import LLMError, LLMRateLimited, LLMUnavailable
from .providers import Provider, build_provider

COOLDOWN_RATE_LIMIT = 30.0     # seconds to skip a provider after a 429
COOLDOWN_HARD_FAIL = 300.0     # seconds to skip a provider after bad key / missing model


class LLMRouter:
    def __init__(self, providers: list[Provider] | None = None):
        self._explicit = providers
        self._cooldown: dict[str, float] = {}
        self.last_used: str | None = None
        self.last_errors: list[str] = []

    # ------------------------------------------------------------- providers
    def providers(self) -> list[Provider]:
        if self._explicit is not None:
            return list(self._explicit)
        out: list[Provider] = []
        for name in settings.llm_providers.split(","):
            p = build_provider(name)
            if p is not None:
                out.append(p)
        return out

    def configured_providers(self) -> list[Provider]:
        return [p for p in self.providers() if p.configured()]

    def available(self) -> bool:
        return bool(self.configured_providers())

    def status(self) -> list[dict[str, Any]]:
        return [{"name": p.name, "configured": p.configured()} for p in self.providers()]

    # -------------------------------------------------------------- complete
    async def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 30.0,
    ) -> str:
        candidates = self.configured_providers()
        if not candidates:
            raise LLMUnavailable("No AI provider is configured. Add GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY.")

        errors: list[str] = []
        now = time.monotonic()
        # providers on cooldown go last, but are still tried if nothing else works
        ready = [p for p in candidates if self._cooldown.get(p.name, 0) <= now]
        cooling = [p for p in candidates if p not in ready]

        for p in ready + cooling:
            try:
                text = await p.complete(system, messages, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
                self.last_used = p.name
                self.last_errors = errors
                self._cooldown.pop(p.name, None)
                return text
            except LLMRateLimited as exc:
                self._cooldown[p.name] = time.monotonic() + COOLDOWN_RATE_LIMIT
                errors.append(exc.message)
            except LLMError as exc:
                if not exc.recoverable:
                    self._cooldown[p.name] = time.monotonic() + COOLDOWN_HARD_FAIL
                errors.append(exc.message)

        self.last_errors = errors
        raise LLMUnavailable("All AI providers failed: " + " | ".join(errors))

    # ------------------------------------------------------------ diagnostics
    async def ping(self) -> list[dict[str, Any]]:
        results = []
        for p in self.providers():
            if not p.configured():
                results.append({"provider": p.name, "configured": False})
                continue
            t0 = time.monotonic()
            try:
                out = await p.complete("Reply with the single word: ok", [{"role": "user", "content": "ping"}], max_tokens=64, timeout=20)
                results.append({"provider": p.name, "configured": True, "ok": True, "ms": int((time.monotonic() - t0) * 1000), "sample": out.strip()[:40]})
            except LLMError as exc:
                results.append({"provider": p.name, "configured": True, "ok": False, "error": exc.message, "ms": int((time.monotonic() - t0) * 1000)})
        return results


_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
