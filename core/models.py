from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time


@dataclass
class InputEnvelope:
    text: str
    mode: str
    input_mode: str  # voice | text
    provider: str    # assemblyai | local_stt | text
    confidence: Optional[float] = None
    language: Optional[str] = None
    raw_text: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanStep:
    agent: str
    task: str
    depends_on: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    intent: str
    clarification_needed: bool = False
    clarification_question: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    expected_response_types: List[str] = field(default_factory=lambda: ["text"])
    notes: str = ""


@dataclass
class ResponseSegment:
    type: str  # text | code | math | table | warning | error
    content: str
    language: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredResponse:
    segments: List[ResponseSegment]
    spoken_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def plain_text(self) -> str:
        parts: List[str] = []
        for segment in self.segments:
            if segment.type == "code":
                parts.append(segment.content)
            else:
                parts.append(segment.content)
        return "\n\n".join(p for p in parts if p).strip()


@dataclass
class HistoryTurn:
    role: str
    content: str
    mode: str
    input_mode: Optional[str] = None
    response_types: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
