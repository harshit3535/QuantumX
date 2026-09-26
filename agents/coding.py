from __future__ import annotations

from agents.base import Agent
from core.models import InputEnvelope, ResponseSegment
from core.response import ResponseParser


class CodingAgent(Agent):
    name = "coding"

    def run(self, task: str, envelope: InputEnvelope, context: str, previous_results: dict[str, str]) -> list[ResponseSegment]:
        prompt = (
            f"Original request: {envelope.text}\n\n"
            f"Coding task: {task}\n\n"
            f"Conversation context:\n{context or '(none)'}\n\n"
            "Previous agent results:\n"
            + "\n\n".join(f"[{k}] {v}" for k, v in previous_results.items())
            + "\n\n"
            "Return a useful implementation. Put source code in fenced code blocks with the language name. "
            "Explain important design choices briefly. Do not claim to have executed code unless it was actually executed."
        )
        raw = self._call_llm(
            "You are the Coding Agent. Produce correct, maintainable code with preserved indentation and language labels. Avoid unsafe shell commands unless explicitly required.",
            prompt,
        )
        return ResponseParser().parse(raw).segments
