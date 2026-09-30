from app.models import NormalizedRequest, ContextBundle, Plan, PlanStep
from app.orchestrator.task_director import assign_team, team_catalog

def req(text="Create a frontend login page"):
    return NormalizedRequest(original_text=text,text=text,language="en",intent_hint="task",is_command=True)

def test_code_task_gets_build_review_team():
    p=Plan(kind="task",goal="Create a frontend login page",steps=[PlanStep(id=1,agent="code_agent",task="Create it")])
    out=assign_team(req(), ContextBundle(), p)
    assert out.team == "Build & Review"
    assert [s.agent for s in out.steps] == ["code_agent","verifier_agent"]
    assert out.assignments[0]["role"] == "builder"
    assert out.assignments[1]["role"] == "reviewer"
    assert out.success_criteria

def test_team_catalog_has_agency_style_presets():
    ids={x["id"] for x in team_catalog()}
    assert {"build-and-review","research-and-verify","front-desk"}.issubset(ids)


def test_common_create_typo_still_routes_to_code_agent():
    from app.orchestrator.planner import heuristic_plan
    r = req("creat a login page frontend perfectly")
    p = heuristic_plan(r, ContextBundle())
    assert p.steps and p.steps[0].agent == "code_agent"

