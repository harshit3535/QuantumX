import asyncio
from app.memory.db import Database
from app.models import ContextBundle
from app.agents.base import AgentContext
from app.agents.receptionist_agent import receptionist_agent
from app.input.normalizer import normalize
from app.orchestrator.planner import heuristic_plan
from app.llm.router import LLMRouter

def ctx(db, text, state=None):
    req=normalize(text, modality="text", mode="personal", language_hint="en", output_pref="text")
    c=ContextBundle(session_id="s1", task_state=state or {}, db=db)
    return AgentContext(request=req, context=c, router=LLMRouter(providers=[]), db=db)

def test_receptionist_route():
    req=normalize("book an appointment tomorrow", modality="text", mode="personal", language_hint="en", output_pref="text")
    p=heuristic_plan(req, ContextBundle())
    assert p.mission_type=="receptionist" and p.steps[0].agent=="receptionist_agent"

def test_receptionist_clarifies_one_missing_detail(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'r.db'}")
    r=asyncio.run(receptionist_agent("book an appointment tomorrow at 3 pm",ctx(db,"book an appointment tomorrow at 3 pm")))
    assert r.data["needs_input"]=="customer_name" and "name" in r.text.lower()

def test_receptionist_requires_confirmation(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'r.db'}")
    r=asyncio.run(receptionist_agent("book an appointment tomorrow at 3 pm. my name is Harshit",ctx(db,"book an appointment tomorrow at 3 pm. my name is Harshit")))
    assert r.data["approval_required"] and db.find_booking(session_id="s1") is None

def test_receptionist_confirmation_writes(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'r.db'}")
    first=asyncio.run(receptionist_agent("book an appointment tomorrow at 3 pm. my name is Harshit",ctx(db,"book an appointment tomorrow at 3 pm. my name is Harshit")))
    second=asyncio.run(receptionist_agent("yes confirm it",ctx(db,"yes confirm it",{"pending_action":first.data["pending_action"]})))
    assert second.data["outcome"]=="appointment_scheduled"
    assert db.find_booking(session_id="s1") is not None

def test_mission_event_roundtrip(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'e.db'}");db.create_session("Mission","s1");db.add_mission_event("s1","input",{"x":1},"Input")
    e=db.mission_events("s1");assert len(e)==1 and e[0]["payload"]["x"]==1


def test_bare_followup_keeps_receptionist_context():
    from app.models import ContextBundle, NormalizedRequest
    from app.orchestrator.planner import heuristic_plan
    ctx = ContextBundle(session_id="s1", task_state={"draft_booking": {"date": "2099-01-03", "time": "15:00"}})
    req = NormalizedRequest(original_text="Harshit", text="Harshit", language="en", intent_hint="statement")
    plan = heuristic_plan(req, ctx)
    assert plan.mission_type == "receptionist"
    assert plan.steps[0].agent == "receptionist_agent"


def test_operator_result_gets_evidence(db):
    from app.response.composer import compose
    from app.models import AgentResult, Plan, PlanStep, Segment
    plan = Plan(kind="task", goal="Check site", steps=[PlanStep(id=1, agent="operator_agent", task="check")], mission_type="diagnostic")
    r = AgentResult(agent="operator_agent", segments=[Segment(type="text", content="HTTP 200")], data={"tool":"check_url","status_code":200,"latency_ms":123,"final_url":"https://example.com"})
    resp, err = compose(plan, [(1,r)])
    assert err is None
    assert len(resp.meta["evidence"]) >= 2
