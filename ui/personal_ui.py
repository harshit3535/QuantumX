from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox

from core.models import InputEnvelope, ResponseSegment
from io_adapters.local_whisper import LocalWhisperSTT
from ui.base import BaseWindow
from ui.theme import ACCENT, BG, FONT, MUTED, PANEL, TEXT, TITLE, SUCCESS, WARN
from ui.widgets import RichResponseView, StatusBar


class PersonalWindow(BaseWindow):
    def __init__(self, master, orchestrator, on_back):
        self.events: queue.Queue = queue.Queue()
        super().__init__(master, "AOB v1.0 — Personal Mode", "personal", orchestrator, on_back)
        self._build()
        self.personal_stt = LocalWhisperSTT(self._on_status, self._on_stt_result, self._on_error)
        self.after(100, self._drain_events)

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=18, pady=(18, 10))
        tk.Label(header, text="PERSONAL AI — AOB v1.0", fg=TEXT, bg=BG, font=TITLE).pack(side="left")
        tk.Label(header, text="Voice + Text + Rich Output", fg=ACCENT, bg=BG, font=FONT).pack(side="right")

        controls = tk.Frame(self, bg=BG)
        controls.pack(fill="x", padx=18, pady=8)
        tk.Button(controls, text="🎤 Local Voice", command=self.start_voice, bg=PANEL, fg=TEXT, relief="flat", padx=14, pady=10).pack(side="left")
        tk.Button(controls, text="Clear History", command=self.clear_history, bg=PANEL, fg=MUTED, relief="flat", padx=14, pady=10).pack(side="left", padx=8)
        tk.Button(controls, text="← Mode Select", command=self._close, bg=PANEL, fg=MUTED, relief="flat", padx=14, pady=10).pack(side="right")

        self.status = tk.Label(self, text="Ready", bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.status.pack(fill="x", padx=18, pady=4)

        input_frame = tk.Frame(self, bg=BG)
        input_frame.pack(fill="x", padx=18, pady=8)
        self.entry = tk.Entry(input_frame, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=10)
        self.entry.bind("<Return>", lambda _: self.send_text())
        tk.Button(input_frame, text="Send", command=self.send_text, bg=PANEL, fg=TEXT, relief="flat", padx=16, pady=9).pack(side="left", padx=(8, 0))

        self.view = RichResponseView(self)
        self.view.pack(fill="both", expand=True, padx=18, pady=8)
        self.bar = StatusBar(self)
        self.bar.pack(fill="x", padx=18, pady=(8, 18))

    def send_text(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self.view.append("You", [ResponseSegment("text", text)])
        response = self.handle_envelope(InputEnvelope(text=text, mode="personal", input_mode="text", provider="text"), speak=False)
        if response:
            self.view.append("Assistant", response.segments)
            self.bar.set(f"Intent: {response.metadata.get('intent', 'unknown')} • Agents: {', '.join(s['agent'] for s in response.metadata.get('plan', []))}")

    def start_voice(self):
        self.status.config(text="Loading local STT and listening...", fg=SUCCESS)
        self.personal_stt.start()

    def _on_stt_result(self, text: str):
        self.events.put(("voice", text))

    def _on_status(self, text: str):
        self.events.put(("status", text))

    def _on_error(self, text: str):
        self.events.put(("error", text))

    def _drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "voice":
                    text = event[1]
                    self.view.append("You (voice)", [ResponseSegment("text", text)])
                    envelope = InputEnvelope(text=text, mode="personal", input_mode="voice", provider="local_stt")
                    response = self.handle_envelope(envelope, speak_override=True)
                    if response:
                        self.view.append("Assistant", response.segments)
                        self.bar.set(f"Voice response • intent={response.metadata.get('intent', 'unknown')}")
                elif event[0] == "status":
                    self.status.config(text=event[1], fg=SUCCESS)
                    self.bar.set(event[1])
                elif event[0] == "error":
                    self.status.config(text=event[1], fg=WARN)
                    self.bar.set(event[1])
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def clear_history(self):
        if messagebox.askyesno("Clear History", "Clear stored conversation history and task state?"):
            self.orchestrator.history.clear()
            self.view.clear()
            self.bar.set("History cleared")
