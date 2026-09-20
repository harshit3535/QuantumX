from __future__ import annotations

import threading

from config import settings


class TTSAdapter:
    def __init__(self, log=None) -> None:
        self.log = log or (lambda _: None)
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        if not settings.tts_enabled or not text.strip():
            return
        thread = threading.Thread(target=self._speak_blocking, args=(text,), daemon=True)
        thread.start()

    def _speak_blocking(self, text: str) -> None:
        try:
            import pyttsx3
            with self._lock:
                engine = pyttsx3.init()
                engine.setProperty("rate", settings.tts_rate)
                engine.setProperty("volume", settings.tts_volume)
                engine.say(text)
                engine.runAndWait()
                engine.stop()
        except Exception as exc:
            self.log(f"TTS: unavailable ({exc})")
