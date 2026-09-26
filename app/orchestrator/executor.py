"""Dependency-aware executor.

  * runs independent steps in parallel (asyncio.gather)
  * runs dependents only after their dependencies succeeded
  * isolates failures: one bad agent does not crash the request
  * validates every result and retries with feedback (bounded, never infinite)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ..agents.base import AgentContext
from ..agents.registry import AGENTS
from ..config import settings
from ..errors import AgentError, AgentTimeout, ErrorInfo, NexusError
from ..llm.router import LLMRouter
from ..models import AgentResult, ContextBundle, NormalizedRequest, PlanStep, Segment, StepTrace
from .validator import validate
from typing import Awaitable, Callable

Emit = Callable[[dict], Awaitable[None]]


async def _fire(emit: "Emit | None", event: dict) -> None:
    if emit is not None:
        try:
            await emit(event)
        except Exception:
            pass          # progress events are best-effort - never let a UI hiccup break the request

log = logging.getLogger("nexus.executor")

RETRYABLE_KINDS = {"invalid_agent_output", "validation_failure"}


@dataclass
class Budget:
    """Global limits for one request - the guard against runaway loops."""
    max_calls: int = field(default_factory=lambda: settings.max_agent_calls)
    calls: int = 0

    def take(self) -> bool:
        if self.calls >= self.max_calls:
            return False
        self.calls += 1
        return True


async def _run_step(step: PlanStep, req: NormalizedRequest, ctx: ContextBundle, router: LLMRouter,
                    deps: dict[int, AgentResult], budget: Budget, iteration: int, emit: "Emit | None" = None) -> tuple[AgentResult, StepTrace]:
    t0 = time.monotonic()
    spec = AGENTS.get(step.agent)
    attempts = 0
    issues: list[str] = []
    feedback = ""
    result: AgentResult

    if spec is None:
        err = NexusError(f"Unknown agent: {step.agent}", kind="unsupported_request", layer="agent", recoverable=False)
        result = AgentResult(agent=step.agent, status="error", error=err.info())
        return result, StepTrace(id=step.id, agent=step.agent, task=step.task, status="error", attempts=0, iteration=iteration, error=err.info())

    await _fire(emit, {"type": "step_start", "id": step.id, "agent": step.agent, "task": step.task[:160], "iteration": iteration})

    while True:
        if not budget.take():
            err = AgentError("Stopped: too many agent calls for one request", kind="budget_exhausted", recoverable=False)
            result = AgentResult(agent=step.agent, status="error", error=err.info())
            break
        attempts += 1
        actx = AgentContext(request=req, context=ctx, router=router, deps=deps, feedback=feedback, attempt=attempts)
        try:
            result = await asyncio.wait_for(spec.handler(step.task, actx), timeout=settings.agent_timeout)
        except asyncio.TimeoutError:
            info = AgentTimeout(f"{step.agent} took longer than {settings.agent_timeout}s").info()
            result = AgentResult(agent=step.agent, status="error", error=info)
        except NexusError as exc:
            result = AgentResult(agent=step.agent, status="error", error=exc.info())
        except Exception as exc:                                    # never let one agent crash the request
            log.exception("agent %s crashed", step.agent)
            result = AgentResult(agent=step.agent, status="error", error=AgentError(f"{type(exc).__name__}: {exc}").info())

        if result.status == "error":
            kind = result.error.kind if result.error else ""
            if kind in RETRYABLE_KINDS and attempts <= settings.max_step_retries:
                feedback = result.error.message if result.error else "invalid output"
                issues.append(feedback)
                continue
            break

        report = validate(result)
        if report.ok:
            break
        issues.extend(report.issues)
        if attempts <= settings.max_step_retries:
            feedback = report.feedback
            continue
        # out of retries: keep the work, but tell the user honestly
        result.segments.append(Segment(type="warning", content="I could not fully verify this: " + report.feedback))
        break

    trace = StepTrace(
        id=step.id, agent=step.agent, task=step.task[:300], status=result.status, attempts=attempts,
        duration_ms=int((time.monotonic() - t0) * 1000), iteration=iteration, issues=issues[:6], error=result.error,
    )
    await _fire(emit, {"type": "step_end", "id": step.id, "agent": step.agent, "status": result.status,
                       "duration_ms": trace.duration_ms, "attempts": attempts, "iteration": iteration,
                       "issue": (result.error.message if result.error else (issues[-1] if issues else None))})
    return result, trace


async def run_steps(steps: list[PlanStep], req: NormalizedRequest, ctx: ContextBundle, router: LLMRouter,
                    results: dict[int, AgentResult], budget: Budget, iteration: int, emit: "Emit | None" = None) -> list[StepTrace]:
    """Execute `steps`, adding outputs to `results` (which may already hold earlier iterations)."""
    pending = {s.id: s for s in steps}
    traces: list[StepTrace] = []

    while pending:
        ready = [s for s in pending.values() if all((d in results) or (d not in pending) for d in s.depends_on)]
        if not ready:                                   # dependency cycle - should have been sanitized already
            for s in pending.values():
                info = ErrorInfo(kind="circular_dependency", layer="agent", message="Circular dependency in plan", recoverable=False)
                results[s.id] = AgentResult(agent=s.agent, status="error", error=info)
                traces.append(StepTrace(id=s.id, agent=s.agent, task=s.task[:300], status="error", iteration=iteration, error=info))
            break

        runnable, blocked = [], []
        for s in ready:
            failed = [d for d in s.depends_on if d in results and results[d].status == "error"]
            (blocked if failed else runnable).append((s, failed))

        for s, failed in blocked:
            pending.pop(s.id)
            info = ErrorInfo(kind="dependency_failed", layer="agent", message=f"Skipped because step {failed[0]} failed", recoverable=True)
            results[s.id] = AgentResult(agent=s.agent, status="skipped", error=info)
            traces.append(StepTrace(id=s.id, agent=s.agent, task=s.task[:300], status="skipped", iteration=iteration, error=info))

        if runnable:
            outs = await asyncio.gather(*[
                _run_step(s, req, ctx, router, {d: results[d] for d in s.depends_on if d in results}, budget, iteration, emit)
                for s, _ in runnable
            ])
            for (s, _), (res, trace) in zip(runnable, outs):
                pending.pop(s.id)
                results[s.id] = res
                traces.append(trace)
    return traces
