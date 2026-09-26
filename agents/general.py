from __future__ import annotations

from agents.base import Agent
from core.models import InputEnvelope, ResponseSegment


class GeneralAgent(Agent):
    name = "general"

    def run(self, task: str, envelope: InputEnvelope, context: str, previous_results: dict[str, str]) -> list[ResponseSegment]:
        prompt = (
            f"User request: {envelope.text}\n\n"
            f"Conversation context:\n{context or '(none)'}\n\n"
            f"Agent task: {task}\n"
            "Respond naturally. If the request is ambiguous, ask one concise clarifying question instead of inventing missing details."
        )
        raw = self._call_llm(
            "You are the General Agent in a multi-agent assistant. Be useful, concise, and context-aware.",
            prompt,
        )
        return [ResponseSegment("text", raw.strip())]
