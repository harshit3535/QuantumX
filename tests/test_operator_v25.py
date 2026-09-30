import pytest
from app.input.normalizer import normalize
from app.memory.db import Database
from app.memory.context import ContextManager
from app.orchestrator.planner import Planner
from app.models import Plan


def test_operator_routes_public_url():
    req = normalize("check https://example.com", modality="text", mode="personal", language_hint="en", output_pref="text")
    plan = __import__('app.orchestrator.planner', fromlist=['heuristic_plan']).heuristic_plan(req, ContextManager(Database("sqlite:///:memory:")).build("s", req))
    assert plan.steps and plan.steps[0].agent == "operator_agent"


def test_operator_asks_for_url():
    req = normalize("check my website", modality="voice", mode="hackathon", language_hint="en", output_pref="text")
    ctx = ContextManager(Database("sqlite:///:memory:")).build("s", req)
    plan = __import__('app.orchestrator.planner', fromlist=['heuristic_plan']).heuristic_plan(req, ctx)
    assert plan.needs_clarification is True
    assert "URL" in (plan.clarification_question or "")
