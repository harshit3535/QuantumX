"""Agent Orchestration Brain (AOB).

    understand -> plan -> execute (dependency-aware, parallel where possible)
              -> validate -> [goal check -> more steps]* -> compose

The AOB receives a NormalizedRequest + ContextBundle. It has no idea whether the
user typed or spoke, which STT/TTS is used, or what the UI looks like.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ..config import settings
from ..errors import ErrorInfo
from ..llm.router import LLMRouter
from ..models import AgentResult, ContextBundle, NormalizedRequest, Plan, PlanStep, Segment, StepTrace, StructuredResponse
from ..response.composer import clarification_response, compose
from .executor import Budget, run_steps
from .executor import Emit, _fire
from .planner import Planner

log = logging.getLogger("nexus.aob")


@dataclass
class AOBResult:
    plan: Plan
    trace: list[StepTrace]
    response: StructuredResponse
    iterations: int = 1
    error: ErrorInfo | None = None


@dataclass
class _State:
    results: dict[int, AgentResult] = field(default_factory=dict)
    trace: list[StepTrace] = field(default_factory=list)
    iterations: int = 0
    timed_out: bool = False


class Orchestrator:
    def __init__(self, router: LLMRouter):
        self.router = router
        self.planner = Planner(router)

    async def run(self, req: NormalizedRequest, ctx: ContextBundle, emit: "Emit | None" = None) -> AOBResult:
        plan = await self.planner.plan(req, ctx)
        await _fire(emit, {"type": "plan", "kind": plan.kind, "goal": plan.goal, "source": plan.source,
                           "steps": [{"id": s.id, "agent": s.agent, "depends_on": s.depends_on} for s in plan.steps]})

        # ---- not a job for agents ------------------------------------------------
        if plan.needs_clarification and plan.clarification_question:
            return AOBResult(plan, [], clarification_response(plan.clarification_question), 0)
        if plan.kind == "unsupported":
            text = plan.clarification_question or "I can't do that here, but I can help with questions, math, code and writing."
            return AOBResult(plan, [], StructuredResponse(response_type="text", segments=[Segment(type="text", content=text)]), 0)
        if plan.direct_action == "read_code_aloud" and ctx.referent:
            r = ctx.referent
            seg = Segment(type="code", content=r.get("content", ""), language=r.get("language"), filename=r.get("filename"))
            return AOBResult(plan, [], StructuredResponse(response_type="code", segments=[seg]), 0)

        # ---- execute --------------------------------------------------------------
        state = _State()
        try:
            await asyncio.wait_for(self._loop(req, ctx, plan, state, emit), timeout=settings.request_deadline)
        except asyncio.TimeoutError:
            state.timed_out = True
            log.warning("request deadline hit after %ss", settings.request_deadline)

        ordered = sorted(state.results.items())
        response, err = compose(plan, ordered, state.timed_out)
        await _fire(emit, {"type": "compose", "response_type": response.response_type})
        return AOBResult(plan, state.trace, response, max(state.iterations, 1), err)

    # ------------------------------------------------------------------------------
    async def _loop(self, req: NormalizedRequest, ctx: ContextBundle, plan: Plan, state: _State, emit: "Emit | None" = None) -> None:
        budget = Budget()
        pending: list[PlanStep] = list(plan.steps)

        while pending and state.iterations < settings.max_iterations:
            state.iterations += 1
            if state.iterations > 1:
                await _fire(emit, {"type": "iteration", "n": state.iterations})
            new_trace = await run_steps(pending, req, ctx, self.router, state.results, budget, state.iterations, emit)
            state.trace.extend(new_trace)
            pending = await self._goal_check(req, plan, state, new_trace, budget)

    async def _goal_check(self, req: NormalizedRequest, plan: Plan, state: _State, new_trace: list[StepTrace], budget: Budget) -> list[PlanStep]:
        """Returns extra steps to run, or [] when the goal is achieved (or we must stop)."""
        mode = settings.goal_check
        if mode == "never" or state.iterations >= settings.max_iterations or budget.calls >= budget.max_calls:
            return []
        # A model outage cannot be fixed by asking the model again; validation issues were already retried.
        problem = any(t.status == "error" and not (t.error and t.error.kind.startswith("llm_")) for t in new_trace)
        wanted = mode == "always" or problem or plan.may_need_followup
        if not wanted or not self.router.available():
            return []
        try:
            next_id = max(state.results) + 1
            done, steps, reason = await self.planner.next_steps(req, plan, state.results, next_id)
        except Exception as exc:
            log.warning("goal check failed: %s", exc)
            return []
        log.info("goal check: done=%s reason=%s extra=%d", done, reason, len(steps))
        return [] if done else steps
