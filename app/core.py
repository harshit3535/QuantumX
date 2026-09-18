from __future__ import annotations

import json
from typing import Any

from .agents import AGENTS
from .config import settings
from .db import Database
from .llm import plan
from .models import AgentResult, ChatResponse, Plan


class Core:
    def __init__(self, db: Database):
        self.db = db

    async def handle(self, session_id: str, message: str, source: str, language: str) -> ChatResponse:
        session = self.db.get_session(session_id)
        if not session:
            self.db.create_session("Mission")
            # Do not silently change requested ID; a caller error is clearer.
            raise ValueError("Unknown session")

        history = self.db.history(session_id, settings.max_history_messages)
        self.db.add_message(session_id, "user", message, source)
        raw_plan = await plan(history, message)
        p = Plan.model_validate(raw_plan)

        if p.needs_clarification and p.clarification_question:
            final = AgentResult(
                agent="core",
                status="success",
                summary=p.clarification_question,
                spoken_response=p.clarification_question,
                data={"clarification": True},
                visual_type="text",
            )
            self.db.add_message(session_id, "assistant", final.summary, source)
            self.db.save_run(session_id, p.model_dump(), [final.model_dump()])
            return ChatResponse(session_id=session_id, user_message=message, plan=p, results=[final], final=final)

        context_chunks: list[str] = []
        results: list[AgentResult] = []
        step_map: dict[int, AgentResult] = {}

        for step in p.steps:
            spec = AGENTS.get(step.agent)
            if not spec:
                result = AgentResult(agent=step.agent, status="error", summary=f"Unknown agent: {step.agent}", spoken_response="I couldn't route that task to a registered specialist.")
            else:
                dependency_text = []
                for dep in step.depends_on:
                    if dep in step_map:
                        dependency_text.append(json.dumps(step_map[dep].data, ensure_ascii=False))
                joined = "\n\n".join(context_chunks[-6:] + dependency_text)
                try:
                    result = await spec.handler(step.task, joined)
                except Exception as exc:
                    result = AgentResult(agent=step.agent, status="error", summary=str(exc), spoken_response=f"The {step.agent} encountered an error.")
            results.append(result)
            step_map[step.id] = result
            context_chunks.append(result.summary)

        final = await self._compose_final(message, p, results)
        self.db.add_message(session_id, "assistant", final.summary, "voice" if source == "voice" else "text", {"visual_type": final.visual_type, "data": final.data})
        self.db.save_run(session_id, p.model_dump(), [r.model_dump() for r in results] + [final.model_dump()])
        if session["title"] == "New mission":
            self.db.update_title(session_id, self._title_from(message))
        return ChatResponse(session_id=session_id, user_message=message, plan=p, results=results, final=final)

    async def _compose_final(self, user_message: str, p: Plan, results: list[AgentResult]) -> AgentResult:
        successful = [r for r in results if r.status == "success"]
        if not successful:
            msg = "I couldn't complete that request. Tell me what you want to accomplish and I will route it differently."
            return AgentResult(agent="core", status="error", summary=msg, spoken_response=msg, data={}, visual_type="text")

        primary = successful[-1]
        # Preserve structured specialist output. This is critical for math/code rendering.
        if primary.visual_type in {"math", "code"}:
            return AgentResult(
                agent="core",
                status="success",
                summary=primary.summary,
                spoken_response=primary.spoken_response or primary.summary,
                data=primary.data,
                visual_type=primary.visual_type,
                citations=primary.citations,
            )

        combined = primary.summary
        if len(successful) > 1:
            combined = "\n\n".join(r.summary for r in successful if r.summary)
        return AgentResult(agent="core", status="success", summary=combined, spoken_response=primary.spoken_response or combined, data={"sub_results": [r.data for r in successful]}, visual_type="text")

    @staticmethod
    def _title_from(message: str) -> str:
        clean = " ".join(message.split())
        return clean[:60] + ("…" if len(clean) > 60 else "")
