"""Central mode configuration.

Two products of the same brain:

  hackathon  -> voice-first, AssemblyAI is the STT provider
  personal   -> voice + text, free/own STT and TTS, rich text UI

Only the *edges* (input adapter, output adapter, UI) depend on the mode.
The Agent Orchestration Brain never reads this config.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Mode = Literal["hackathon", "personal"]
InputMode = Literal["voice", "text"]
OutputPref = Literal["auto", "voice", "text", "both"]


@dataclass
class ModeConfig:
    mode: Mode = "personal"
    input_mode: InputMode = "text"
    stt_provider: str = "text"          # assemblyai | groq_whisper | browser | text
    tts_provider: str = "browser"       # browser | (future: server engines)
    output_pref: OutputPref = "auto"
    ui_mode: str = "personal_ui"        # hackathon_ui | personal_ui
    can_display: bool = True            # does the client have a screen to show rich output?

    def as_dict(self) -> dict:
        return asdict(self)


def build_mode_config(mode: str, input_mode: str, output_pref: str = "auto", stt_provider: str | None = None) -> ModeConfig:
    mode = "hackathon" if mode == "hackathon" else "personal"
    input_mode = "voice" if input_mode == "voice" else "text"
    output_pref = output_pref if output_pref in {"auto", "voice", "text", "both"} else "auto"

    if mode == "hackathon":
        stt = stt_provider or ("assemblyai" if input_mode == "voice" else "text")
        return ModeConfig("hackathon", input_mode, stt, "browser", output_pref, "hackathon_ui", True)

    stt = stt_provider or ("groq_whisper" if input_mode == "voice" else "text")
    return ModeConfig("personal", input_mode, stt, "browser", output_pref, "personal_ui", True)
