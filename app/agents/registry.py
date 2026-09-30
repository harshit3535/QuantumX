"""Agent registry. Adding an agent = add one entry here; the AOB picks it up from `describe()`.

`usage` is a short "when to use this, not that" line (inspired by how large agent
catalogs like Anthropic's agency-agents disambiguate similar specialists) - it exists
purely to sharpen the LLM planner's routing, so keep it to one crisp contrast.
"""
from __future__ import annotations

from .base import AgentSpec
from .code_agent import code_agent
from .general import general_agent
from .math_agent import math_agent
from .operator_agent import operator_agent
from .receptionist_agent import receptionist_agent
from .floorops_agent import floorops_agent
from .text_agents import research_agent, summarizer_agent, verifier_agent
from .web_agent import web_agent

AGENTS: dict[str, AgentSpec] = {
    "general_agent": AgentSpec(
        "general_agent", "Conversation, general questions, explanations, casual talk, clarifications", general_agent,
        needs_llm=False, usage="Default agent. Use for chat, opinions, or anything that isn't math/code/current-events/summarizing."),
    "math_agent": AgentSpec(
        "math_agent", "Math: equations, calculus, arithmetic, word problems. Returns LaTeX (verified with SymPy when possible)", math_agent,
        needs_llm=False, usage="Use whenever the task is a calculation or equation, even a small one - it is exact and free."),
    "code_agent": AgentSpec(
        "code_agent", "Writes or edits code (any language). Returns complete files with language + filename", code_agent,
        usage="Use for writing, fixing or editing actual code/files. Not for explaining a programming concept in words - use research_agent for that."),
    "research_agent": AgentSpec(
        "research_agent", "Explains a topic from the model's own training knowledge (no live web)", research_agent,
        usage="Use for stable, well-established knowledge (history, concepts, how things work). NOT for anything that could have changed recently - use web_agent for that."),
    "receptionist_agent": AgentSpec(
        "receptionist_agent", "Acts as a business front desk: answers hours/services, checks live availability, proposes and confirms appointments, looks up bookings, and captures messages", receptionist_agent,
        needs_llm=False, usage="Use for appointment, receptionist, booking, front-desk, availability, callback or business-hours tasks. Uses real SQLite records and explicit confirmation before booking writes."),
    "floorops_agent": AgentSpec(
        "floorops_agent", "Voice-first warehouse/factory floor assistant for stock checks, safety checklists, incident logs and shift handoffs", floorops_agent,
        needs_llm=False, usage="Use only in FloorOps workspace for inventory, safety, incident and shift-handoff work."),
    "operator_agent": AgentSpec(
        "operator_agent", "Runs safe, real public tools such as website health checks and live web lookups", operator_agent,
        needs_llm=False, usage="Use for a real public action/diagnostic (especially checking a URL/site/server) instead of merely describing what to do."),
    "web_agent": AgentSpec(
        "web_agent", "Searches the live web (DuckDuckGo) and answers with sources", web_agent,
        usage="Use for current events, prices, recent releases, 'latest'/'today'/'current' questions, or anything that needs a citable source."),
    "summarizer_agent": AgentSpec(
        "summarizer_agent", "Condenses output of earlier steps or supplied text into a short summary", summarizer_agent,
        usage="Use only as a LATER step in a plan, to shrink the output of research_agent/web_agent/code_agent - never as the only step."),
    "verifier_agent": AgentSpec(
        "verifier_agent", "Reviews another agent's output for bugs/errors (depends on that step)", verifier_agent,
        usage="Use only as an extra step after code_agent or math_agent when the user asked for something to be checked or is high-stakes."),
}


def describe() -> str:
    return "\n".join(f"- {a.name}: {a.description}. When to use: {a.usage}" for a in AGENTS.values())
