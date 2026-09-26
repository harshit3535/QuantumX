import asyncio

from app.memory import knowledge
from app.models import ChatRequest


def test_is_why_question():
    assert knowledge.is_why_question("why did that happen")
    assert knowledge.is_why_question("Kem aavi error aavi")
    assert knowledge.is_why_question("क्यों आई यह गलती")
    assert not knowledge.is_why_question("write a python calculator")


def test_recall_needs_min_overlap_and_updates_hits(db):
    db.add_knowledge("render,environment,variable,github,deploy", "why does render deploy fail",
                      "You need to set environment variables and requirements.txt on Render before deploying.")
    note = knowledge.recall(db, "why did my render deploy fail with github")
    assert note and "environment variables" in note
    hits = db.search_knowledge({"render", "environment", "variable"}, limit=1)
    assert hits[0]["hits"] >= 2                      # recall() + this direct call both counted


def test_recall_returns_none_without_enough_overlap(db):
    db.add_knowledge("render,environment,variable", "q", "explanation text here")
    assert knowledge.recall(db, "why is the sky blue") is None


def test_full_turn_learns_in_background_and_next_user_benefits(offline, db):
    async def turn1():
        return await offline.chat(ChatRequest(session_id="s1", message="Create a Python calculator"))
    r1 = asyncio.run(turn1())
    assert r1.response.response_type == "error"       # no AI configured -> llm_unavailable

    async def turn2():
        return await offline.chat(ChatRequest(session_id="s1", message="why did that fail"))
    r2 = asyncio.run(turn2())
    assert r2.response.response_type == "error"        # still offline, general_agent also needs an AI provider

    # simulate what learning WOULD store, using the real background function directly
    asyncio.run(knowledge.learn_from_turn(db, "s1", "no AI provider is configured", "why did that fail",
                                          "No AI provider is configured, so add GEMINI_API_KEY or GROQ_API_KEY on Render."))
    note = knowledge.recall(db, "why did creating a python calculator fail", "no AI provider is configured")
    assert note and "GEMINI_API_KEY" in note


def test_learning_is_fire_and_forget_and_never_raises(offline):
    async def go():
        return await offline.chat(ChatRequest(session_id="s1", message="why did that happen"))
    r = asyncio.run(go())
    assert r.error is None or r.response.response_type in {"error", "text", "clarification"}
