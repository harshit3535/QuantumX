"""Code agent. Code is a first-class output: language, filename and indentation survive."""
from __future__ import annotations

from ..errors import InvalidAgentOutput
from ..models import AgentResult
from ..response.parser import markdown_to_segments
from .base import AgentContext

SYSTEM = """You are Astra's builder agent. Your job is to DO the coding work, not to describe how the user could do it.
Output contract:
1. Start with one short completion sentence.
2. Return EVERY essential requested file in its own fenced block, with language AND exact filename on the opening fence, e.g. ```html index.html
3. Do not replace code with pseudocode, snippets, placeholders, ellipses, or instructions such as 'save this as...'.
4. After the complete files, at most two short notes about validation/run steps.
Rules:
- Preserve the user's original intent and requested features. Never silently simplify the task to a summary.
- When the task implies a multi-file project, create all files needed for it to run. For a plain frontend request, prefer complete index.html + styles.css + script.js when JavaScript is useful.
- If modifying earlier code, return the full updated affected files, not a diff-only snippet.
- Keep indentation and syntax exact. Keep dependencies minimal unless requested.
- The result is not complete until the requested work product exists in full.
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
