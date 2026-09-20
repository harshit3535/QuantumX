from __future__ import annotations

from dataclasses import dataclass

from core.models import StructuredResponse


@dataclass(frozen=True)
class OutputDecision:
    render_ui: bool
    speak: bool
    reason: str


class OutputRouter:
    """Keeps presentation policy outside the AOB and agents."""

    def decide(self, mode: str, input_mode: str, response: StructuredResponse) -> OutputDecision:
        if mode == "hackathon":
            # Voice-first hackathon UI: speak the answer; UI is only an optional
            # developer/debug surface and is not the required chat interface.
            return OutputDecision(render_ui=True, speak=True, reason="Hackathon voice-first output")

        # Personal mode: voice input normally produces speech + rich UI;
        # text input stays text-first.
        if input_mode == "voice":
            return OutputDecision(render_ui=True, speak=True, reason="Personal voice output")
        return OutputDecision(render_ui=True, speak=False, reason="Personal text output")
