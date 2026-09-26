import asyncio
import json

from app.errors import LLMRateLimited
from app.models import ChatRequest


def chat(nx, sid, msg, **kw):
    return asyncio.run(nx.chat(ChatRequest(session_id=sid, message=msg, **kw)))


# ------------------------------------------------------- unknown != error
def test_unknown_casual_input_is_not_an_error_offline(offline):
    r = chat(offline, "s1", "mare ghare javu che")
    assert r.error is None
    assert r.response.response_type == "text"
    assert r.plan.kind == "conversation"
    assert r.output.speak is False                    # personal + text in -> text out
    assert "ઘરે" in r.response.plain_text()          # answered in Gujarati, not "error"


def test_greeting_offline(offline):
    r = chat(offline, "s1", "hello")
    assert r.error is None and "Astra" in r.response.plain_text()


def test_needing_llm_offline_is_a_real_error_with_layer(offline):
    r = chat(offline, "s1", "Create a Python calculator")
    assert r.response.response_type == "error"
    assert r.error and r.error.kind == "llm_unavailable" and r.error.layer == "llm"


def test_incomplete_input_asks_for_clarification(offline):
    r = chat(offline, "s1", "I want to build a website and")
    assert r.response.response_type == "clarification" and r.trace == []


def test_unresolved_reference_asks_for_clarification(offline):
    r = chat(offline, "fresh", "Add login to it")
    assert r.response.response_type == "clarification"


# ------------------------------------------------------------ math / speech
def test_math_needs_no_llm_and_speaks_words(offline):
    r = chat(offline, "s1", "solve x^2 - 5x + 6 = 0", source="voice", mode="hackathon")
    kinds = r.response.kinds()
    assert "math" in kinds and r.error is None
    assert r.output.speak is True
    assert "x equals two" in r.output.speech_text and "\\" not in r.output.speech_text
    assert r.plan.source == "heuristic" and len(r.trace) == 1


# ------------------------------------------------------------------- code
CODE_REPLY = "Here is the calculator.\n\n```python calculator.py\ndef add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n```\n\nRun it with python."


def test_code_is_structured_and_not_read_raw(make_llm):
    nx, prov = make_llm(lambda s, m, j: CODE_REPLY)
    r = chat(nx, "s1", "Create a Python calculator", source="voice", mode="personal")
    code = [s for s in r.response.segments if s.type == "code"][0]
    assert code.language == "python" and code.filename == "calculator.py" and "    return a + b" in code.content
    assert r.output.speak and "def " not in r.output.speech_text and "on screen" in r.output.speech_text
    assert len(prov.calls) == 1                      # cheap path: no planner call for a simple request


def test_text_in_personal_mode_is_display_only(make_llm):
    nx, _ = make_llm(lambda s, m, j: CODE_REPLY)
    r = chat(nx, "s1", "Create a Python calculator", source="text", mode="personal")
    assert r.output.speak is False and r.output.display is True


def test_hackathon_is_voice_first_even_for_text(make_llm):
    nx, _ = make_llm(lambda s, m, j: "Paris is the capital of France.")
    r = chat(nx, "s1", "What is the capital of France?", source="text", mode="hackathon")
    assert r.output.speak is True and "Paris" in r.output.speech_text


def test_validation_retry_fixes_broken_code(make_llm):
    replies = iter([
        "```python a.py\ndef f(:\n    pass\n```",
        "```python a.py\ndef f():\n    return 1\n```",
    ])
    nx, prov = make_llm(lambda s, m, j: next(replies))
    r = chat(nx, "s1", "Write a python function f")
    assert r.trace[0].attempts == 2 and r.trace[0].issues
    assert "def f():" in [s for s in r.response.segments if s.type == "code"][0].content
    assert "syntax error" in prov.calls[1]["messages"][0]["content"].lower()   # feedback reached the agent


def test_retry_gives_up_honestly(make_llm):
    nx, prov = make_llm(lambda s, m, j: "```python a.py\ndef f(:\n```")
    r = chat(nx, "s1", "Write a python function f")
    assert len(prov.calls) == 2                       # 1 try + max_step_retries(1), never infinite
    assert any(s.type == "warning" for s in r.response.segments)


