from __future__ import annotations

import tkinter as tk

from agents.factory import build_agents
from core.history import HistoryManager
from core.orchestrator import AgentOrchestrator
from llm.factory import build_llm
from ui.hackathon_ui import HackathonWindow
from ui.personal_ui import PersonalWindow
from ui.theme import ACCENT, BG, FONT, MUTED, PANEL, TEXT, TITLE


class ModeSelector(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AOB v1.0 — Mode Selector")
        self.geometry("780x480")
        self.minsize(680, 420)
        self.configure(bg=BG)
        self.llm = build_llm()
        self.history = HistoryManager()
        self.orchestrator = AgentOrchestrator(self.llm, self.history)
        self.active_window = None
        self._build()

    def _build(self):
        tk.Label(self, text="Agent Orchestration Brain", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 24)).pack(pady=(50, 8))
        tk.Label(
            self,
            text="One core AOB • two modes • pluggable STT/TTS • structured responses",
            bg=BG,
            fg=MUTED,
            font=FONT,
        ).pack(pady=(0, 35))

        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=55)

        hack = tk.Frame(cards, bg=PANEL)
        hack.pack(side="left", fill="both", expand=True, padx=(0, 12))
        tk.Label(hack, text="🎤 Hackathon Mode", bg=PANEL, fg=ACCENT, font=TITLE).pack(pady=(25, 8))
        tk.Label(hack, text="AssemblyAI Realtime\nVoice-first interface\nAOB + Agents + TTS", bg=PANEL, fg=TEXT, justify="center", font=FONT).pack(pady=8)
        tk.Button(hack, text="Launch Hackathon", command=self.open_hackathon, bg=BG, fg=TEXT, relief="flat", padx=16, pady=10).pack(pady=25)

        personal = tk.Frame(cards, bg=PANEL)
        personal.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(personal, text="🧠 Personal Mode", bg=PANEL, fg=ACCENT, font=TITLE).pack(pady=(25, 8))
        tk.Label(personal, text="Local STT (optional)\nText + Voice\nRich code/math UI", bg=PANEL, fg=TEXT, justify="center", font=FONT).pack(pady=8)
        tk.Button(personal, text="Launch Personal", command=self.open_personal, bg=BG, fg=TEXT, relief="flat", padx=16, pady=10).pack(pady=25)

        info = f"LLM: {self.llm.info().get('provider', 'unknown')}  •  Model: {self.llm.info().get('model', 'n/a')}"
        tk.Label(self, text=info, bg=BG, fg=MUTED, font=FONT).pack(pady=24)

    def _hide(self):
        self.withdraw()

    def _back(self):
        self.active_window = None
        self.deiconify()

    def open_hackathon(self):
        if self.active_window:
            return
        self._hide()
        self.active_window = HackathonWindow(self, self.orchestrator, self._back)

    def open_personal(self):
        if self.active_window:
            return
        self._hide()
        self.active_window = PersonalWindow(self, self.orchestrator, self._back)


def run():
    ModeSelector().mainloop()
