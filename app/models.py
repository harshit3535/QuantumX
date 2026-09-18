from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=20000)
    source: Literal["text", "voice"] = "text"
    language: str = "en"


class SessionResponse(BaseModel):
    session_id: str
    title: str


class AgentPlanStep(BaseModel):
    id: int
    agent: str
    task: str
    input_from: list[str] = []
    expected_output: str = ""
    depends_on: list[int] = []


class Plan(BaseModel):
    intent: Literal["task", "question", "conversation", "clarification", "unknown"]
    goal: str
    confidence: float = 0.5
    steps: list[AgentPlanStep] = []
    response_mode: Literal["text", "math", "code", "table", "conversation"] = "text"
    needs_clarification: bool = False
    clarification_question: str | None = None


class AgentResult(BaseModel):
    agent: str
    status: Literal["success", "error", "skipped"]
    summary: str = ""
    data: dict[str, Any] = {}
    spoken_response: str = ""
    visual_type: str = "text"
    citations: list[str] = []


class ChatResponse(BaseModel):
    session_id: str
    user_message: str
    plan: Plan
    results: list[AgentResult]
    final: AgentResult
