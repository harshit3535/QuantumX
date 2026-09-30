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
        bundle = ContextBundle(session_id=session_id, history=slim, task_state=state, referent=referent, reference_unresolved=unresolved, db=self.db)

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
        # Code projects are now stored as named files in response.meta.artifacts so
        # the complete work product survives beyond the chat bubble and can be
        # edited/referred to on a later turn. Keep the older single-segment path for
        # math and any legacy responses.
        bundled = response.meta.get("artifacts", []) if isinstance(response.meta, dict) else []
        seen_paths = {str(a.get("filename") or "") for a in artifacts if a.get("filename")}
        for bundle in bundled:
            for f in bundle.get("files", []):
                content = str(f.get("content") or "")
                filename = str(f.get("path") or f.get("filename") or "")
                if not content or not filename:
                    continue
                if filename in seen_paths:
                    artifacts = [a for a in artifacts if a.get("filename") != filename]
                seen_paths.add(filename)
                artifacts.append({
                    "id": uuid.uuid4().hex[:8],
                    "type": "code",
                    "language": f.get("language"),
                    "filename": filename,
                    "content": content,
                    "goal": plan.goal,
                    "created_at": int(time.time()),
                })
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
        meta = response.meta or {}
        if meta.get("pending_action"):
            state["pending_action"] = meta["pending_action"]
        elif meta.get("clear_pending_action"):
            state.pop("pending_action", None)
        if meta.get("draft_booking"):
            state["draft_booking"] = meta["draft_booking"]
        elif meta.get("clear_draft_booking"):
            state.pop("draft_booking", None)
        if meta.get("mission_type"):
            state["mission_type"] = meta["mission_type"]
        mission_meta = meta.get("mission") or {}
        if mission_meta.get("status"):
            state["last_status"] = mission_meta["status"]
        if mission_meta.get("verified") is not None:
            state["verified"] = bool(mission_meta.get("verified"))
        if meta.get("outcome"):
            state["last_outcome"] = meta["outcome"]
        if meta.get("team"):
            state["team"] = meta["team"]
        if meta.get("deliverables"):
            state["deliverables"] = meta["deliverables"]
        if meta.get("success_criteria"):
            state["success_criteria"] = meta["success_criteria"]
        if meta.get("completion_policy"):
            state["completion_policy"] = meta["completion_policy"]
        if meta.get("task_contract"):
            state["task_contract"] = meta["task_contract"]
        self.db.set_task_state(session_id, state)
        self.db.save_run(session_id, plan.model_dump(), trace)

        sess = self.db.get_session(session_id)
        if sess and sess["title"] == "New mission" and req.text:
            self.db.update_title(session_id, (req.text[:60] + ("…" if len(req.text) > 60 else "")))
