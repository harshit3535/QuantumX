import asyncio

import httpx
import pytest

from app.agents.web_agent import search_web, _resolve_url

SAMPLE_HTML = '''
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FPython">Python (programming language)</a>
  <a class="result__snippet">Python is a <b>high-level</b> programming language.</a>
</div>
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="https://python.org/">Welcome to Python.org</a>
  <a class="result__snippet">The official home of the Python programming language.</a>
</div>
'''


def _fake_client(html_body, status=200):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, data=None, headers=None):
            return httpx.Response(status, text=html_body, request=httpx.Request("POST", url))
    return C


def test_resolve_duckduckgo_redirect_url():
    assert _resolve_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage") == "https://example.com/page"
    assert _resolve_url("https://example.com/direct") == "https://example.com/direct"


def test_search_parses_results(monkeypatch):
    import app.agents.web_agent as wa
    monkeypatch.setattr(wa.httpx, "AsyncClient", _fake_client(SAMPLE_HTML))
    results = asyncio.run(search_web("python"))
    assert len(results) == 2
    assert results[0]["url"] == "https://en.wikipedia.org/wiki/Python"
    assert results[0]["title"] == "Python (programming language)"
    assert "high-level" in results[0]["snippet"]
    assert results[1]["url"] == "https://python.org/"


def test_search_empty_query_returns_empty(monkeypatch):
    assert asyncio.run(search_web("")) == []


def test_web_agent_answers_with_sources(make_llm, monkeypatch):
    import app.agents.web_agent as wa
    monkeypatch.setattr(wa.httpx, "AsyncClient", _fake_client(SAMPLE_HTML))

    def script(system, messages, json_mode):
        assert "Python (programming language)" in messages[-1]["content"]
        return "Python is a general-purpose language.\n\nSource: Python.org (https://python.org/)"
    nx, prov = make_llm(script)
    from app.models import ChatRequest
    r = asyncio.run(nx.chat(ChatRequest(session_id="s1", message="what is the latest news about python programming language")))
    assert r.error is None
    assert "python.org" in r.response.plain_text().lower()
    assert [t.agent for t in r.trace] == ["web_agent"]


def test_web_agent_falls_back_when_search_fails(make_llm, monkeypatch):
    import app.agents.web_agent as wa

    def bad_client(*a, **k):
        class C:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): raise httpx.ConnectError("down")
        return C()
    monkeypatch.setattr(wa.httpx, "AsyncClient", bad_client)
    nx, prov = make_llm(lambda s, m, j: "General knowledge answer (not live).")
    from app.models import ChatRequest
    r = asyncio.run(nx.chat(ChatRequest(session_id="s1", message="what is the current bitcoin price today")))
    assert r.error is None and "not live" in r.response.plain_text().lower()
