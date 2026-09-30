"""Result composition: agent results -> ONE structured response."""
from __future__ import annotations

import hashlib

from ..errors import ErrorInfo
from ..models import AgentResult, Plan, Segment, StructuredResponse
from .parser import guess_kind

_FRIENDLY = {
    "llm_unavailable": "I couldn't reach an AI model right now. Check that at least one API key (Gemini, Groq or OpenRouter) is set and has quota left.",
    "llm_rate_limited": "The free AI quota is busy for a moment. Please try again in a few seconds.",
    "llm_auth_failed": "An AI provider rejected its API key. Please check the key in the environment settings.",
    "llm_model_not_found": "The configured AI model name doesn't exist any more. Update the model name in the environment settings.",
    "agent_timeout": "That took too long, so I stopped. Try a smaller request.",
    "budget_exhausted": "That request needed too many steps, so I stopped safely. Try splitting it up.",
    "invalid_agent_output": "The AI answered in a format I couldn't use. Please try again.",
}


def friendly_error(err: ErrorInfo | None) -> str:
    if err is None:
        return "Something went wrong on my side. Please try again."
    return _FRIENDLY.get(err.kind, err.message or "Something went wrong on my side. Please try again.")


def clarification_response(question: str) -> StructuredResponse:
    return StructuredResponse(response_type="clarification", segments=[Segment(type="text", content=question)], meta={"clarification": True})


def _artifact_files(results: list[AgentResult]) -> list[dict]:
    """Turn code-agent output into durable, named file records for the UI preview."""
    files: list[dict] = []
    for result in results:
        for seg in result.segments:
            if seg.type != "code" or not seg.content.strip():
                continue
            language = (seg.language or "text").lower()
            filename = seg.filename
            if not filename:
                ext = {"python":"py","javascript":"js","typescript":"ts","html":"html","css":"css","json":"json","bash":"sh"}.get(language, "txt")
                if language == "html":
                    filename = "index.html"
                elif language == "css":
                    filename = "styles.css"
                elif language in {"javascript", "typescript"}:
                    filename = "script." + ext
                else:
                    filename = "main." + ext
            filename = str(filename).replace("\\", "/").lstrip("/")
            if any(f["path"] == filename for f in files):
                # Keep both files when an agent accidentally reuses a filename.
                stem, dot, ext = filename.rpartition(".")
                base = stem or "file"
                filename = f"{base}-{len(files)+1}.{ext}" if dot else f"{filename}-{len(files)+1}"
            files.append({"path": filename, "filename": filename, "language": seg.language or language, "content": seg.content})
    return files


def _artifact_bundle(plan: Plan, results: list[AgentResult]) -> dict | None:
    files = _artifact_files(results)
    if not files:
        return None
    entrypoint = next((f["path"] for f in files if f["path"].lower() == "index.html"), None)
    return {
        "id": "artifact-" + hashlib.sha1((plan.goal or "generated-project").encode("utf-8")).hexdigest()[:10],
        "type": "code_project",
        "title": plan.goal[:120] or "Generated project",
        "files": files,
        "entrypoint": entrypoint,
        "preview": bool(entrypoint),
        "sandboxed_preview": True,
    }


