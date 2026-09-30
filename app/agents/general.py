"""General conversation agent + the offline fallback.

"mare ghare javu che" is NOT an error. It is casual/travel-ish/unclear input, and
this agent is where such input lands: it answers naturally, or asks one short
clarifying question. With no AI provider configured it still replies gracefully.
"""
from __future__ import annotations

import re

from ..errors import LLMUnavailable
from ..models import AgentResult, Segment
from ..response.parser import markdown_to_segments
from .base import AgentContext

SYSTEM = """You are Astra, a friendly multilingual assistant inside a voice-first agent system.
Rules:
- Casual statements such as "I want to go home" are normal conversation. Never treat them as errors.
- If the intent is genuinely unclear, ask ONE short clarifying question (offer 2-3 concrete options).
- If it is a plain question, just answer it briefly and correctly.
- Never claim you ran tools, searched the web or opened apps. You cannot.
- Put code in fenced blocks with the language, and equations in $$...$$ blocks.
- Be concise: 1-4 sentences for conversation."""

_GREETING = re.compile(r"^\s*(hi+|hello|hey|yo|namaste|kem cho|kem chho|kemcho|જય શ્રી કૃષ્ણ|કેમ છો|નમસ્તે|नमस्ते)\b", re.I)
_HOME = re.compile(r"(\bhome\b|\bghare\b|\bghar\b|ઘરે|ઘર\b|\bघर\b)", re.I)
_THANKS = re.compile(r"\b(thanks|thank you|thx|aabhar|આભાર|धन्यवाद)\b", re.I)

_T = {
    "greet": {
        "en": "Hello! I'm Astra. Ask me something, give me a task, or just talk.",
        "gu": "નમસ્તે! હું Astra છું. કંઈક પૂછો, કામ આપો, કે બસ વાત કરો.",
        "hi": "नमस्ते! मैं Astra हूँ। कुछ पूछिए, काम दीजिए, या बस बात कीजिए।",
    },
    "thanks": {"en": "You're welcome!", "gu": "આભાર! બીજું કંઈ જોઈએ તો કહેજો.", "hi": "आपका स्वागत है! और कुछ चाहिए तो बताइए।"},
    "home": {
        "en": "Heading home? Do you want route or travel options, or something else?",
        "gu": "ઘરે જવું છે? રસ્તો કે ટ્રાવેલ ઓપ્શન જોઈએ છે, કે બીજું કંઈક?",
        "hi": "घर जाना है? रास्ता या ट्रैवल ऑप्शन चाहिए, या कुछ और?",
    },
    "ack": {
        "en": "Got it. What would you like to do next?",
        "gu": "સમજાયું. હવે તમે શું કરવા માંગો છો?",
        "hi": "समझ गया। अब आप क्या करना चाहेंगे?",
    },
}


def _lang(ctx: AgentContext) -> str:
    return ctx.request.language if ctx.request.language in {"gu", "hi"} else "en"


def offline_reply(task: str, ctx: AgentContext) -> str | None:
    """Graceful reply for casual input when no AI provider is available. None = needs a real model."""
    lang = _lang(ctx)
    if _GREETING.match(task):
        return _T["greet"][lang]
    if _THANKS.search(task):
        return _T["thanks"][lang]
    if _HOME.search(task) and ctx.request.intent_hint in {"conversation", "statement"}:
        return _T["home"][lang]
    if ctx.request.intent_hint in {"conversation", "statement"}:
        return _T["ack"][lang]
    return None


async def general_agent(task: str, ctx: AgentContext) -> AgentResult:
    if not ctx.router.available():
        text = offline_reply(task, ctx)
        if text is None:
            raise LLMUnavailable("I need an AI provider to answer that. Add GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY.")
        return AgentResult(agent="general_agent", status="success", segments=[Segment(type="text", content=text)], data={"offline": True})

    parts = [f"User message: {task}"]
    context = ctx.context.render(3500)
    if context:
        parts.append(context)
    dep = ctx.dep_text()
    if dep:
        parts.append("Input from earlier steps:\n" + dep)
    if ctx.feedback:
        parts.append("Fix this problem with your previous answer: " + ctx.feedback)
    system = SYSTEM + "\n" + ctx.language_rule() + ctx.voice_rule()
    text = await ctx.router.complete(system, [{"role": "user", "content": "\n\n".join(parts)}], temperature=0.5, max_tokens=1200)
    segs = markdown_to_segments(text) or [Segment(type="text", content=text.strip())]
    return AgentResult(agent="general_agent", status="success", segments=segs, data={"provider": ctx.router.last_used})
