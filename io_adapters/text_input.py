from __future__ import annotations

from core.models import InputEnvelope


def build_text_envelope(text: str, mode: str) -> InputEnvelope:
    return InputEnvelope(text=text, mode=mode, input_mode="text", provider="text")
