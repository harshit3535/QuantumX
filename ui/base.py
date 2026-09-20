from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.models import InputEnvelope, StructuredResponse
from core.output_router import OutputRouter
from core.orchestrator import AgentOrchestrator
from io_adapters.tts import TTSAdapter
from ui.theme import BG, FONT, MUTED, PANEL, TEXT, TITLE


class BaseWindow(tk.Toplevel):
    def __init__(self, master, title: str, mode: str, orchestrator: AgentOrchestrator, on_back: Callable[[], None]):
        super().__init__(master)
        self.mode = mode
        self.orchestrator = orchestrator
        self.on_back = on_back
        self.tts = TTSAdapter(self.log)
        self.output_router = OutputRouter()
        self.title(title)
        self.geometry("980x720")
        self.minsize(800, 560)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self):
        self.on_back()
        self.destroy()

    def log(self, message: str):
        # Overridden by concrete UIs.
        pass

    def handle_envelope(self, envelope: InputEnvelope, speak_override: bool | None = None):
        try:
            response = self.orchestrator.handle(envelope)
        except Exception as exc:
            self.log(f"Pipeline error: {exc}")
            return None
        decision = self.output_router.decide(envelope.mode, envelope.input_mode, response)
        should_speak = decision.speak if speak_override is None else speak_override
        if should_speak and response.spoken_text:
            self.tts.speak(response.spoken_text)
        return response
