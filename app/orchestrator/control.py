"""Astra v2.4 mission control layer.

This layer turns the existing AOB into a visible, stateful workflow without
changing the core agent contract. It is deliberately provider-agnostic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..models import NormalizedRequest, Plan, StepTrace


PHASE_ORDER = ["UNDERSTAND", "PLAN", "EXECUTE", "VERIFY", "APPROVAL", "FINALIZE", "DONE"]

TOOLS: dict[str, dict[str, Any]] = {
    "context": {"label": "Context & memory", "phase": "UNDERSTAND", "kind": "read"},
    "planner": {"label": "Mission planner", "phase": "PLAN", "kind": "reason"},
    "web_search": {"label": "Live web search", "phase": "EXECUTE", "kind": "external-read"},
    "math_solver": {"label": "Exact math solver", "phase": "EXECUTE", "kind": "deterministic"},
    "code_writer": {"label": "Code generation", "phase": "EXECUTE", "kind": "generate"},
    "research": {"label": "Knowledge research", "phase": "EXECUTE", "kind": "reason"},
    "summarizer": {"label": "Compression / summary", "phase": "EXECUTE", "kind": "transform"},
    "verifier": {"label": "Validation / review", "phase": "VERIFY", "kind": "check"},
    "artifact_store": {"label": "Artifact memory", "phase": "FINALIZE", "kind": "persist"},
    "voice_output": {"label": "Voice response", "phase": "FINALIZE", "kind": "output"},
}

AGENT_TOOLS: dict[str, list[str]] = {
    "general_agent": ["context"],
    "math_agent": ["context", "math_solver"],
    "code_agent": ["context", "code_writer"],
    "research_agent": ["context", "research"],
    "web_agent": ["context", "web_search"],
    "summarizer_agent": ["context", "summarizer"],
    "verifier_agent": ["context", "verifier"],
}

HIGH_IMPACT_PATTERNS = re.compile(
    r"\b(delete|destroy|erase|wipe|deploy|production|push|publish|send|payment|purchase|refund|transfer|approve|execute|shutdown|restart)\b|"
    r"(ડિલીટ|મોકલો|પુષ|ડિપ્લોય|बेरोक|डिलीट|भुगतान|भेज)", re.I,
)


@dataclass(frozen=True)
class ActionAssessment:
    risk: str
    approval_required: bool
    reason: str


def assess_action(req: NormalizedRequest, plan: Plan) -> ActionAssessment:
    text = f"{req.text} {plan.goal}".strip()
    if HIGH_IMPACT_PATTERNS.search(text):
        return ActionAssessment(
            risk="review",
            approval_required=True,
            reason="The request appears to involve an external, destructive, publishing, or irreversible action; Astra prepares the work first and keeps the final action behind a human approval gate.",
        )
    return ActionAssessment(risk="safe", approval_required=False, reason="No high-impact action was detected; the normal guarded workflow applies.")


def tools_for(plan: Plan) -> list[dict[str, Any]]:
    names: list[str] = ["context", "planner"]
    for step in plan.steps:
        for name in AGENT_TOOLS.get(step.agent, []):
            if name not in names:
                names.append(name)
    if any(s.agent == "verifier_agent" for s in plan.steps):
        if "verifier" not in names:
            names.append("verifier")
    for name in ["artifact_store", "voice_output"]:
        if name not in names:
            names.append(name)
    return [dict(id=n, **TOOLS[n], enabled=True) for n in names if n in TOOLS]


def phase_for_trace(trace: list[StepTrace], approval_required: bool = False) -> str:
    if approval_required:
        return "APPROVAL"
    if any(t.status == "error" for t in trace):
        return "VERIFY"
    if any(t.agent == "verifier_agent" for t in trace):
        return "VERIFY"
    if trace:
        return "EXECUTE"
    return "PLAN"


def build_mission(req: NormalizedRequest, plan: Plan, trace: list[StepTrace], iterations: int, *, done: bool, approval: ActionAssessment) -> dict[str, Any]:
    phase = "DONE" if done and not approval.approval_required else phase_for_trace(trace, approval.approval_required)
    completed = sum(1 for t in trace if t.status == "success")
    failed = sum(1 for t in trace if t.status == "error")
    return {
        "version": "2.4",
        "phase": phase,
        "phases": [
            {"id": p, "label": p.title(), "active": p == phase, "done": PHASE_ORDER.index(p) < PHASE_ORDER.index(phase) if p in PHASE_ORDER and phase in PHASE_ORDER else False}
            for p in PHASE_ORDER
        ],
        "risk": approval.risk,
        "approval_required": approval.approval_required,
        "approval_reason": approval.reason if approval.approval_required else "",
        "tools": tools_for(plan),
        "metrics": {
            "steps": len(trace),
            "successful_steps": completed,
            "failed_steps": failed,
            "iterations": iterations,
            "parallelism": len(trace) > 1,
        },
        "voice_first": req.mode == "hackathon" or req.modality == "voice",
        "assemblyai": req.mode == "hackathon" and req.modality == "voice",
    }
