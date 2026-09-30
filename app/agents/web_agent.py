"""Live web search agent.

Uses DuckDuckGo's HTML endpoint (html.duckduckgo.com) - no API key, no quota.
This is what makes research_agent's "I have no live web access" caveat go away
for requests that clearly need current information.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ..errors import LLMUnavailable, NetworkError
from ..models import AgentResult, Segment
from .base import AgentContext

SEARCH_URL = "https://html.duckduckgo.com/html/"
MAX_RESULTS = 5
FETCH_TIMEOUT = 8.0

_RESULT = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'(?:<a[^>]*class="result__snippet"[^>]*>(.*?)</a>|<td class="result__snippet"[^>]*>(.*?)</td>)',
    re.S,
)
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAG.sub("", s or "")).strip()


def _resolve_url(href: str) -> str:
    """DuckDuckGo's HTML result links are redirects like /l/?uddg=<encoded-url>."""
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        q = parse_qs(urlparse(href).query)
        target = q.get("uddg")
        if target:
            return unquote(target[0])
    return href


async def search_web(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, str]]:
    query = query.strip()
    if not query:
        return []
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(
                SEARCH_URL, data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; AstraAgent/1.0)"},
            )
    except httpx.HTTPError as exc:
        raise NetworkError(f"Web search failed ({type(exc).__name__})") from exc
    if r.status_code >= 400:
        raise NetworkError(f"Web search returned HTTP {r.status_code}")

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _RESULT.finditer(r.text):
        href, title_html, snippet1, snippet2 = m.groups()
        url = _resolve_url(href)
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append({"title": _clean(title_html), "url": url, "snippet": _clean(snippet1 or snippet2 or "")})
        if len(out) >= max_results:
            break
    return out


SYSTEM = """You are a research assistant with FRESH web search results attached below.
Answer the user's question using ONLY the information in the results (plus your own general
knowledge to explain background context). Rules:
- Do not invent facts, numbers or dates that are not in the results.
- Prefer the most recent-looking results when they disagree.
- After the answer, list the sources as a short list: "Source: <title> (<url>)" - one per fact used.
- If the results don't actually answer the question, say so plainly."""


def _format_results(results: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{i+1}. {r['title']}\n{r['snippet']}\nURL: {r['url']}" for i, r in enumerate(results))


async def web_agent(task: str, ctx: AgentContext) -> AgentResult:
    try:
        results = await search_web(task)
    except NetworkError:
        results = []

    if not results:
        if not ctx.router.available():
            raise LLMUnavailable("Web search returned nothing and no AI provider is configured to answer from general knowledge.")
        text = await ctx.router.complete(
            "You have no live web access right now (search failed). Answer from general knowledge and say clearly that this is not "
            "from a live search. " + ctx.language_rule() + ctx.voice_rule(),
            [{"role": "user", "content": task}], temperature=0.3, max_tokens=900,
        )
        from ..response.parser import markdown_to_segments
        return AgentResult(agent="web_agent", status="success", segments=markdown_to_segments(text), data={"live_search": False, "results": 0})

    if not ctx.router.available():
        segs = [Segment(type="text", content=f"Top results for \"{task}\":")]
        segs.append(Segment(type="list", items=[f"{r['title']} — {r['snippet'][:140]} ({r['url']})" for r in results]))
        return AgentResult(agent="web_agent", status="success", segments=segs, data={"live_search": True, "results": len(results)})

    prompt = f"Question: {task}\n\nSearch results:\n{_format_results(results)}"
    text = await ctx.router.complete(SYSTEM + "\n" + ctx.language_rule() + ctx.voice_rule(), [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1400)
    from ..response.parser import markdown_to_segments
    segs = markdown_to_segments(text)
    return AgentResult(agent="web_agent", status="success", segments=segs, data={"live_search": True, "results": len(results), "provider": ctx.router.last_used})
