from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List

from config import settings
from core.models import HistoryTurn


class HistoryManager:
    """Persistent short-term conversation + task-state memory."""

    def __init__(self, path: Path | None = None, max_turns: int | None = None) -> None:
        self.path = path or settings.history_file
        self.max_turns = max_turns or settings.history_max_turns
        self._lock = threading.Lock()
        self.turns: List[HistoryTurn] = []
        self.task_state: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.turns = [HistoryTurn(**item) for item in data.get("turns", [])][-self.max_turns :]
            self.task_state = dict(data.get("task_state", {}))
        except (OSError, ValueError, TypeError):
            self.turns = []
            self.task_state = {}

    def _save(self) -> None:
        payload = {
            "turns": [turn.__dict__ for turn in self.turns[-self.max_turns :]],
            "task_state": self.task_state,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, turn: HistoryTurn) -> None:
        with self._lock:
            self.turns.append(turn)
            self.turns = self.turns[-self.max_turns :]
            self._save()

    def set_task_state(self, **kwargs: str) -> None:
        with self._lock:
            self.task_state.update({k: str(v) for k, v in kwargs.items()})
            self._save()

    def recent(self, limit: int = 12) -> List[HistoryTurn]:
        with self._lock:
            return list(self.turns[-limit:])

    def prompt_context(self, limit: int = 12) -> str:
        lines: List[str] = []
        for turn in self.recent(limit):
            label = "User" if turn.role == "user" else "Assistant"
            lines.append(f"{label}: {turn.content}")
        if self.task_state:
            state = "; ".join(f"{k}={v}" for k, v in self.task_state.items())
            lines.append(f"Task state: {state}")
        return "\n".join(lines)

    def clear(self) -> None:
        with self._lock:
            self.turns.clear()
            self.task_state.clear()
            self._save()
