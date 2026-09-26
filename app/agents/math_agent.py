"""Math agent: SymPy first (exact, verified), LLM only for word problems."""
from __future__ import annotations

from ..errors import LLMUnavailable, NexusError
from ..models import AgentResult, Segment
from ..response.parser import markdown_to_segments
from ..tools.mathsolve import MathParseError, solve_math_isolated
from .base import AgentContext

SYSTEM = """You are a careful math tutor. Solve the problem step by step.
Formatting rules (important, the UI renders them):
- Put every equation on its own line inside $$ ... $$ using LaTeX.
- Use short sentences between equations.
- End with a line that states the final answer clearly.
- If you are not sure, say so."""


_LEAD = {
    "en": {"solve": "Solving it:", "diff": "Differentiating:", "integrate": "Integrating:", "percent": "Percentage:", "default": "Result:",
           "checked": "Checked by substituting the answer back into the equation."},
    "gu": {"solve": "ઉકેલ:", "diff": "વિકલન:", "integrate": "સંકલન:", "percent": "ટકાવારી:", "default": "પરિણામ:",
           "checked": "જવાબને સમીકરણમાં પાછો મૂકીને ચકાસ્યો છે."},
    "hi": {"solve": "हल:", "diff": "अवकलन:", "integrate": "समाकलन:", "percent": "प्रतिशत:", "default": "परिणाम:",
           "checked": "उत्तर को समीकरण में वापस रखकर जाँचा गया है।"},
}


async def math_agent(task: str, ctx: AgentContext) -> AgentResult:
    words = _LEAD.get(ctx.request.language, _LEAD["en"])
    # 1) deterministic path
    try:
        out = await solve_math_isolated(task)
        segs: list[Segment] = []
        segs.append(Segment(type="text", content=words.get(out.kind, words["default"])))
        for step in out.steps:
            segs.append(Segment(type="math", content=step, display=True))
        segs.append(Segment(type="math", content=out.latex, display=True))
        if out.verified is True and out.kind == "solve":
            segs.append(Segment(type="text", content=words["checked"]))
        return AgentResult(
            agent="math_agent", status="success", segments=segs,
            data={"engine": "sympy", "expression": out.expression, "result": out.result, "latex": out.latex, "verified": out.verified},
        )
    except MathParseError as exc:
        reason = str(exc)

    # 2) word problems / anything sympy can't parse -> LLM
    if not ctx.router.available():
        raise LLMUnavailable(f"I couldn't compute that directly ({reason}) and no AI provider is configured for word problems.")
    prompt = [f"Problem: {task}"]
    if ctx.context.referent and ctx.context.referent.get("type") == "math":
        prompt.append("Earlier result the user may refer to:\n" + ctx.context.referent.get("content", ""))
    if ctx.dep_text():
        prompt.append(ctx.dep_text())
    if ctx.feedback:
        prompt.append("Fix this problem with your previous answer: " + ctx.feedback)
    text = await ctx.router.complete(SYSTEM + "\n" + ctx.language_rule() + ctx.voice_rule(),
                                     [{"role": "user", "content": "\n\n".join(prompt)}], temperature=0.1, max_tokens=1600)
    segs = markdown_to_segments(text)
    if not segs:
        raise NexusError("The math agent returned nothing", kind="invalid_agent_output", layer="validation")
    return AgentResult(agent="math_agent", status="success", segments=segs, data={"engine": "llm", "verified": None, "provider": ctx.router.last_used})
