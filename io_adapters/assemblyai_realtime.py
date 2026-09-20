from __future__ import annotations

import threading
from typing import Callable, Optional

import pyaudio
from assemblyai.streaming.v3 import (
    BeginEvent,
    RealTimeEvents,
    RealTimeParameters,
    RealTimeSessionParameters,
    RealTimeTranscriber,
    RealTimeTranscriberOptions,
    RealTimeError,
    TerminationEvent,
    TurnEvent,
)

from config import settings


class AssemblyAIRealtimeAdapter:
    """Hackathon-mode voice input using AssemblyAI's current v3 streaming SDK."""

    def __init__(
        self,
        on_partial: Callable[[str], None],
        on_final: Callable[[str, float | None], None],
        on_status: Callable[[str], None],
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_status = on_status
        self.on_error = on_error or (lambda _: None)
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.client: Optional[RealTimeTranscriber] = None

    def start(self) -> None:
        if not settings.assemblyai_api_key:
            self.on_error("ASSEMBLYAI_API_KEY is missing in .env")
            return
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="assemblyai-stream", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        try:
            if self.client:
                self.client.disconnect(terminate=True)
        except Exception as exc:
            self.on_error(f"AssemblyAI disconnect error: {exc}")

    def set_agent_context(self, text: str) -> None:
        if not self.client or not text.strip():
            return
        try:
            self.client.set_params(RealTimeSessionParameters(agent_context=text))
        except Exception as exc:
            self.on_error(f"Could not update AssemblyAI agent context: {exc}")

    def _run(self) -> None:
        pa = None
        mic = None
        try:
            self.on_status("Connecting to AssemblyAI...")
            self.client = RealTimeTranscriber(
                RealTimeTranscriberOptions(terminate_timeout=30.0),
                api_key=settings.assemblyai_api_key,
            )
            self.client.on(RealTimeEvents.Begin, self._on_begin)
            self.client.on(RealTimeEvents.Turn, self._on_turn)
            self.client.on(RealTimeEvents.Termination, self._on_terminated)
            self.client.on(RealTimeEvents.Error, self._on_error)
            self.client.connect(
                RealTimeParameters(
                    speech_model=settings.assemblyai_speech_model,
                    sample_rate=settings.assemblyai_sample_rate,
                    mode=settings.assemblyai_mode,
                    min_turn_silence=settings.assemblyai_min_turn_silence,
                    max_turn_silence=settings.assemblyai_max_turn_silence,
                )
            )

            pa = pyaudio.PyAudio()
            mic = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=settings.assemblyai_sample_rate,
                input=True,
                frames_per_buffer=800,
            )
            self.on_status("Listening...")

            while not self.stop_event.is_set():
                audio = mic.read(800, exception_on_overflow=False)
                self.client.stream(audio)
        except Exception as exc:
            self.on_error(str(exc))
        finally:
            try:
                if mic:
                    mic.stop_stream()
                    mic.close()
            except Exception:
                pass
            try:
                if pa:
                    pa.terminate()
            except Exception:
                pass
            try:
                if self.client:
                    self.client.disconnect(terminate=True)
            except Exception as exc:
                self.on_error(f"AssemblyAI termination error: {exc}")
            self.client = None
            self.on_status("Stopped")

    def _on_begin(self, client: RealTimeTranscriber, event: BeginEvent) -> None:
        self.on_status(f"AssemblyAI session: {event.id}")

    def _on_turn(self, client: RealTimeTranscriber, event: TurnEvent) -> None:
        transcript = (event.transcript or "").strip()
        if not transcript:
            return
        self.on_partial(transcript)
        if event.end_of_turn:
            self.on_final(transcript, getattr(event, "end_of_turn_confidence", None))

    def _on_terminated(self, client: RealTimeTranscriber, event: TerminationEvent) -> None:
        self.on_status("AssemblyAI session terminated")

    def _on_error(self, client: RealTimeTranscriber, error: RealTimeError) -> None:
        self.on_error(f"AssemblyAI error: {error}")