def compose(plan: Plan, ordered: list[tuple[int, AgentResult]], timed_out: bool = False) -> tuple[StructuredResponse, ErrorInfo | None]:
    """`ordered` is [(step_id, result)] in plan order across all iterations."""
    ok = [(i, r) for i, r in ordered if r.status == "success"]
    failed = [(i, r) for i, r in ordered if r.status == "error"]
    content = [(i, r) for i, r in ok if r.agent != "verifier_agent"]
    verifiers = [r for _, r in ok if r.agent == "verifier_agent"]

    if not content:
        first = failed[0][1].error if failed and failed[0][1].error else None
        msg = friendly_error(first)
        if timed_out:
            msg = _FRIENDLY["agent_timeout"]
        return StructuredResponse(response_type="error", segments=[Segment(type="error", content=msg)]), first

    # A summarizer that consumed earlier steps is the final answer on its own.
    last_id, last = content[-1]
    if last.agent == "summarizer_agent" and len(content) > 1:
        chosen = [last]
    else:
        chosen = [r for _, r in content]

    segs: list[Segment] = []
    meta: dict = {"evidence": [], "actions": [], "team": plan.team, "deliverables": plan.deliverables,
                  "success_criteria": plan.success_criteria, "completion_policy": plan.completion_policy,
                  "task_contract": plan.task_contract}
    for r in chosen:
        if r.data.get("evidence"):
            meta["evidence"].extend(r.data.get("evidence") or [])
        if r.data.get("approval_required"):
            pa = r.data.get("pending_action") or {}
            meta["approval"] = {"required": True, "kind": pa.get("kind", "action"), "label": pa.get("label", "Confirm action")}
        if r.data.get("pending_action"):
            meta["pending_action"] = r.data["pending_action"]
        if r.data.get("clear_pending_action"):
            meta["clear_pending_action"] = True
        if r.data.get("draft_booking"):
            meta["draft_booking"] = r.data["draft_booking"]
        if r.data.get("clear_draft_booking"):
            meta["clear_draft_booking"] = True
        if r.data.get("outcome"):
            meta["outcome"] = r.data["outcome"]
        if r.data.get("tool"):
            tool_name = r.data["tool"]
            meta["actions"].append({"tool": tool_name, "status": "executed"})
            # Backfill evidence for deterministic tools whose agents expose raw tool data.
            if tool_name == "check_url" and not r.data.get("evidence"):
                status = r.data.get("status_code")
                if status is not None:
                    meta["evidence"].append({"type": "http", "label": "HTTP response", "value": f"HTTP {status}"})
                if r.data.get("latency_ms") is not None:
                    meta["evidence"].append({"type": "latency", "label": "Diagnostic latency", "value": f"{r.data['latency_ms']} ms"})
                if r.data.get("final_url"):
                    meta["evidence"].append({"type": "url", "label": "Final URL", "value": str(r.data["final_url"])[:240]})
            if tool_name == "web_search" and not r.data.get("evidence"):
                rows = r.data.get("results") or []
                for row in rows[:3]:
                    meta["evidence"].append({"type": "source", "label": row.get("title", "Web source"), "value": row.get("url", "")})
        for s in r.segments:
            if segs and segs[-1] == s:
                continue
            segs.append(s)

    artifact = _artifact_bundle(plan, [r for _, r in content if r.agent == "code_agent"])
    if artifact:
        meta["artifacts"] = [artifact]
        meta["artifact_count"] = len(artifact["files"])
        # Code tasks should show the actual work product in the artifact workspace,
        # not bury it in a giant assistant paragraph. Keep a compact status sentence
        # and warnings, while the complete files live in the structured artifact.
        # Keep the complete typed code segments too: the rich renderer shows them
        # inside the artifact workspace, while the user still gets a normal
        # structured response when opening the saved history.
        status = next((s for s in segs if s.type == "text"), None)
        if status is None:
            segs.insert(0, Segment(type="text", content="Completed the requested code build."))

    for v in verifiers:
        segs.extend(s for s in v.segments if s.type == "warning")
    for _, r in failed:
        segs.append(Segment(type="warning", content=f"One step didn't finish ({r.agent.replace('_', ' ')}): {friendly_error(r.error)}"))
    if timed_out:
        segs.append(Segment(type="warning", content="I ran out of time, so this may be incomplete."))

    if not segs:
        segs = [Segment(type="text", content="Done.")]
    meta["mission_type"] = plan.mission_type
    response_type = "code" if meta.get("artifacts") else guess_kind(segs)
    return StructuredResponse(response_type=response_type, segments=segs, meta=meta), (failed[0][1].error if failed else None)
