"""Read-only operator agent: perform real public diagnostics instead of inventing tool output."""
from __future__ import annotations

import re

from ..errors import NetworkError
from ..models import AgentResult, Segment
from ..response.parser import markdown_to_segments
from ..tools.operator import check_url, run_public_search
from .base import AgentContext

_URL = re.compile(r"https?://[^\s<>()\[\]{}]+", re.I)
_DOMAIN = re.compile(r"\b(?:www\.)?[a-z0-9-]+\.(?:com|net|org|io|ai|dev|app|co|in)(?:/[^\s<>()]*)?\b", re.I)


def _url_from(task: str) -> str | None:
    m = _URL.search(task)
    if m:
        return m.group(0).rstrip(".,!?;:")
    m = _DOMAIN.search(task)
    return m.group(0).rstrip(".,!?;:") if m else None


async def operator_agent(task: str, ctx: AgentContext) -> AgentResult:
    target = _url_from(task)
    lower = task.lower()
    is_diagnostic = any(k in lower for k in (
        "website", "web site", "site", "url", "server", "endpoint", "http", "https", "down", "offline", "reachable", "health check", "status check"
    ))

    if is_diagnostic and not target:
        # Planner normally catches this, but keep the agent truthful if called directly.
        return AgentResult(agent="operator_agent", status="success", segments=[Segment(
            type="warning", content="I need the public website URL before I can run a real health check."
        )], data={"tool": "check_url", "needs_input": "url"})

    try:
        if target:
            result = await check_url(target)
            code = result["status_code"]
            state = "healthy" if 200 <= code < 400 else "reachable but unhealthy"
            title = f" Page title: {result['title']}." if result.get("title") else ""
            text = (
                f"The site is {state}. HTTP {code}, {result['latency_ms']} ms from the diagnostic client, "
                f"and the final URL is {result['final_url']}.{title}"
            )
            return AgentResult(
                agent="operator_agent", status="success", segments=markdown_to_segments(text),
                data={"tool": "check_url", **result},
            )

        result = await run_public_search(task)
        rows = result.get("results", [])
        segs = [Segment(type="text", content=f"I ran a live web search and found {len(rows)} public results for: {task}")]
        if rows:
            segs.append(Segment(type="list", items=[f"{r['title']} — {r['snippet'][:180]} ({r['url']})" for r in rows]))
        return AgentResult(agent="operator_agent", status="success", segments=segs, data={"tool": "web_search", **result})
    except (NetworkError, ValueError) as exc:
        raise NetworkError(str(exc)) from exc
