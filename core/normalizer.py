from __future__ import annotations

import re
from dataclasses import dataclass

from core.models import InputEnvelope


@dataclass
class NormalizationResult:
    envelope: InputEnvelope
    intent_hint: str
    content_types: list[str]
    needs_clarification: bool
    clarification_reason: str = ""


class InputNormalizer:
    """Turns voice/text input into one normalized representation for the AOB."""

    CODE_HINTS = ("python", "javascript", "typescript", "java", "c++", "c#", "code", "program", "script", "function", "class")
    MATH_HINTS = ("solve", "equation", "calculate", "calculate", "integral", "derivative", "equation", "math", "formula", "x =", "= ")

    def normalize(self, envelope: InputEnvelope) -> NormalizationResult:
        text = re.sub(r"\s+", " ", envelope.text or "").strip()
        envelope.text = text
        envelope.raw_text = envelope.raw_text or text

        lower = text.lower()
        content_types = ["text"]
        if any(h in lower for h in self.CODE_HINTS) or "```" in text:
            content_types.append("code")
        if any(h in lower for h in self.MATH_HINTS) or any(ch in text for ch in ("√", "∫", "π", "²", "³")):
            content_types.append("math")

        if not text:
            return NormalizationResult(envelope, "empty", content_types, True, "No input was detected.")

        if envelope.confidence is not None and envelope.provider == "assemblyai":
            # Low-confidence voice turns should not trigger actions blindly.
            from config import settings
            if envelope.confidence < settings.assemblyai_min_confidence:
                return NormalizationResult(
                    envelope,
                    "uncertain_voice_input",
                    content_types,
                    True,
                    "The speech transcript confidence is low enough that a clarification is safer than acting on it.",
                )

        # Simple intent hint; the LLM planner can override this.
        if any(k in lower for k in ("build", "create", "make", "write", "code", "program")):
            intent = "coding"
        elif any(k in lower for k in ("solve", "equation", "calculate", "integral", "derivative")):
            intent = "math"
        elif lower in {"hi", "hello", "hey", "kem cho", "how are you"}:
            intent = "conversation"
        elif any(k in lower for k in ("go home", "home", "ghar", "ghare")):
            intent = "travel_or_navigation"
        else:
            intent = "general"

        return NormalizationResult(envelope, intent, content_types, False)
