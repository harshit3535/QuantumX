"""Self-improvement, scoped safely.

This does NOT let the system rewrite its own code or behavior (that would be
dangerous to ship days before a deadline). It does ONE narrow, safe thing:

  When a user hits an error, then asks a follow-up like "why did that happen" /
  "how do I fix this", the explanation Astra works out is saved as a small
  (question -> explanation) note, keyed by keywords. The NEXT user who hits a
  similar situation gets that note silently folded into their context, so the
  system answers faster and more specifically without repeating the same
  research from scratch.

Runs entirely in the background:
  - the lookup (`recall`) is one cheap in-memory keyword match, done while
    building context - it never calls an AI model and never blocks the request
  - the write (`learn_from_turn`) happens via asyncio.create_task AFTER the
    response was already sent to the user, so it costs the user's turn nothing
Nothing about this is shown in the UI - it is not part of the hackathon demo.
"""
from __future__ import annotations

import logging
import re

from .db import Database

log = logging.getLogger("nexus.knowledge")

_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "for", "and", "or", "but", "how", "what",
    "why", "did", "do", "does", "i", "it", "that", "this", "my", "me", "you", "your", "with", "at", "as", "be",
    "can", "could", "would", "should", "will", "not", "no", "aa", "che", "chhe", "shu", "kem", "hu", "mane", "मे",
    "है", "को", "का", "में", "से",
}
_WORD = re.compile(r"[a-z0-9\u0A80-\u0AFF\u0900-\u097F]{3,}")

_WHY = re.compile(
    r"^\s*(why|how (do|to|can) (i|we) fix|what (went|goes) wrong|kem (aavi|thai)|"
    r"क्यों|यह क्यों|कैसे ठीक|કેમ આવી|કેમ થઈ)",
    re.I,
)


def keywords_of(*texts: str, limit: int = 12) -> set[str]:
    words: list[str] = []
    for t in texts:
        words.extend(w.lower() for w in _WORD.findall(t or ""))
    uniq = set(w for w in words if w not in _STOP)
    return set(list(uniq)[:limit]) if len(uniq) > limit else uniq


def is_why_question(text: str) -> bool:
    return bool(_WHY.match((text or "").strip()))


def recall(db: Database, question: str, error_context: str = "") -> str | None:
    """Cheap synchronous lookup - safe to call while building context for every request."""
    kw = keywords_of(question, error_context)
    if len(kw) < 2:
        return None
    hits = db.search_knowledge(kw, limit=1)
    if not hits:
        return None
    return hits[0]["explanation"]


async def learn_from_turn(db: Database, session_id: str, prior_error: str, question: str, explanation: str) -> None:
    """Fire-and-forget: call via asyncio.create_task, never awaited by the request path."""
    try:
        if not explanation.strip() or len(explanation) < 20:
            return
        kw = keywords_of(question, prior_error)
        if len(kw) < 2:
            return
        db.add_knowledge(",".join(sorted(kw)), question, explanation)
        log.info("learned from session %s: %s", session_id, ",".join(sorted(kw))[:120])
    except Exception:
        log.exception("background learning failed (non-fatal)")
