import asyncio
from app.models import NormalizedRequest, ContextBundle
from app.orchestrator.planner import Planner
from app.llm.router import LLMRouter

def run(req):
    return asyncio.run(Planner(LLMRouter()).plan(req, ContextBundle()))

def test_floorops_workspace_routes_directly():
    req=NormalizedRequest(original_text="check SKU-104 stock",text="check SKU-104 stock",language="en",workspace="floorops",intent_hint="task")
    plan=run(req)
    assert plan.steps[0].agent=="floorops_agent" and plan.team=="FloorOps"

def test_receptionist_workspace_stays_receptionist():
    req=NormalizedRequest(original_text="hello",text="hello",language="en",workspace="receptionist",intent_hint="conversation")
    plan=run(req)
    assert plan.steps[0].agent=="receptionist_agent" and plan.team=="Front Desk"
