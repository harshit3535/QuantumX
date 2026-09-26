"""Context + History Manager.

History is *not* one giant prompt. It is three things:

  1. conversation history  - what was said (budgeted when rendered)
  2. task state            - what we are working on, and the artifacts produced
  3. referent resolution   - what "it" / "the previous code" / "the button" points to
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from ..config import settings
from ..models import ContextBundle, NormalizedRequest, Plan, StructuredResponse
from . import knowledge
from .db import Database

MAX_ARTIFACTS = 8


class ContextManager:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ build
    def build(self, session_id: str, req: NormalizedRequest) -> ContextBundle:
        history = self.db.history(session_id, settings.max_history_messages)
        state = self.db.get_task_state(session_id)
        artifacts: list[dict[str, Any]] = state.get("artifacts", [])

        referent: dict[str, Any] | None = None
        unresolved = False

        if req.read_aloud:                      # "read the code aloud" -> latest code artifact
            referent = next((a for a in reversed(artifacts) if a.get("type") == "code"), None)

        wants_referent = (req.has_reference or req.followup_style) and referent is None
        if wants_referent:
            referent = self._pick_referent(artifacts, req)
            if referent is None and req.has_reference:
                referent = self._last_answer(history)
            if referent is None and req.has_reference:
                unresolved = True          # explicit "it"/"previous" but nothing exists yet

        slim = [{"role": m["role"], "content": m["content"], "source": m.get("source", "text")} for m in history]
        bundle = ContextBundle(session_id=session_id, history=slim, task_state=state, referent=referent, reference_unresolved=unresolved)

        # Self-improvement (background-only, see memory/knowledge.py): find the error the user
        # might be asking "why" about, so both recall() below and pipeline._learn_in_background
        # after the response is sent use the same, single source of truth.
        for m in reversed(history):
            if m["role"] == "assistant" and (m.get("metadata") or {}).get("response", {}).get("response_type") == "error":
                bundle.prior_error = m["content"]
                break
        if knowledge.is_why_question(req.text):
            note = knowledge.recall(self.db, req.text, bundle.prior_error or "")
            if note:
                bundle.learned_note = note
        return bundle

    @staticmethod
    def _pick_referent(artifacts: list[dict[str, Any]], req: NormalizedRequest) -> dict[str, Any] | None:
        if not artifacts:
            return None
        hint = req.reference_hint
        if hint in {"code", "math"}:
            for a in reversed(artifacts):
                if a.get("type") == hint:
                    return a
        # edit-like follow-up ("Make the button blue") -> most recent code, else most recent anything
        if req.followup_style and hint in {None, "any"}:
            for a in reversed(artifacts):
                if a.get("type") == "code":
                    return a
        return artifacts[-1]

    @staticmethod
    def _last_answer(history: list[dict[str, Any]]) -> dict[str, Any] | None:
        for m in reversed(history):
            if m["role"] == "assistant" and m.get("content"):
                return {"id": "last-answer", "type": "answer", "content": m["content"]}
        return None

    # ----------------------------------------------------------------- record
    def record_turn(
        self,
        session_id: str,
        req: NormalizedRequest,
        plan: Plan,
        response: StructuredResponse,
        trace: list[dict[str, Any]],
    ) -> None:
        self.db.add_message(
            session_id,
            "user",
            req.original_text or req.text,
            req.modality,
            {"language": req.language, "romanized": req.romanized, "mode": req.mode},
        )
        self.db.add_message(
            session_id,
            "assistant",
            response.plain_text() or "…",
            "voice" if req.modality == "voice" else "text",
            {"response": response.model_dump(), "plan_kind": plan.kind},
        )

        state = self.db.get_task_state(session_id)
        artifacts: list[dict[str, Any]] = state.get("artifacts", [])
        for seg in response.segments:
            if seg.type in {"code", "math"} and seg.content.strip():
                artifacts.append(
                    {
                        "id": uuid.uuid4().hex[:8],
                        "type": seg.type,
                        "language": seg.language,
                        "filename": seg.filename,
                        "content": seg.content,
                        "goal": plan.goal,
                        "created_at": int(time.time()),
                    }
                )
        state["artifacts"] = artifacts[-MAX_ARTIFACTS:]
        if plan.kind in {"task", "question"} and plan.goal:
            state["last_goal"] = plan.goal
        self.db.set_task_state(session_id, state)
        self.db.save_run(session_id, plan.model_dump(), trace)

        sess = self.db.get_session(session_id)
        if sess and sess["title"] == "New mission" and req.text:
            self.db.update_title(session_id, (req.text[:60] + ("…" if len(req.text) > 60 else "")))
