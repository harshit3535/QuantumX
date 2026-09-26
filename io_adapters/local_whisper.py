from __future__ import annotations

import os
import tempfile
import threading
import wave
from typing import Callable, Optional

import pyaudio

from config import settings


class LocalWhisperSTT:
    """Optional personal-mode STT using local faster-whisper."""

    def __init__(self, on_status: Callable[[str], None], on_result: Callable[[str], None], on_error: Optional[Callable[[str], None]] = None) -> None:
        self.on_status = on_status
        self.on_result = on_result
        self.on_error = on_error or (lambda _: None)
        self._thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self._model = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("Personal voice mode needs the optional 'faster-whisper' package. Install requirements-personal.txt.") from exc
            self.on_status(f"Loading local Whisper model: {settings.personal_stt_model}")
            self._model = WhisperModel(
                settings.personal_stt_model,
                device=settings.personal_stt_device,
                compute_type=settings.personal_stt_compute_type,
            )
        return self._model

    def _run(self) -> None:
        pa = None
        stream = None
        wav_path = None
        try:
            model = self._load_model()
            pa = pyaudio.PyAudio()
            rate = 16000
            frames_per_buffer = 800
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=rate,
                input=True,
                frames_per_buffer=frames_per_buffer,
            )
            self.on_status("Personal STT listening...")
            frames = []
            for _ in range(max(1, int(settings.personal_record_seconds * rate / frames_per_buffer))):
                if self.stop_event.is_set():
                    break
                frames.append(stream.read(frames_per_buffer, exception_on_overflow=False))

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                wav_path = tmp.name
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(rate)
                wf.writeframes(b"".join(frames))

            language = settings.personal_stt_language or None
            segments, _ = model.transcribe(wav_path, language=language, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            if text:
                self.on_result(text)
            else:
                self.on_status("No speech detected")
        except Exception as exc:
            self.on_error(str(exc))
        finally:
            try:
                if stream:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if pa:
                    pa.terminate()
            except Exception:
                pass
            if wav_path:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
            self.on_status("Personal STT stopped")
