from __future__ import annotations

import queue
import tkinter as tk

from core.models import InputEnvelope
from io_adapters.assemblyai_realtime import AssemblyAIRealtimeAdapter
from ui.base import BaseWindow
from ui.theme import ACCENT, BG, FONT, MUTED, PANEL, SUCCESS, TEXT, TITLE, WARN
from ui.widgets import RichResponseView, StatusBar


class HackathonWindow(BaseWindow):
    """Voice-first AssemblyAI demo UI. No text chat box is required for this mode."""

    def __init__(self, master, orchestrator, on_back):
        self.events: queue.Queue = queue.Queue()
        super().__init__(master, "AOB v1.0 — Hackathon Mode", "hackathon", orchestrator, on_back)
        self._build()
        self.adapter = AssemblyAIRealtimeAdapter(
            self._on_partial,
            self._on_final,
            self._on_status,
            self._on_error,
        )
        self.after(100, self._drain_events)

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=18, pady=(18, 10))
        tk.Label(header, text="ASSEMBLYAI VOICE AGENT", fg=TEXT, bg=BG, font=TITLE).pack(side="left")
        tk.Label(header, text="Hackathon Mode • voice-first UI", fg=ACCENT, bg=BG, font=FONT).pack(side="right")

        controls = tk.Frame(self, bg=BG)
        controls.pack(fill="x", padx=18, pady=8)
        self.start_btn = tk.Button(controls, text="🎤 Start Listening", command=self.start_listening, bg=PANEL, fg=TEXT, relief="flat", padx=14, pady=10)
        self.start_btn.pack(side="left")
        self.stop_btn = tk.Button(controls, text="■ Stop", command=self.stop_listening, bg=PANEL, fg=TEXT, relief="flat", padx=14, pady=10, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        tk.Button(controls, text="← Mode Select", command=self._close, bg=PANEL, fg=MUTED, relief="flat", padx=14, pady=10).pack(side="right")

        self.status = tk.Label(self, text="Ready to connect to AssemblyAI", bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.status.pack(fill="x", padx=18, pady=(0, 8))

        self.partial = tk.StringVar(value="")
        tk.Label(self, textvariable=self.partial, bg=BG, fg=WARN, font=("Segoe UI", 12), anchor="w", wraplength=880, justify="left").pack(fill="x", padx=18, pady=8)

        self.view = RichResponseView(self)
        self.view.pack(fill="both", expand=True, padx=18, pady=8)
        self.bar = StatusBar(self)
        self.bar.pack(fill="x", padx=18, pady=(8, 18))
        self.log("Ready. Press Start Listening.")

    def start_listening(self):
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.adapter.start()

    def stop_listening(self):
        self.adapter.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _on_partial(self, text: str):
        self.events.put(("partial", text))

    def _on_final(self, text: str, confidence: float | None):
        self.events.put(("final", text, confidence))

    def _on_status(self, text: str):
        self.events.put(("status", text))

    def _on_error(self, text: str):
        self.events.put(("error", text))

    def _drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "partial":
                    self.partial.set(f"Listening: {event[1]}")
                elif kind == "final":
                    text, confidence = event[1], event[2]
                    self.partial.set("")
                    self.bar.set(f"Final transcript • confidence={confidence if confidence is not None else 'n/a'}")
                    envelope = InputEnvelope(
                        text=text,
                        mode="hackathon",
                        input_mode="voice",
                        provider="assemblyai",
                        confidence=confidence,
                    )
                    response = self.handle_envelope(envelope, speak_override=True)
                    if response:
                        self.view.append("Assistant", response.segments)
                        if self.adapter.client and response.spoken_text:
                            self.adapter.set_agent_context(response.spoken_text)
                elif kind == "status":
                    self.status.config(text=event[1], fg=SUCCESS)
                    self.log(event[1])
                elif kind == "error":
                    self.status.config(text=event[1], fg=WARN)
                    self.log(f"ERROR: {event[1]}")
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def log(self, message: str):
        self.bar.set(message)
