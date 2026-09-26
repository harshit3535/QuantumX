from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from core.models import InputEnvelope, ResponseSegment
from llm.base import LLMClient


class Agent(ABC):
    name: str = "base"

    def __init__(self, llm: LLMClient, log: Optional[Callable[[str], None]] = None) -> None:
        self.llm = llm
        self.log = log or (lambda _: None)

    @abstractmethod
    def run(self, task: str, envelope: InputEnvelope, context: str, previous_results: dict[str, str]) -> list[ResponseSegment]:
        raise NotImplementedError

    def _call_llm(self, system: str, user: str) -> str:
        self.log(f"{self.name}: calling LLM")
        return self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