# --------------------------------------------------- history & references
def test_follow_up_uses_previous_code(make_llm):
    def script(system, messages, json_mode):
        prompt = messages[-1]["content"]
        if "Existing code to modify" in prompt:
            return "```python calculator.py\ndef add(a, b):\n    return a + b\n\ndef div(a, b):\n    return a / b\n```"
        return "```python calculator.py\ndef add(a, b):\n    return a + b\n```"
    nx, prov = make_llm(script)
    chat(nx, "s1", "Create a Python calculator")
    r = chat(nx, "s1", "Add division to it")
    last_prompt = prov.calls[-1]["messages"][-1]["content"]
    assert "Existing code to modify" in last_prompt and "def add" in last_prompt
    assert "def div" in [s for s in r.response.segments if s.type == "code"][0].content


def test_implicit_followup_without_pronoun(make_llm):
    nx, prov = make_llm(lambda s, m, j: "```html page.html\n<button>Hi</button>\n```")
    chat(nx, "s1", "Create an HTML page with a button")
    chat(nx, "s1", "Make the button blue.")
    assert "Existing code to modify" in prov.calls[-1]["messages"][-1]["content"]


def test_read_code_aloud_uses_previous_code(make_llm):
    nx, prov = make_llm(lambda s, m, j: "```python a.py\ndef add(a, b):\n    return a + b\n```")
    chat(nx, "s1", "Create a Python function add")
    n = len(prov.calls)
    r = chat(nx, "s1", "read the code aloud", source="voice")
    assert len(prov.calls) == n                       # no LLM needed
    assert r.output.read_code_aloud and "open parenthesis" in r.output.speech_text


def test_history_persists_structured_response(make_llm, db):
    nx, _ = make_llm(lambda s, m, j: CODE_REPLY)
    chat(nx, "s1", "Create a Python calculator")
    msgs = db.history("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["metadata"]["response"]["segments"][1]["type"] == "code"


# ------------------------------------------------------- planner (LLM path)
def test_complex_request_uses_llm_planner_and_dependencies(make_llm):
    plan = {"kind": "task", "goal": "research then summarize", "confidence": 0.9, "may_need_followup": False,
            "steps": [{"id": 1, "agent": "research_agent", "task": "Research solar power", "depends_on": []},
                      {"id": 2, "agent": "summarizer_agent", "task": "Summarize it", "depends_on": [1]}],
            "needs_clarification": False}

    def script(system, messages, json_mode):
        if "planner" in system:
            return json.dumps(plan)
        if "summarizer" in system:
            return "Solar turns sunlight into power."
        return "Long research text about solar power."
    nx, prov = make_llm(script)
    r = chat(nx, "s1", "Research solar power and then summarize it for me")
    assert r.plan.source == "llm"
    assert [t.agent for t in r.trace] == ["research_agent", "summarizer_agent"]
    assert r.response.plain_text() == "Solar turns sunlight into power."   # summarizer output only


def test_broken_llm_plan_falls_back_to_heuristic(make_llm):
    def script(system, messages, json_mode):
        if "planner" in system:
            return "this is not json"
        return "Some answer."
    nx, _ = make_llm(script)
    r = chat(nx, "s1", "Research solar power and then summarize it for me")
    assert r.plan.source == "heuristic" and r.error is None


def test_unknown_agents_in_plan_are_dropped(make_llm):
    plan = {"kind": "task", "goal": "g", "steps": [{"id": 1, "agent": "hacker_agent", "task": "x"}, {"id": 2, "agent": "general_agent", "task": "hi"}]}
    def script(system, messages, json_mode):
        return json.dumps(plan) if "planner" in system else "ok"
    nx, _ = make_llm(script)
    r = chat(nx, "s1", "Research solar power and then summarize it for me")
    assert [s.agent for s in r.plan.steps] == ["general_agent"]


# --------------------------------------------------------- failure handling
def test_provider_fallback_on_rate_limit(db):
    from app.llm.router import LLMRouter
    from app.pipeline import Nexus
    from conftest import FakeProvider
    bad = FakeProvider(lambda s, m, j: LLMRateLimited("gemini: rate limit reached"))
    bad.name = "gemini"
    good = FakeProvider(lambda s, m, j: "Hi from the backup provider")
    good.name = "groq"
    nx = Nexus(db, LLMRouter(providers=[bad, good]))
    r = chat(nx, "s1", "Explain photosynthesis")
    assert "backup" in r.response.plain_text() and nx.router.last_used == "groq"
    chat(nx, "s1", "Explain gravity")
    assert len(bad.calls) == 1                        # cooldown: not hammered again right away


def test_all_providers_down_is_reported_not_crashed(make_llm):
    nx, _ = make_llm(lambda s, m, j: LLMRateLimited("rate limit"))
    r = chat(nx, "s1", "Explain photosynthesis")
    assert r.response.response_type == "error" and r.error.kind == "llm_unavailable"
