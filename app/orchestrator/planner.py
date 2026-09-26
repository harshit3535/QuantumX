"""Planner.

Free-tier APIs allow only a handful of requests per minute, so the planner is
"cheap path first":

  1. rules       -> clarification, "read the code aloud", unresolved "it"       (0 LLM calls)
  2. heuristics  -> greeting/casual -> general, math -> math, code -> code       (0 LLM calls)
  3. LLM planner -> only for genuinely multi-step / multi-domain requests        (1 LLM call)

Every LLM plan is validated and sanitized; if it is broken we fall back to (2).
"""
from __future__ import annotations

import logging
import re

from ..agents.registry import AGENTS, describe
from ..llm.jsonutil import extract_json
from ..llm.router import LLMRouter
from ..models import AgentResult, ContextBundle, NormalizedRequest, Plan, PlanStep

log = logging.getLogger("nexus.planner")

MAX_STEPS = 5

_CODE_WORDS = re.compile(
    r"\b(python|javascript|typescript|java|c\+\+|cpp|html|css|sql|bash|react|flask|fastapi|django|node|api|script|function|"
    r"class|program|code|coding|website|web ?page|app|application|algorithm|calculator|game|bot|login|database|"
    r"કોડ|પ્રોગ્રામ|वेबसाइट|कोड)\b|`{3}",
    re.I,
)
_LIVE_WORDS = re.compile(
    r"\b(latest|current(ly)?|today|recent(ly)?|now|news|price of|score of|weather|who is the (current|new)|"
    r"this (week|month|year)|2025|2026|(stock|share) price|release date|"
    r"અત્યારે|તાજેતર|હાલ|आज|अभी|हाल)\b", re.I,
)
_RESEARCH_WORDS = re.compile(r"\b(research|compare|comparison|pros and cons|history of|difference between|versus|vs\.?)\b", re.I)
_SUMMARY_WORDS = re.compile(r"\b(summari[sz]e|summary|shorten|tl;?dr|in brief|સારાંશ|सारांश)\b", re.I)
_MULTI = re.compile(
    r"\b(and then|then|after that|afterwards|also|as well as|and (?:then )?(?:deploy|test|summari[sz]e|verify|explain|document|compare|"
    r"solve|write|build|create))\b",
    re.I,
)
_STEP_HINT = re.compile(r"\b(research|summari[sz]e|compare|deploy|test|verify|document|explain|solve|build|write)\b", re.I)

_CLARIFY = {
    "empty": {"en": "I didn't catch anything. Could you say that again?", "gu": "મને કંઈ સંભળાયું નહીં. ફરી કહેશો?", "hi": "मुझे कुछ सुनाई नहीं दिया। क्या आप फिर से कह सकते हैं?"},
    "too_short": {"en": "Could you tell me a bit more about what you need?", "gu": "તમને શું જોઈએ છે એ થોડું વધારે કહેશો?", "hi": "आपको क्या चाहिए, थोड़ा और बताएँगे?"},
    "trailing_connector": {"en": "It sounds like your sentence was cut off. What did you want to add?", "gu": "લાગે છે કે વાક્ય અધૂરું રહી ગયું. બીજું શું કહેવું હતું?", "hi": "लगता है वाक्य अधूरा रह गया। आप और क्या कहना चाहते थे?"},
    "reference": {"en": "Which project or result do you mean? Tell me what to work on first.", "gu": "તમે કયા પ્રોજેક્ટ કે પરિણામની વાત કરો છો? પહેલા કહો કે શું બનાવવું છે.", "hi": "आप किस प्रोजेक्ट या नतीजे की बात कर रहे हैं? पहले बताइए क्या बनाना है।"},
    "no_code": {"en": "There is no code to read yet. Ask me to write something first.", "gu": "હજી વાંચવા માટે કોઈ કોડ નથી. પહેલા કંઈક લખવાનું કહો.", "hi": "अभी पढ़ने के लिए कोई कोड नहीं है। पहले कुछ लिखने को कहिए।"},
}


def _lang(req: NormalizedRequest) -> str:
    return req.language if req.language in {"gu", "hi"} else "en"


def clarification_plan(req: NormalizedRequest, key: str) -> Plan:
    q = _CLARIFY[key][_lang(req)]
    return Plan(kind="unclear", goal=req.text[:200], confidence=0.9, needs_clarification=True, clarification_question=q, source="rule")


