from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        raise NotImplementedError

    def is_configured(self) -> bool:
        return True

    def info(self) -> dict[str, Any]:
        return {}
