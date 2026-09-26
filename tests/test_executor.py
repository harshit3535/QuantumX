import asyncio
import time

from app.agents import registry
from app.agents.base import AgentSpec
from app.errors import AgentError
from app.input.normalizer import normalize
from app.llm.router import LLMRouter
from app.models import AgentResult, ContextBundle, PlanStep, Segment
from app.orchestrator.executor import Budget, run_steps

ORDER: list[str] = []


def _agent(name, delay=0.0, fail=False, text="ok"):
    async def handler(task, ctx):
        ORDER.append(f"start:{name}")
        await asyncio.sleep(delay)
        if fail:
            raise AgentError("boom")
        ORDER.append(f"end:{name}")
        return AgentResult(agent=name, status="success", segments=[Segment(type="text", content=text)])
    return AgentSpec(name, name, handler, needs_llm=False)


def run(steps):
    ORDER.clear()
    results: dict = {}
    req = normalize("x")
    traces = asyncio.run(run_steps(steps, req, ContextBundle(), LLMRouter(providers=[]), results, Budget(), 1))
    return results, traces


def test_independent_steps_run_in_parallel_dependents_wait(monkeypatch):
    monkeypatch.setitem(registry.AGENTS, "a", _agent("a", 0.2))
    monkeypatch.setitem(registry.AGENTS, "b", _agent("b", 0.2))
    monkeypatch.setitem(registry.AGENTS, "c", _agent("c", 0.0))
    t0 = time.monotonic()
    results, _ = run([PlanStep(id=1, agent="a", task="t"), PlanStep(id=2, agent="b", task="t"), PlanStep(id=3, agent="c", task="t", depends_on=[1, 2])])
    assert time.monotonic() - t0 < 0.38               # a and b overlapped
    assert ORDER.index("start:c") > ORDER.index("end:a") and ORDER.index("start:c") > ORDER.index("end:b")
    assert set(results) == {1, 2, 3}


def test_one_failure_does_not_crash_others_and_blocks_only_dependents(monkeypatch):
    monkeypatch.setitem(registry.AGENTS, "good", _agent("good"))
    monkeypatch.setitem(registry.AGENTS, "bad", _agent("bad", fail=True))
    monkeypatch.setitem(registry.AGENTS, "after_bad", _agent("after_bad"))
    results, traces = run([PlanStep(id=1, agent="good", task="t"), PlanStep(id=2, agent="bad", task="t"), PlanStep(id=3, agent="after_bad", task="t", depends_on=[2])])
    assert results[1].status == "success"
    assert results[2].status == "error" and results[2].error.layer == "agent"
    assert results[3].status == "skipped"
    assert "start:after_bad" not in ORDER


def test_call_budget_stops_runaway(monkeypatch):
    monkeypatch.setitem(registry.AGENTS, "a", _agent("a"))
    results: dict = {}
    b = Budget(max_calls=2)
    steps = [PlanStep(id=i, agent="a", task="t") for i in range(1, 5)]
    asyncio.run(run_steps(steps, normalize("x"), ContextBundle(), LLMRouter(providers=[]), results, b, 1))
    assert sum(1 for r in results.values() if r.status == "success") == 2
    assert any(r.error and r.error.kind == "budget_exhausted" for r in results.values())
