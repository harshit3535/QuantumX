"""Agency-inspired task direction for Astra.

The reference Agency Agents project emphasizes four practical ideas:
  * define the outcome before the steps,
  * cast a team instead of a soloist,
  * loop until evidence satisfies the done-bar,
  * feed the team enough context to execute correctly.

This module applies those ideas to Astra's existing AOB without importing or
executing third-party agent files. It converts an AOB plan into an explicit
Task Contract + role assignments, and it adds a reviewer when the work product
benefits from a second pass.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import ContextBundle, NormalizedRequest, Plan, PlanStep


@dataclass(frozen=True)
class TeamPreset:
    key: str
    label: str
    purpose: str
    members: tuple[tuple[str, str], ...]  # (role, agent)
    completion_policy: str


TEAMS: dict[str, TeamPreset] = {
    "solo-general": TeamPreset(
        "solo-general", "General", "Direct conversation or simple answers.",
        (("operator", "general_agent"),),
        "Answer the user's request directly and do not invent work you did not perform.",
    ),
    "build-and-review": TeamPreset(
        "build-and-review", "Build & Review", "Produce a real work product, then independently review it.",
        (("builder", "code_agent"), ("reviewer", "verifier_agent")),
        "Build the complete artifact, review the result, fix concrete issues, and only then deliver it.",
    ),
    "research-and-verify": TeamPreset(
        "research-and-verify", "Research & Verify", "Gather evidence, then challenge the first answer.",
        (("researcher", "web_agent"), ("reviewer", "verifier_agent")),
        "Use fresh evidence, verify important claims, and deliver only what survived review.",
    ),
    "diagnose-and-resolve": TeamPreset(
        "diagnose-and-resolve", "Diagnose & Resolve", "Run a real diagnostic and report verified evidence.",
        (("operator", "operator_agent"),),
        "Run the real diagnostic, preserve evidence, and do not claim a check that was not executed.",
    ),
    "front-desk": TeamPreset(
        "front-desk", "Front Desk", "Handle customer requests with clarification and explicit confirmation for writes.",
        (("receptionist", "receptionist_agent"),),
        "Collect only missing details, verify availability, read back the proposed action, and require confirmation before booking writes.",
    ),
    "floor-ops": TeamPreset(
        "floor-ops", "FloorOps", "Handle warehouse/factory-floor stock, safety, incidents and shift handoff.",
        (("floor_operator", "floorops_agent"),),
        "Prefer auditable checks and logs; never claim a machine was physically controlled.",
    ),
}


def _pick_team(plan: Plan) -> TeamPreset:
    if plan.mission_type == "receptionist" or any(s.agent == "receptionist_agent" for s in plan.steps):
        return TEAMS["front-desk"]
    if plan.mission_type == "incident" or any(s.agent == "floorops_agent" for s in plan.steps):
        return TEAMS["floor-ops"]
    if any(s.agent == "code_agent" for s in plan.steps):
        return TEAMS["build-and-review"]
    if any(s.agent in {"web_agent", "research_agent"} for s in plan.steps):
        return TEAMS["research-and-verify"]
    if any(s.agent == "operator_agent" for s in plan.steps):
        return TEAMS["diagnose-and-resolve"]
    return TEAMS["solo-general"]


def _deliverables(req: NormalizedRequest, plan: Plan) -> list[str]:
    if any(s.agent == "code_agent" for s in plan.steps):
        return ["Complete runnable files for the requested change", "Validation/review result"]
    if plan.mission_type == "receptionist":
        return ["Correct customer-facing answer", "Availability or booking outcome"]
    if plan.mission_type in {"research", "diagnostic"}:
        return ["Answer grounded in evidence", "Sources or diagnostic evidence where applicable"]
    return ["A direct answer or completed task result"]


def _success_criteria(req: NormalizedRequest, plan: Plan) -> list[str]:
    if any(s.agent == "code_agent" for s in plan.steps):
        return [
            "All requested files are complete; no ellipses or placeholders.",
            "The output is structured as named files and is ready to use.",
            "A reviewer has checked the generated work and any concrete issue is fixed or clearly reported.",
        ]
    if plan.mission_type == "receptionist":
        return [
            "Only necessary details are requested.",
            "Availability is checked before booking.",
            "No booking write happens without explicit confirmation.",
        ]
    if plan.mission_type == "diagnostic":
        return ["A real public diagnostic was executed.", "The answer reflects the observed result."]
    if plan.mission_type == "research":
        return ["Important claims are supported by retrieved evidence.", "The response does not pretend to have stronger evidence than it has."]
    return ["The user's requested outcome is directly addressed."]


def _find_last_agent_step(steps: list[PlanStep], agent: str) -> PlanStep | None:
    for s in reversed(steps):
        if s.agent == agent:
            return s
    return None


def assign_team(req: NormalizedRequest, ctx: ContextBundle, plan: Plan) -> Plan:
    """Add a concrete team, done-bar, and reviewer to a plan where useful."""
    team = _pick_team(plan)
    steps = list(plan.steps)

    # Build tasks should never end at "here is a suggestion". A reviewer follows
    # the builder and the AOB can schedule a fix if the reviewer finds problems.
    if team.key == "build-and-review":
        code_step = _find_last_agent_step(steps, "code_agent")
        has_reviewer = any(s.agent == "verifier_agent" for s in steps)
        if code_step and not has_reviewer:
            steps.append(
                PlanStep(
                    id=max((s.id for s in steps), default=0) + 1,
                    agent="verifier_agent",
                    role="reviewer",
                    activation="after builder",
                    task=(
                        "Review the complete generated files from the builder. Check correctness, completeness, "
                        "missing files, broken references, obvious syntax/runtime problems, and whether the requested "
                        "outcome is actually delivered. Return PASS when it is ready; return FAIL with specific fixes "
                        "when it is not. Do not rewrite the files yourself.") ,
                    depends_on=[code_step.id],
                    expected_output="PASS/FAIL with concrete issues",
                    done_when="PASS, or a concrete issue list that can be fixed by the builder.",
                )
            )
            plan.may_need_followup = True

    # Give every step a role + activation + a concrete done-bar.
    role_by_agent: dict[str, str] = {agent: role for role, agent in team.members}
    for i, step in enumerate(steps):
        if not step.role:
            step.role = role_by_agent.get(step.agent, "specialist")
        if not step.activation:
            step.activation = "when dependencies are complete" if step.depends_on else "immediately"
        if not step.done_when:
            step.done_when = step.expected_output or "Return a concrete result that can be validated by the next step."

        # Convert vague builder instructions into outcome-first tasks.
        if step.agent == "code_agent":
            step.task = (
                f"Outcome: {plan.goal or req.text}. Build the complete requested work product. "
                f"Deliverables: {', '.join(_deliverables(req, plan))}. "
                "Do the work itself; do not answer with instructions for the user to create files. "
                "Return every requested file completely, with exact file names."
            )
            step.done_when = "Every essential requested file is complete and ready to use."
        elif step.agent == "web_agent":
            step.done_when = "Fresh search evidence has been gathered and synthesized without invented citations."
        elif step.agent == "receptionist_agent":
            step.done_when = "The customer request is answered or the explicitly confirmed booking action is completed."
        elif step.agent == "floorops_agent":
            step.done_when = "The floor request is answered with a real inventory, checklist, incident or handoff result."

    plan.steps = steps
    plan.team = team.label
    plan.assignments = [
        {
            "role": s.role,
            "agent": s.agent,
            "task": s.task,
            "activation": s.activation,
            "depends_on": s.depends_on,
            "done_when": s.done_when,
            "expected_output": s.expected_output,
        }
        for s in steps
    ]
    plan.deliverables = _deliverables(req, plan)
    plan.success_criteria = _success_criteria(req, plan)
    plan.completion_policy = team.completion_policy
    plan.task_contract = {
        "objective": plan.goal or req.text,
        "context": ctx.render(1800),
        "constraints": [
            "Preserve the user's original request; do not silently replace it with a summary.",
            "Use only registered Astra agents and tools.",
            "Stop only when the success criteria are met, a required user answer is missing, or a bounded safety/timeout budget is reached.",
        ],
    }
    return plan


def team_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": t.key,
            "label": t.label,
            "purpose": t.purpose,
            "members": [{"role": role, "agent": agent} for role, agent in t.members],
            "completion_policy": t.completion_policy,
        }
        for t in TEAMS.values()
    ]
