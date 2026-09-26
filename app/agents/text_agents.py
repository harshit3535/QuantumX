"""research / summarizer / verifier agents (all LLM-backed, all honest about limits)."""
from __future__ import annotations

from ..errors import LLMUnavailable
from ..llm.jsonutil import extract_json
from ..models import AgentResult, Segment
from ..response.parser import markdown_to_segments
from .base import AgentContext


async def research_agent(task: str, ctx: AgentContext) -> AgentResult:
    if not ctx.router.available():
        raise LLMUnavailable("No AI provider configured for research answers.")
    system = ("You are a research assistant. Answer from your own knowledge, clearly separating what you know well from what "
              "may have changed. You have NO live web access: never pretend to browse or cite sources you did not see. "
              "Structure the answer with short paragraphs or bullets. ") + ctx.language_rule() + ctx.voice_rule()
    prompt = f"Question: {task}"
    if ctx.dep_text():
        prompt += "\n\n" + ctx.dep_text()
    if ctx.feedback:
        prompt += "\n\nFix this problem with your previous answer: " + ctx.feedback
    text = await ctx.router.complete(system, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=1600)
    return AgentResult(agent="research_agent", status="success", segments=markdown_to_segments(text), data={"live_search": False, "provider": ctx.router.last_used})


async def summarizer_agent(task: str, ctx: AgentContext) -> AgentResult:
    if not ctx.router.available():
        raise LLMUnavailable("No AI provider configured for summaries.")
    material = ctx.dep_text() or ctx.request.text
    system = "You are a precise summarizer. Keep the key facts, drop the fluff. " + ctx.language_rule() + ctx.voice_rule()
    prompt = f"Task: {task}\n\nMaterial:\n{material}"
    text = await ctx.router.complete(system, [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=900)
    return AgentResult(agent="summarizer_agent", status="success", segments=markdown_to_segments(text), data={"provider": ctx.router.last_used})


async def verifier_agent(task: str, ctx: AgentContext) -> AgentResult:
    """Reviews earlier agent output. Skipped (not failed) when no LLM is available."""
    material = ctx.dep_text()
    if not material:
        return AgentResult(agent="verifier_agent", status="skipped", data={"reason": "nothing to verify"})
    if not ctx.router.available():
        return AgentResult(agent="verifier_agent", status="skipped", data={"reason": "no AI provider"})
    system = ('You review another agent\'s output for concrete, checkable problems (bugs, wrong maths, missing parts). '
              'Reply with JSON only: {"verdict":"PASS"|"FAIL","issues":["..."]}. Only FAIL for real problems.')
    prompt = f"Task that was requested: {task}\n\nOutput to review:\n{material}"
    raw = await ctx.router.complete(system, [{"role": "user", "content": prompt}], json_mode=True, temperature=0.0, max_tokens=500)
    try:
        obj = extract_json(raw)
        verdict = str(obj.get("verdict", "PASS")).upper()
        issues = [str(i) for i in obj.get("issues", [])][:5]
    except Exception:
        verdict, issues = "PASS", []
    segs: list[Segment] = []
    if verdict == "FAIL" and issues:
        segs.append(Segment(type="warning", content="Review found possible issues: " + "; ".join(issues)))
    return AgentResult(agent="verifier_agent", status="success", segments=segs, data={"verdict": verdict, "issues": issues})
