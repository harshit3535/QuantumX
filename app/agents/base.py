"""Agent contract.

An agent is `async (task: str, ctx: AgentContext) -> AgentResult`.
Agents are modality-independent: they never know about STT, TTS or the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..llm.router import LLMRouter
from ..models import AgentResult, ContextBundle, NormalizedRequest


@dataclass
class AgentContext:
    request: NormalizedRequest
    context: ContextBundle
    router: LLMRouter
    deps: dict[int, AgentResult] = field(default_factory=dict)   # outputs of steps this step depends on
    feedback: str = ""                                            # validator feedback on a retry
    attempt: int = 1

    def dep_text(self, limit: int = 3500) -> str:
        parts = [f"[{r.agent} output]\n{r.brief()}" for r in self.deps.values() if r.status == "success"]
        return "\n\n".join(parts)[:limit]

    def language_rule(self) -> str:
        """How the agent should write its reply for this user."""
        r = self.request
        keep = " Keep code, file names and math notation in their normal form."
        if r.language == "gu":
            if r.romanized and r.modality == "text":
                return "The user writes Gujarati using English letters. Reply in casual Gujarati written with English letters (romanized), the same way." + keep
            return "Reply in Gujarati using Gujarati script (ગુજરાતી)." + keep
        if r.language == "hi":
            if r.romanized and r.modality == "text":
                return "The user writes Hindi using English letters. Reply in casual Hindi written with English letters (romanized)." + keep
            return "Reply in Hindi using Devanagari script." + keep
        return "Reply in English." + keep

    def voice_rule(self) -> str:
        if self.request.modality == "voice" or self.request.mode == "hackathon":
            return " The answer will be spoken aloud: use short natural sentences, no tables, no long lists, no emoji."
        return ""


Handler = Callable[[str, AgentContext], Awaitable[AgentResult]]


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str       # shown to the planner
    handler: Handler
    needs_llm: bool = True
    usage: str = ""         # short "when to use this vs. others" hint for the planner
