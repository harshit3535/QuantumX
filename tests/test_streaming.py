import asyncio
import json

from app.models import ChatRequest
from app.pipeline import Nexus


def test_emit_receives_plan_and_step_events_offline(offline):
    events = []

    async def emit(e):
        events.append(e)

    async def go():
        return await offline.chat(ChatRequest(session_id="s1", message="solve x^2 - 5x + 6 = 0"), emit=emit)

    r = asyncio.run(go())
    types = [e["type"] for e in events]
    assert types == ["plan", "step_start", "step_end", "compose"]
    assert events[0]["steps"][0]["agent"] == "math_agent"
    assert events[1]["agent"] == "math_agent" and events[2]["status"] == "success"
    assert r.error is None


def test_emit_never_breaks_the_request_if_it_raises(offline):
    async def bad_emit(e):
        raise RuntimeError("ui socket closed")

    async def go():
        return await offline.chat(ChatRequest(session_id="s1", message="hello"), emit=bad_emit)

    r = asyncio.run(go())
    assert r.error is None and "Astra" in r.response.plain_text()


def test_no_emit_for_clarification_or_direct_answer(offline):
    events = []

    async def emit(e):
        events.append(e)

    async def go():
        return await offline.chat(ChatRequest(session_id="s1", message="I want to build a website and"), emit=emit)

    asyncio.run(go())
    assert [e["type"] for e in events] == ["plan"]     # no steps run for a clarification


def test_stream_endpoint_yields_progress_then_final(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    import importlib
    import app.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    with client.stream("POST", "/api/chat/stream", json={"session_id": "sx", "message": "solve 2x + 4 = 10"}) as r:
        assert r.status_code == 200
        lines = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
    types = [e["type"] for e in lines]
    assert types[0] == "plan" and types[-1] == "final"
    assert "step_start" in types and "step_end" in types
    final = lines[-1]["data"]
    assert final["response"]["segments"][1]["type"] == "math"