def is_complex(req: NormalizedRequest) -> bool:
    text = req.text
    words = len(text.split())
    if _MULTI.search(text) and len(_STEP_HINT.findall(text)) >= 2:
        return True
    if req.is_command and words > 30:
        return True
    domains = sum([bool(_CODE_WORDS.search(text)), req.has_math, bool(_RESEARCH_WORDS.search(text)), bool(_SUMMARY_WORDS.search(text))])
    return domains >= 2


# ---------------------------------------------------------------- heuristics
def heuristic_plan(req: NormalizedRequest, ctx: ContextBundle) -> Plan:
    text = req.text
    goal = text[:300]
    referent_type = (ctx.referent or {}).get("type")

    def one(agent: str, kind: str, conf: float, **kw) -> Plan:
        return Plan(kind=kind, goal=goal, confidence=conf, steps=[PlanStep(id=1, agent=agent, task=text, expected_output=kw.get("out", ""))], source="heuristic")

    # follow-up on earlier work
    if ctx.referent and (req.has_reference or req.followup_style):
        if referent_type == "code":
            return one("code_agent", "task", 0.85)
        if referent_type == "math":
            return one("math_agent", "question", 0.7)

    if req.has_code and not req.has_math and req.intent_hint == "task":
        return one("code_agent", "task", 0.7)

    # a bare mention of a language name in a question ("what is python used for", "latest python news")
    # must not hijack routing - only an explicit build/write/fix command (or code already present) means code_agent
    code_intent = bool(_CODE_WORDS.search(text)) and (req.is_command or req.intent_hint == "task")
    if req.has_math and not code_intent:
        return one("math_agent", "question", 0.85)
    if code_intent:
        return one("code_agent", "task", 0.85)
    if _SUMMARY_WORDS.search(text):
        return one("summarizer_agent", "task", 0.75)
    if _LIVE_WORDS.search(text) and (req.is_question or req.is_command):
        return one("web_agent", "question", 0.75)
    if _RESEARCH_WORDS.search(text) and (req.is_question or req.is_command):
        return one("research_agent", "question", 0.7)
    if req.intent_hint in {"conversation", "statement"}:
        return one("general_agent", "conversation", 0.9)
    return one("general_agent", "question" if req.is_question else "task", 0.6)


# ------------------------------------------------------------------ sanitize
def sanitize_plan(plan: Plan) -> Plan:
    """Make an untrusted plan safe to execute: known agents, valid ids, no cycles, bounded size."""
    steps: list[PlanStep] = []
    seen: set[int] = set()
    for s in plan.steps[:MAX_STEPS]:
        if s.agent not in AGENTS or s.id in seen or not s.task.strip():
            continue
        seen.add(s.id)
        steps.append(s)
    ids = {s.id for s in steps}
    order = {s.id: i for i, s in enumerate(steps)}
    for s in steps:
        # only depend on existing, *earlier* steps -> no cycles possible
        s.depends_on = sorted({d for d in s.depends_on if d in ids and d != s.id and order[d] < order[s.id]})
    plan.steps = steps
    if not steps and not plan.needs_clarification and plan.kind not in {"unsupported", "unclear"}:
        plan.steps = [PlanStep(id=1, agent="general_agent", task=plan.goal or "Respond to the user.")]
    return plan


PLANNER_SYSTEM = """You are the planner of a multi-agent system. Turn the user's request into the SMALLEST plan that fully achieves the goal.
Available agents:
{agents}

Rules:
- Use only the agents above. Never invent agents or tools.
- One step is best when one agent can do it. Use several only for genuinely different skills.
- depends_on lists the ids of earlier steps whose output this step needs. Independent steps have empty depends_on (they run in parallel).
- Casual talk ("I want to go home") is a conversation for general_agent, not an error.
- If the request is impossible here (needs real-world actions such as booking, deploying to a server, opening apps), set kind "unsupported" and explain briefly in clarification_question, then offer what you CAN do.
- If the intent is really unclear, set needs_clarification true with ONE short question.
- Set may_need_followup true only if the result may need another round (e.g. build then test).
- Write clarification_question in the user's language ({lang}).
Return JSON only:
{{"kind":"task|question|conversation|partial|unclear|unsupported","goal":"...","confidence":0.0,
 "steps":[{{"id":1,"agent":"...","task":"...","depends_on":[],"optional":false,"expected_output":"..."}}],
 "needs_clarification":false,"clarification_question":null,"may_need_followup":false}}"""


