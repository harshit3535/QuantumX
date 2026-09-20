from __future__ import annotations

from core.models import InputEnvelope
from core.normalizer import InputNormalizer
from core.response import ResponseParser
from core.orchestrator import AgentOrchestrator
from core.history import HistoryManager
from llm.mock import MockLLM


def test_text_normalization():
    result = InputNormalizer().normalize(InputEnvelope("  hello   world  ", "personal", "text", "text"))
    assert result.envelope.text == "hello world"
    assert not result.needs_clarification


def test_code_detection():
    result = InputNormalizer().normalize(InputEnvelope("write Python code", "personal", "text", "text"))
    assert "code" in result.content_types


def test_math_parser():
    response = ResponseParser().parse("Result:\n\n```python\nprint(2+2)\n```")
    assert any(seg.type == "code" for seg in response.segments)


def test_mock_orchestrator():
    history = HistoryManager(path=__import__("pathlib").Path("/tmp/aob_test_history.json"), max_turns=5)
    history.clear()
    aob = AgentOrchestrator(MockLLM(), history)
    response = aob.handle(InputEnvelope("create a Python calculator", "personal", "text", "text"))
    assert response.segments
    assert any(seg.type == "code" for seg in response.segments)
