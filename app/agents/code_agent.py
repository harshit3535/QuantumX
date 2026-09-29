"""Code agent. Code is a first-class output: language, filename and indentation survive."""
from __future__ import annotations

from ..errors import InvalidAgentOutput
from ..models import AgentResult
from ..response.parser import markdown_to_segments
from .base import AgentContext

SYSTEM = """You are a senior software engineer.
Output format (the UI depends on it):
1. One short sentence saying what you built.
2. Every file in its own fenced block, with the language AND file name on the opening fence, e.g. ```python calculator.py
3. Then 2-4 short sentences of explanation (how to run it, key design choice).
Rules:
- Return COMPLETE, runnable code - never fragments or "..." placeholders.
- If the user is modifying earlier code, return the full updated file, keeping unchanged parts intact.
- Keep indentation exact. Use one language unless asked otherwise.
- Do not write malware or anything harmful."""


async def code_agent(task: str, ctx: AgentContext) -> AgentResult:
    parts = [f"Request: {task}"]
    ref = ctx.context.referent
    if ref and ref.get("type") == "code":
        parts.append(
            f"Existing code to modify ({ref.get('language') or 'code'}"
            f"{', ' + ref['filename'] if ref.get('filename') else ''}):\n```{ref.get('language') or ''}\n{ref.get('content','')}\n```"
        )
    elif ctx.context.render(1500) and ctx.request.has_reference:
        parts.append(ctx.context.render(2500))
    dep = ctx.dep_text()
    if dep:
        parts.append("Use this input from earlier steps:\n" + dep)
    if ctx.feedback:
        parts.append("Your previous attempt was rejected. Fix exactly this and return the complete code again: " + ctx.feedback)

    text = await ctx.router.complete(SYSTEM + "\n" + ctx.language_rule(), [{"role": "user", "content": "\n\n".join(parts)}],
                                     temperature=0.2, max_tokens=3500, timeout=40)
    segs = markdown_to_segments(text)
    if not any(s.type == "code" and s.content.strip() for s in segs):
        raise InvalidAgentOutput("The code agent replied without any code block")
    langs = sorted({s.language for s in segs if s.type == "code" and s.language})
    names = [s.filename for s in segs if s.type == "code" and s.filename]
    return AgentResult(agent="code_agent", status="success", segments=segs,
                       data={"languages": langs, "filenames": names, "provider": ctx.router.last_used})