class Planner:
    def __init__(self, router: LLMRouter):
        self.router = router

    async def plan(self, req: NormalizedRequest, ctx: ContextBundle) -> Plan:
        # ---- 1. rules
        if req.needs_clarification:
            return clarification_plan(req, req.clarification_reason or "too_short")
        if ctx.reference_unresolved:
            return clarification_plan(req, "reference")
        if req.read_aloud:
            if ctx.referent and ctx.referent.get("type") == "code":
                return Plan(kind="task", goal="Read the previous code aloud", confidence=0.95, direct_action="read_code_aloud", source="rule")
            code_exists = any(a.get("type") == "code" for a in ctx.task_state.get("artifacts", []))
            if not code_exists:
                return clarification_plan(req, "no_code")

        # ---- 2/3. heuristic, or LLM for complex requests
        fallback = heuristic_plan(req, ctx)
        if is_complex(req) and self.router.available():
            try:
                return await self._llm_plan(req, ctx, fallback)
            except Exception as exc:                       # bad JSON, provider down, ... -> cheap path still works
                log.warning("LLM planner failed (%s); using heuristic plan", exc)
        return fallback

    async def _llm_plan(self, req: NormalizedRequest, ctx: ContextBundle, fallback: Plan) -> Plan:
        lang = {"gu": "Gujarati", "hi": "Hindi"}.get(req.language, "English")
        system = PLANNER_SYSTEM.format(agents=describe(), lang=lang)
        user = f"User request: {req.text}\n\nSignals: code={req.has_code}, math={req.has_math}, follow_up={req.followup_style}"
        rendered = ctx.render(2500)
        if rendered:
            user += "\n\n" + rendered
        raw = await self.router.complete(system, [{"role": "user", "content": user}], json_mode=True, temperature=0.1, max_tokens=900)
        obj = extract_json(raw)
        if not isinstance(obj, dict):
            raise ValueError("plan is not an object")
        obj.setdefault("goal", req.text[:300])
        plan = Plan.model_validate({**obj, "source": "llm"})
        plan = sanitize_plan(plan)
        if plan.kind == "unsupported" and not plan.clarification_question:
            plan.clarification_question = "I can't do that here, but I can help with questions, math, code and writing."
        if plan.needs_clarification and not plan.clarification_question:
            plan.needs_clarification = False
        return plan

    # ------------------------------------------------------------- follow-up
    async def next_steps(self, req: NormalizedRequest, plan: Plan, results: dict[int, AgentResult], next_id: int) -> tuple[bool, list[PlanStep], str]:
        """Goal check. Returns (done, extra_steps, reason). Only called when needed (see AOB)."""
        summary = "\n".join(
            f"- step {i} {r.agent}: {r.status}" + (f" ({r.error.message})" if r.error else "") + (f"\n  {r.brief(300)}" if r.status == "success" else "")
            for i, r in sorted(results.items())
        )
        system = ("You check whether a goal has been achieved. If not, propose at most 2 extra steps using only these agents:\n"
                  + describe() + '\nReply JSON only: {"done":true|false,"reason":"...","next_steps":[{"agent":"...","task":"...","depends_on":[]}]}')
        user = f"Goal: {plan.goal}\nOriginal request: {req.text}\n\nResults so far:\n{summary}"
        raw = await self.router.complete(system, [{"role": "user", "content": user}], json_mode=True, temperature=0.0, max_tokens=500)
        obj = extract_json(raw)
        done = bool(obj.get("done", True))
        reason = str(obj.get("reason", ""))
        steps: list[PlanStep] = []
        if not done:
            for k, s in enumerate(obj.get("next_steps", [])[:2]):
                deps = [d for d in s.get("depends_on", []) if isinstance(d, int) and d in results]
                steps.append(PlanStep(id=next_id + k, agent=str(s.get("agent", "")), task=str(s.get("task", "")), depends_on=deps))
            steps = [s for s in steps if s.agent in AGENTS and s.task.strip()]
        return (done or not steps), steps, reason
