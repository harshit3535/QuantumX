from __future__ import annotations

import re
from typing import Iterable

from core.models import ResponseSegment, StructuredResponse


class ResponseParser:
    """Converts LLM markdown-ish output into typed segments."""

    FENCED_CODE = re.compile(r"```(?P<lang>[\w+#.-]*)\s*\n?(?P<code>.*?)```", re.S)

    def parse(self, raw: str, expected_types: Iterable[str] | None = None) -> StructuredResponse:
        raw = (raw or "").strip()
        if not raw:
            return StructuredResponse([ResponseSegment("text", "I don't have a response yet.")])

        segments: list[ResponseSegment] = []
        pos = 0
        for match in self.FENCED_CODE.finditer(raw):
            before = raw[pos : match.start()].strip()
            if before:
                segments.extend(self._parse_math(before))
            lang = match.group("lang") or "text"
            code = match.group("code").strip("\n")
            segments.append(ResponseSegment("code", code, language=lang))
            pos = match.end()

        tail = raw[pos:].strip()
        if tail:
            segments.extend(self._parse_math(tail))

        spoken = self.to_speech(segments)
        return StructuredResponse(segments=segments, spoken_text=spoken)

    def _parse_math(self, text: str) -> list[ResponseSegment]:
        lines = text.splitlines()
        out: list[ResponseSegment] = []
        for line in lines:
            stripped = line.strip()
            looks_math = (
                stripped.startswith("$$")
                or stripped.startswith("\\[")
                or ("=" in stripped and any(ch in stripped for ch in ("²", "√", "∫", "π", "^")))
            )
            if looks_math:
                out.append(ResponseSegment("math", stripped))
            elif stripped:
                out.append(ResponseSegment("text", stripped))
        return out

    def to_speech(self, segments: list[ResponseSegment]) -> str:
        spoken: list[str] = []
        for segment in segments:
            if segment.type == "text":
                spoken.append(segment.content)
            elif segment.type == "code":
                spoken.append(
                    f"I generated {segment.language or 'programming'} code. "
                    "The complete code is available in the interface."
                )
            elif segment.type == "math":
                spoken.append(self.math_to_speech(segment.content))
            elif segment.type == "warning":
                spoken.append(f"Warning. {segment.content}")
            elif segment.type == "error":
                spoken.append(f"Error. {segment.content}")
        return " ".join(spoken).strip()

    @staticmethod
    def math_to_speech(text: str) -> str:
        cleaned = text.replace("\\", " ")
        replacements = {
            "√": " square root of ",
            "²": " squared ",
            "³": " cubed ",
            "±": " plus or minus ",
            "×": " times ",
            "÷": " divided by ",
            "=": " equals ",
            "^": " to the power of ",
            "/": " divided by ",
        }
        for a, b in replacements.items():
            cleaned = cleaned.replace(a, b)
        return " ".join(cleaned.split())
