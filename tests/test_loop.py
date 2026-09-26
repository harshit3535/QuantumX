import asyncio
import json

from app.config import settings
from app.models import ChatRequest


def chat(nx, msg, sid="s1", **kw):
    return asyncio.run(nx.chat(ChatRequest(session_id=sid, message=msg, **kw)))


def _script(planner_reply, checker_reply):
    def script(system, messages, json_mode):
        if "planner of a multi-agent" in system:
            return json.dumps(planner_reply)
        if "check whether a goal" in system:
            return json.dumps(checker_reply)
        return "answer"
    return script


PLAN = {"kind": "task", "goal": "g", "may_need_followup": True,
        "steps": [{"id": 1, "agent": "research_agent", "task": "Research X", "depends_on": []},
                  {"id": 2, "agent": "summarizer_agent", "task": "Summarize", "depends_on": [1]}]}
NEVER_DONE = {"done": False, "reason": "not yet", "next_steps": [{"agent": "general_agent", "task": "more", "depends_on": []}]}


def test_loop_continues_until_goal_done(make_llm):
    answers = iter([NEVER_DONE, {"done": True, "reason": "ok", "next_steps": []}])
    def script(system, messages, json_mode):
        if "planner of a multi-agent" in system:
            return json.dumps(PLAN)
        if "check whether a goal" in system:
            return json.dumps(next(answers))
        return "answer"
    nx, _ = make_llm(script)
    r = chat(nx, "Research solar power and then summarize it for me")
    assert r.iterations == 2 and len(r.trace) == 3


def test_loop_can_never_run_forever(make_llm, monkeypatch):
    monkeypatch.setattr(settings, "max_iterations", 3)
    monkeypatch.setattr(settings, "max_agent_calls", 8)
    nx, prov = make_llm(_script(PLAN, NEVER_DONE))
    r = chat(nx, "Research solar power and then summarize it for me")
    assert r.iterations == 3                           # hard cap
    assert len(prov.calls) < 12
    assert r.response.plain_text()                     # still returns the best answer so far


def test_goal_check_off_by_default_when_all_ok(make_llm):
    plan = dict(PLAN, may_need_followup=False)
    nx, prov = make_llm(_script(plan, NEVER_DONE))
    r = chat(nx, "Research solar power and then summarize it for me")
    assert r.iterations == 1
    assert not any("check whether a goal" in c["system"] for c in prov.calls)   # saved an API call
