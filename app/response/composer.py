"""Result composition: agent results -> ONE structured response."""
from __future__ import annotations

from ..errors import ErrorInfo
from ..models import AgentResult, Plan, Segment, StructuredResponse
from .parser import guess_kind

_FRIENDLY = {
    "llm_unavailable": "I couldn't reach an AI model right now. Check that at least one API key (Gemini, Groq or OpenRouter) is set and has quota left.",
    "llm_rate_limited": "The free AI quota is busy for a moment. Please try again in a few seconds.",
    "llm_auth_failed": "An AI provider rejected its API key. Please check the key in the environment settings.",
    "llm_model_not_found": "The configured AI model name doesn't exist any more. Update the model name in the environment settings.",
    "agent_timeout": "That took too long, so I stopped. Try a smaller request.",
    "budget_exhausted": "That request needed too many steps, so I stopped safely. Try splitting it up.",
    "invalid_agent_output": "The AI answered in a format I couldn't use. Please try again.",
}


def friendly_error(err: ErrorInfo | None) -> str:
    if err is None:
        return "Something went wrong on my side. Please try again."
    return _FRIENDLY.get(err.kind, err.message or "Something went wrong on my side. Please try again.")


def clarification_response(question: str) -> StructuredResponse:
    return StructuredResponse(response_type="clarification", segments=[Segment(type="text", content=question)])


def compose(plan: Plan, ordered: list[tuple[int, AgentResult]], timed_out: bool = False) -> tuple[StructuredResponse, ErrorInfo | None]:
    """`ordered` is [(step_id, result)] in plan order across all iterations."""
    ok = [(i, r) for i, r in ordered if r.status == "success"]
    failed = [(i, r) for i, r in ordered if r.status == "error"]
    content = [(i, r) for i, r in ok if r.agent != "verifier_agent"]
    verifiers = [r for _, r in ok if r.agent == "verifier_agent"]

    if not content:
        first = failed[0][1].error if failed and failed[0][1].error else None
        msg = friendly_error(first)
        if timed_out:
            msg = _FRIENDLY["agent_timeout"]
        return StructuredResponse(response_type="error", segments=[Segment(type="error", content=msg)]), first

    # A summarizer that consumed earlier steps is the final answer on its own.
    last_id, last = content[-1]
    if last.agent == "summarizer_agent" and len(content) > 1:
        chosen = [last]
    else:
        chosen = [r for _, r in content]

    segs: list[Segment] = []
    for r in chosen:
        for s in r.segments:
            if segs and segs[-1] == s:
                continue
            segs.append(s)

    for v in verifiers:
        segs.extend(s for s in v.segments if s.type == "warning")
    for _, r in failed:
        segs.append(Segment(type="warning", content=f"One step didn't finish ({r.agent.replace('_', ' ')}): {friendly_error(r.error)}"))
    if timed_out:
        segs.append(Segment(type="warning", content="I ran out of time, so this may be incomplete."))

    if not segs:
        segs = [Segment(type="text", content="Done.")]
    return StructuredResponse(response_type=guess_kind(segs), segments=segs), (failed[0][1].error if failed else None)
