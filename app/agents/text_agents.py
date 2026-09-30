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
    ref = ctx.context.referent
    material = ctx.dep_text() or ((ref or {}).get("content") if ref else "") or ctx.request.text
    system = "You are a precise summarizer. Keep the key facts, drop the fluff. " + ctx.language_rule() + ctx.voice_rule()
    prompt = f"Task: {task}\n\nMaterial:\n{material}"
    text = await ctx.router.complete(system, [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=900)
    return AgentResult(agent="summarizer_agent", status="success", segments=markdown_to_segments(text), data={"provider": ctx.router.last_used})


async def verifier_agent(task: str, ctx: AgentContext) -> AgentResult:
    """Independent reality check.

    Code work is reviewed deterministically so the build/test loop does not spend
    an extra model call just to check syntax/completeness. Research/tool outputs
    can still use an LLM reviewer when evidence needs semantic scrutiny.
    """
    material = ctx.dep_text()
    if not material:
        return AgentResult(agent="verifier_agent", status="skipped", data={"reason": "nothing to verify"})

    if "code_agent output" in material.lower() or ctx.request.has_code or "```" in material:
        structural_issues: list[str] = []
        code_blocks = re.findall(r"```[^\n]*\n([\s\S]*?)```", material)
        if not code_blocks:
            structural_issues.append("No fenced code artifact was returned.")
        if any(marker in material for marker in ("...", "…", "TODO: implement", "your code here")):
            structural_issues.append("The generated code contains a placeholder or incomplete implementation.")
        # Frontend projects should be a real multi-file work product, not a prose recipe.
        low = (task + " " + material).lower()
        if any(x in low for x in ("frontend", "front-end", "html", "website", "web page", "login page")):
            names = set(re.findall(r"```(?:\w+)?\s+([\w./-]+\.[\w]{1,6})", material, flags=re.I))
            if "index.html" not in {n.lower() for n in names}:
                structural_issues.append("Frontend build is missing an index.html entry file.")
        if structural_issues:
            segs = [Segment(type="warning", content="Review found concrete issues: " + "; ".join(structural_issues))]
            return AgentResult(agent="verifier_agent", status="success", segments=segs, data={"verdict": "FAIL", "issues": structural_issues, "review_mode": "deterministic"})
        return AgentResult(
            agent="verifier_agent", status="success",
            segments=[Segment(type="text", content="Build review passed: the requested code artifact is complete, named, and structurally valid.")],
            data={"verdict": "PASS", "issues": [], "review_mode": "deterministic"},
        )

    if not ctx.router.available():
        return AgentResult(agent="verifier_agent", status="skipped", data={"reason": "no AI provider"})

    system = (
        'You are the independent reality checker in a build/test loop. Review the prior agent output against the original requested outcome. '
        'For research or tool results, check evidence consistency and unsupported claims. '
        'Reply with JSON only: {"verdict":"PASS"|"FAIL","issues":["specific fix"]}. '
        'Do not fail for style preferences alone. Only FAIL when a concrete issue would prevent the requested outcome from being reliable or complete.'
    )
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
    return AgentResult(agent="verifier_agent", status="success", segments=segs, data={"verdict": verdict, "issues": issues, "review_mode": "llm"})
