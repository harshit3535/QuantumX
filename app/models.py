"""Data contracts shared by every layer.

Nothing here knows about AssemblyAI, TTS engines or the web UI.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .errors import ErrorInfo

Language = Literal["en", "gu", "hi", "und"]
Modality = Literal["voice", "text"]


# ----------------------------------------------------------------- requests
class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=8000)
    source: Literal["text", "voice"] = "text"
    language: str = "auto"
    mode: Literal["hackathon", "personal"] = "personal"
    output: Literal["auto", "voice", "text", "both"] = "auto"
    stt_provider: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    title: str


# ------------------------------------------------- normalized (AOB input)
class NormalizedRequest(BaseModel):
    """What the brain sees. It does not care whether the user typed or spoke."""

    original_text: str            # never destroyed
    text: str                     # cleaned
    language: Language = "und"
    romanized: bool = False       # Gujarati/Hindi written in Latin letters
    script: str = "latin"
    modality: Modality = "text"
    mode: str = "personal"
    output_pref: str = "auto"

    has_code: bool = False
    has_math: bool = False
    is_question: bool = False
    is_command: bool = False
    is_conversational: bool = False
    is_incomplete: bool = False
    needs_clarification: bool = False
    clarification_reason: str | None = None

    has_reference: bool = False   # "it", "the previous code", "એમાં" ...
    reference_hint: str | None = None   # code | math | any
    read_aloud: bool = False      # "read the code aloud"
    followup_style: bool = False  # "Make the button blue." (edit-like, may point at earlier work)

    intent_hint: Literal["task", "question", "conversation", "statement", "unclear"] = "statement"

    @property
    def content_types(self) -> list[str]:
        out = []
        if self.has_code:
            out.append("code")
        if self.has_math:
            out.append("math")
        return out or ["text"]


# ---------------------------------------------------------- context bundle
class ContextBundle(BaseModel):
    session_id: str = ""
    history: list[dict[str, Any]] = []       # recent messages (role, content, source)
    task_state: dict[str, Any] = {}
    referent: dict[str, Any] | None = None   # artifact the user is pointing at
    reference_unresolved: bool = False
    learned_note: str | None = None          # recalled from earlier users' clarified errors (background-learned)
    prior_error: str | None = None           # this session's most recent error, if any (used to key learning)

    def render(self, max_chars: int = 6000) -> str:
        """Compact text form for prompts (history is NOT one giant blob: it is budgeted)."""
        parts: list[str] = []
        goal = self.task_state.get("last_goal")
        if goal:
            parts.append(f"Current/last task: {goal}")
        if self.referent:
            r = self.referent
            label = r.get("filename") or r.get("type", "artifact")
            body = r.get("content", "")
            if r.get("type") == "code":
                parts.append(f"The user is referring to this previous {r.get('language','')} code ({label}):\n```{r.get('language','')}\n{body}\n```")
            else:
                parts.append(f"The user is referring to this previous {r.get('type')} result:\n{body}")
        if self.learned_note:
            parts.append(f"A similar question was clarified before; this explanation may already apply:\n{self.learned_note}")
        if self.history:
            lines = []
            for m in self.history[-12:]:
                who = "User" if m.get("role") == "user" else "Assistant"
                lines.append(f"{who}: {str(m.get('content',''))[:600]}")
            parts.append("Recent conversation:\n" + "\n".join(lines))
        text = "\n\n".join(parts)
        return text[-max_chars:] if len(text) > max_chars else text


# ------------------------------------------------------- structured output
SegmentType = Literal["text", "code", "math", "table", "list", "link", "warning", "error", "image", "file"]


class Segment(BaseModel):
    type: SegmentType
    content: str = ""
    language: str | None = None
    filename: str | None = None
    display: bool = True                # math: block (True) or inline (False)
    header: list[str] = []
    rows: list[list[str]] = []
    items: list[str] = []
    ordered: bool = False
    speak: str | None = None            # optional explicit spoken form


class StructuredResponse(BaseModel):
    response_type: Literal["text", "code", "math", "table", "mixed", "clarification", "error"] = "text"
    segments: list[Segment] = []

    def plain_text(self) -> str:
        parts = []
        for s in self.segments:
            if s.type in {"text", "warning", "error", "link"}:
                parts.append(s.content)
            elif s.type == "list":
                parts.extend(("- " + i) for i in s.items)
            elif s.type == "math":
                parts.append(s.content)
            elif s.type == "code":
                parts.append(f"[{s.language or 'code'}{' ' + s.filename if s.filename else ''}]")
        return "\n".join(p for p in parts if p).strip()

    def kinds(self) -> set[str]:
        return {s.type for s in self.segments}


# ------------------------------------------------------------------ agents
class AgentResult(BaseModel):
    agent: str
    status: Literal["success", "error", "skipped"] = "success"
    segments: list[Segment] = []
    spoken: str = ""
    data: dict[str, Any] = {}
    error: ErrorInfo | None = None

    @property
    def text(self) -> str:
        return "\n".join(s.content for s in self.segments if s.type == "text").strip()

    def brief(self, limit: int = 1500) -> str:
        """What downstream agents receive as dependency input."""
        bits = []
        for s in self.segments:
            if s.type == "code":
                bits.append(f"```{s.language or ''}\n{s.content}\n```")
            elif s.type == "math":
                bits.append(f"$${s.content}$$")
            elif s.type in {"text", "warning"}:
                bits.append(s.content)
        return "\n".join(bits)[:limit]


# -------------------------------------------------------------------- plan
class PlanStep(BaseModel):
    id: int
    agent: str
    task: str
    depends_on: list[int] = []
    optional: bool = False
    expected_output: str = ""


class Plan(BaseModel):
    kind: Literal["task", "question", "conversation", "partial", "unclear", "unsupported"] = "question"
    goal: str = ""
    confidence: float = 0.5
    steps: list[PlanStep] = []
    needs_clarification: bool = False
    clarification_question: str | None = None
    may_need_followup: bool = False
    direct_action: str | None = None     # e.g. "read_code_aloud"
    source: Literal["rule", "heuristic", "llm"] = "heuristic"


class StepTrace(BaseModel):
    id: int
    agent: str
    task: str
    status: Literal["success", "error", "skipped"]
    attempts: int = 1
    duration_ms: int = 0
    iteration: int = 1
    issues: list[str] = []
    error: ErrorInfo | None = None


# ------------------------------------------------------------------ output
class OutputDecision(BaseModel):
    display: bool = True
    speak: bool = False
    speech_text: str = ""
    speech_lang: str = "en-US"
    tts_provider: str = "browser"
    reason: str = ""
    read_code_aloud: bool = False


class ChatResponse(BaseModel):
    session_id: str
    mode: str
    user_message: str
    normalized: dict[str, Any]
    plan: Plan
    trace: list[StepTrace]
    response: StructuredResponse
    output: OutputDecision
    iterations: int = 1
    error: ErrorInfo | None = None
