"""The whole flow, in the order of the architecture diagram.

  input adapter -> INPUT NORMALIZER -> CONTEXT/HISTORY -> AOB -> agents
                -> structured response -> OUTPUT DECISION -> UI / TTS
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from .errors import ErrorInfo
from .input.normalizer import normalize
from .llm.router import LLMRouter, get_router
from .memory import knowledge
from .memory.context import ContextManager
from .memory.db import Database
from .models import ChatRequest, ChatResponse, ContextBundle, NormalizedRequest, Plan, Segment, StructuredResponse
from .modes import build_mode_config
from .orchestrator.aob import Orchestrator
from .orchestrator.control import assess_action, build_mission
from .response.decision import decide_output

log = logging.getLogger("nexus.pipeline")

Emit = Callable[[dict], Awaitable[None]]


class Nexus:
    def __init__(self, db: Database, router: LLMRouter | None = None):
        self.db = db
        self.router = router or get_router()
        self.context = ContextManager(db)
        self.aob = Orchestrator(self.router)

    async def chat(self, req: ChatRequest, emit: Emit | None = None) -> ChatResponse:
        self.db.ensure_session(req.session_id)
        cfg = build_mode_config(req.mode, req.source, req.output, req.stt_provider)
        norm = normalize(req.message, modality=req.source, mode=req.mode, language_hint=req.language, output_pref=req.output,
                        force_agent=req.force_agent, force_think=req.force_think)
        ctx = self.context.build(req.session_id, norm)

        try:
            result = await self.aob.run(norm, ctx, emit=emit)
            plan, trace, response, iterations, error = result.plan, result.trace, result.response, result.iterations, result.error
        except Exception as exc:                        # last line of defence: never a bare 500 to the UI
            log.exception("AOB crashed")
            plan = Plan(kind="unclear", goal=norm.text[:200])
            trace, iterations = [], 0
            error = ErrorInfo(kind="system_error", layer="system", message=f"{type(exc).__name__}", recoverable=True)
            response = StructuredResponse(response_type="error", segments=[Segment(type="error", content="Something went wrong on my side. Please try again.")])

        approval = assess_action(norm, plan)
        if approval.approval_required and not any(s.type == "warning" and "approval" in s.content.lower() for s in response.segments):
            response.segments.append(Segment(type="warning", content="Human approval gate: Astra prepared the result but will not treat a high-impact external action as completed without explicit user confirmation."))
        decision = decide_output(cfg, norm, response)
        mission = build_mission(norm, plan, trace, iterations, done=(error is None), approval=approval)
        self.context.record_turn(req.session_id, norm, plan, response, [t.model_dump() for t in trace])
        self.db.add_event(req.session_id, "mission_complete", mission)
        self._learn_in_background(req.session_id, norm, ctx, response)

        return ChatResponse(
            session_id=req.session_id,
            mode=cfg.mode,
            user_message=norm.original_text,
            mission=mission,
            normalized={
                "language": norm.language, "romanized": norm.romanized, "modality": norm.modality, "intent": norm.intent_hint,
                "content_types": norm.content_types, "is_question": norm.is_question, "is_command": norm.is_command,
                "is_conversational": norm.is_conversational, "is_incomplete": norm.is_incomplete,
                "has_reference": norm.has_reference, "needs_clarification": norm.needs_clarification,
            },
            plan=plan, trace=trace, response=response, output=decision, iterations=iterations, error=error,
        )

    def _learn_in_background(self, session_id: str, norm: NormalizedRequest, ctx: ContextBundle, response: StructuredResponse) -> None:
        """Fire-and-forget: never awaited, never slows down the reply, never shown in the UI."""
        if not knowledge.is_why_question(norm.text):
            return
        explanation = response.plain_text()
        if not explanation:
            return
        try:
            asyncio.create_task(knowledge.learn_from_turn(self.db, session_id, ctx.prior_error or "", norm.text, explanation))
        except RuntimeError:
            pass          # no running event loop (e.g. a sync test) - safe to skip
