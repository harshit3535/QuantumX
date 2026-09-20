from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Callable

from agents.factory import build_agents
from core.history import HistoryManager
from core.models import ExecutionPlan, HistoryTurn, InputEnvelope, PlanStep, ResponseSegment, StructuredResponse
from core.normalizer import InputNormalizer
from core.response import ResponseParser
from llm.base import LLMClient


PLANNER_SYSTEM = """
You are the Agent Orchestration Brain (AOB) planner.
You receive one user request plus context and must choose the minimal useful set of agents.
Available agents:
- general: conversation, clarification, broad assistance
- coding: programming and code generation/modification
- math: mathematical calculation, equations, derivations
- validation: checks a generated artifact; normally depends on coding or math

Never invent an unavailable agent. Do not select every agent by default.
If the user intent is not sufficiently clear, set clarification_needed=true and provide one concise question.
Return ONLY valid JSON with this exact shape:
{
  "intent": "...",
  "clarification_needed": false,
  "clarification_question": "",
  "steps": [
    {"agent":"coding","task":"...","depends_on":[]}
  ],
  "expected_response_types": ["text"],
  "notes": "..."
}
""".strip()


class AgentOrchestrator:
    def __init__(self, llm: LLMClient, history: HistoryManager, log: Callable[[str], None] | None = None) -> None:
        self.llm = llm
        self.history = history
        self.log = log or (lambda _: None)
        self.normalizer = InputNormalizer()
        self.parser = ResponseParser()
        self.agents = build_agents(llm, self.log)

    def handle(self, envelope: InputEnvelope) -> StructuredResponse:
        self.log(f"AOB: received {envelope.input_mode} input in {envelope.mode} mode")
        normalized = self.normalizer.normalize(envelope)
        self.history.add(HistoryTurn("user", normalized.envelope.text, envelope.mode, envelope.input_mode))

        if normalized.needs_clarification:
            response = StructuredResponse([
                ResponseSegment("warning", "I need one clarification before I act."),
                ResponseSegment("text", normalized.clarification_reason),
            ])
            response.spoken_text = self.parser.to_speech(response.segments)
            self.history.add(HistoryTurn("assistant", response.plain_text(), envelope.mode, envelope.input_mode, [s.type for s in response.segments]))
            return response

        plan = self._build_plan(normalized.envelope.text, normalized.intent_hint, normalized.content_types)
        self.history.set_task_state(last_intent=plan.intent, active_agents=",".join(s.agent for s in plan.steps))

        if plan.clarification_needed:
            response = StructuredResponse([ResponseSegment("text", plan.clarification_question or "Could you clarify the request?")])
            response.spoken_text = response.plain_text()
            self.history.add(HistoryTurn("assistant", response.plain_text(), envelope.mode, envelope.input_mode, ["text"]))
            return response

        results: dict[str, str] = {}
        final_segments: list[ResponseSegment] = []
        ordered = self._topological_order(plan.steps)

        for step in ordered:
            agent = self.agents.get(step.agent)
            if not agent:
                self.log(f"AOB: skipping unknown agent '{step.agent}'")
                continue
            self.log(f"AOB: assigning '{step.agent}' -> {step.task}")
            try:
                segments = agent.run(step.task, normalized.envelope, self.history.prompt_context(), results)
            except Exception as exc:
                self.log(f"AOB: agent '{step.agent}' failed: {exc}")
                segments = [ResponseSegment("error", f"Agent '{step.agent}' failed safely: {exc}")]

            text_result = "\n\n".join(seg.content for seg in segments)
            results[step.agent] = text_result

            # Validation is metadata/checking; its output is useful but not the main answer.
            if step.agent != "validation":
                final_segments.extend(segments)
            else:
                final_segments.extend(segments)

        # If multiple agents produce overlapping final prose, collapse obvious duplicates.
        final_segments = self._dedupe_segments(final_segments)
        response = StructuredResponse(final_segments or [ResponseSegment("text", "No agent produced a response.")])
        response.metadata.update({
            "mode": envelope.mode,
            "input_mode": envelope.input_mode,
            "plan": [step.__dict__ for step in plan.steps],
            "intent": plan.intent,
            "content_types": normalized.content_types,
        })
        response.spoken_text = self.parser.to_speech(response.segments)

        self.history.add(
            HistoryTurn(
                "assistant",
                response.plain_text(),
                envelope.mode,
                envelope.input_mode,
                [s.type for s in response.segments],
            )
        )
        return response

    def _build_plan(self, text: str, intent_hint: str, content_types: list[str]) -> ExecutionPlan:
        context = self.history.prompt_context()
        user_prompt = (
            f"Current input:\n{text}\n\n"
            f"Heuristic intent hint: {intent_hint}\n"
            f"Detected content types: {', '.join(content_types)}\n\n"
            f"Conversation context:\n{context or '(none)'}"
        )
        try:
            raw = self.llm.chat(
                [{"role": "system", "content": PLANNER_SYSTEM}, {"role": "user", "content": user_prompt}],
                temperature=0.0,
            )
            data = self._parse_json(raw)
            return self._validate_plan(data, intent_hint)
        except Exception as exc:
            self.log(f"AOB planner fallback: {exc}")
            return self._heuristic_plan(text, intent_hint)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
        raw = re.sub(r"```$", "", raw).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Planner did not return a JSON object.")
        return json.loads(raw[start : end + 1])

    def _validate_plan(self, data: dict, intent_hint: str) -> ExecutionPlan:
        allowed = set(self.agents.keys())
        steps: list[PlanStep] = []
        for raw_step in data.get("steps", []):
            agent = str(raw_step.get("agent", "")).strip()
            if agent not in allowed:
                continue
            steps.append(
                PlanStep(
                    agent=agent,
                    task=str(raw_step.get("task", "Respond helpfully.")),
                    depends_on=[d for d in raw_step.get("depends_on", []) if d in allowed],
                )
            )
        if not steps:
            steps = self._heuristic_plan("", intent_hint).steps
        return ExecutionPlan(
            intent=str(data.get("intent") or intent_hint or "general"),
            clarification_needed=bool(data.get("clarification_needed", False)),
            clarification_question=str(data.get("clarification_question", "")),
            steps=steps,
            expected_response_types=[str(x) for x in data.get("expected_response_types", ["text"])],
            notes=str(data.get("notes", "")),
        )

    def _heuristic_plan(self, text: str, intent: str) -> ExecutionPlan:
        lower = text.lower()
        if any(k in lower for k in ("build", "create", "make", "code", "python", "program")):
            return ExecutionPlan("coding", steps=[PlanStep("coding", "Implement the requested code", [])])
        if any(k in lower for k in ("solve", "equation", "calculate", "math")):
            return ExecutionPlan("math", steps=[PlanStep("math", "Solve or explain the mathematical request", [])])
        if not text and intent == "empty":
            return ExecutionPlan("empty", clarification_needed=True, clarification_question="What would you like me to do?")
        return ExecutionPlan("general", steps=[PlanStep("general", "Respond helpfully to the request", [])])

    @staticmethod
    def _topological_order(steps: list[PlanStep]) -> list[PlanStep]:
        by_name = {step.agent: step for step in steps}
        indegree = defaultdict(int)
        outgoing = defaultdict(list)
        for step in steps:
            for dep in step.depends_on:
                if dep in by_name:
                    indegree[step.agent] += 1
                    outgoing[dep].append(step.agent)

        q = deque(step.agent for step in steps if indegree[step.agent] == 0)
        ordered_names: list[str] = []
        while q:
            name = q.popleft()
            ordered_names.append(name)
            for nxt in outgoing[name]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    q.append(nxt)

        if len(ordered_names) != len(steps):
            # Cycles are unsafe for v1.0: fall back to declared order.
            return steps
        return [by_name[name] for name in ordered_names]

    @staticmethod
    def _dedupe_segments(segments: list[ResponseSegment]) -> list[ResponseSegment]:
        out: list[ResponseSegment] = []
        seen: set[tuple[str, str]] = set()
        for segment in segments:
            key = (segment.type, segment.content.strip())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            out.append(segment)
        return out
