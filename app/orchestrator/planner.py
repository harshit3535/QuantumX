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
from .task_director import assign_team

log = logging.getLogger("nexus.planner")

MAX_STEPS = 5

_CODE_WORDS = re.compile(
    r"\b(python|javascript|typescript|java|c\+\+|cpp|html|css|sql|bash|react|flask|fastapi|django|node|api|script|function|"
    r"class|program|code|coding|website|web ?page|app|application|algorithm|calculator|game|bot|login|database|json|regex)\b|`{3}",
    re.I,
)
_CODE_INDIC = re.compile(r"(કોડ|પ્રોગ્રામ|કેલ્ક્યુલેટર|કેલક્યુલેટર|વેબસાઇટ|વેબસાઈટ|એપ|कोड|प्रोग्राम|वेबसाइट|कैलकुलेटर|कैल्कुलेटर|ऐप|एप|banavo.*(app|website|calculator))", re.I)
_BUILD_EN = re.compile(
    r"\b(create|creat|build|make|write|generate|develop|code|implement|fix|debug|refactor|edit|modify|add|remove|update|convert|rewrite|"
    r"design|program|script|deploy|install|optimi[sz]e|correct|complete|finish)\b", re.I,
)
_BUILD_INDIC = re.compile(r"(બનાવ|લખ|ઉમેર|સુધાર|बनाओ|बनाकर|बनाइए|बना दो|बना दें|लिखो|लिखकर|लिखिए|जोड़ो|banavo|banavi|lakho|lakhi)", re.I)
_NOT_CODE = re.compile(r"\b(study plan|roadmap|schedule|essay|poem|story|email|letter|resume|cv|syllabus|timetable|diet plan)\b", re.I)
_STRONG_CODE = re.compile(r"\b(function|script|program|code|app|application|website|web ?page|api|calculator|bot|game|class|algorithm)\b", re.I)
_FIRST_PERSON = re.compile(r"^\s*(?:(?:i|i'm|i am|my|me|we|mare|mane|hu)\b|મારે|મને|હું|મારું|मुझे|मैं|मेरा|मेरी)", re.I)
_LIVE_WORDS = re.compile(
    r"\b(latest|newest|current(ly)?|right now|today|recent(ly)?|news|headlines?|price|cost of|score|weather|forecast|stock|"
    r"exchange rate|who is the (current|new)|this (week|month|year)|2025|2026|release date|trending|happening)\b|"
    r"(આજે|અત્યારે|તાજા|હાલ|હવામાન|સમાચાર|ભાવ|आज|अभी|ताज़ा|ताजा|मौसम|समाचार|कीमत|भाव)",
    re.I,
)
_OPERATOR_WORDS = re.compile(
    r"\b(check|test|diagnose|diagnostic|monitor|is .* up|is .* down|reachable|health check|status of|uptime|responding|http status|server status)\b|"
    r"(ચેક|તપાસ|ડાઉન|ચાલે છે|સ્ટેટસ|હેલ્થ|सर्वर|जांच|डाउन|स्टेटस)", re.I,
)
_URL_HINT = re.compile(r"(?:https?://|\b(?:www\.)?[a-z0-9-]+\.(?:com|net|org|io|ai|dev|app|co|in)\b)", re.I)
_RECEPTIONIST_WORDS = re.compile(r"\b(receptionist|front desk|appointment|book|booking|schedule|availability|available slot|customer call|take a message|callback|business hours|open today|reserve)\b|અપોઇન્ટમેન્ટ|બુક|બુકિંગ|રીસેપ્શન|મેસેજ|स्लॉट|बुकिंग|रिसेप्शन|अपॉइंटमेंट|संदेश", re.I)
_AFFIRM_RE = re.compile(r"\b(yes|yeah|yep|sure|confirm|confirmed|do it|book it|go ahead|okay|ok|haan|હા|બરાબર|हाँ|कर दीजिए)\b", re.I)
_NEGATE_RE = re.compile(r"\b(no|nope|cancel|don’t|do not|stop|not now|નહીં|ના|રદ્દ|नहीं|रद्द)\b", re.I)

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


def _workspace_plan(req: NormalizedRequest, ctx: ContextBundle) -> Plan | None:
    if req.workspace == "receptionist":
        return _receptionist_plan(req, ctx) or Plan(kind="task", goal=req.text[:300], confidence=0.9, mission_type="receptionist", steps=[PlanStep(id=1, agent="receptionist_agent", task=req.text)], source="rule")
    if req.workspace == "floorops":
        return Plan(kind="task", goal=req.text[:300], confidence=0.96, mission_type="incident", steps=[PlanStep(id=1, agent="floorops_agent", task=req.text)], source="rule")
    return None

def _receptionist_plan(req: NormalizedRequest, ctx: ContextBundle) -> Plan | None:
    text = req.text
    state = ctx.task_state or {}
    pending = state.get("pending_action")
    # Keep a multi-turn front-desk conversation in the receptionist agent even when
    # the next user turn is only a bare answer such as "Harshit" or "3 pm".
    if pending and (_AFFIRM_RE.search(text) or _NEGATE_RE.search(text)):
        return Plan(kind="task", goal="Handle pending front-desk action", confidence=0.98, mission_type="receptionist", steps=[PlanStep(id=1, agent="receptionist_agent", task=text)], source="rule")
    if state.get("draft_booking"):
        return Plan(kind="task", goal="Continue front-desk booking", confidence=0.97, mission_type="receptionist", steps=[PlanStep(id=1, agent="receptionist_agent", task=text)], source="rule")
    if not _RECEPTIONIST_WORDS.search(text):
        return None
    return Plan(kind="task", goal=text[:300], confidence=0.94, mission_type="receptionist", steps=[PlanStep(id=1, agent="receptionist_agent", task=text)], source="heuristic")

def _operator_plan(req: NormalizedRequest) -> Plan | None:
    text = req.text
    if not _OPERATOR_WORDS.search(text):
        return None
    if _URL_HINT.search(text):
        return Plan(kind="task", goal=text[:300], confidence=0.9, steps=[PlanStep(id=1, agent="operator_agent", task=text)], mission_type="diagnostic", source="heuristic")
    site_words = re.search(r"\b(my|our|the)\s+(website|site|server|endpoint)\b|(મારી|મારું|મારો)\s+(વેબસાઇટ|સાઇટ|સર્વર)|\b(mera|meri)\s+(website|site|server)\b", text, re.I)
    if site_words:
        lang = _lang(req)
        q = {"en": "What public website URL should I check?", "gu": "કઈ public website URL ચેક કરું?", "hi": "कौन-सा public website URL चेक करूँ?"}[lang]
        return Plan(kind="unclear", goal=text[:200], confidence=0.93, needs_clarification=True, clarification_question=q, source="rule")
    return Plan(kind="task", goal=text[:300], confidence=0.72, steps=[PlanStep(id=1, agent="operator_agent", task=text)], mission_type="diagnostic", source="heuristic")


def heuristic_plan(req: NormalizedRequest, ctx: ContextBundle) -> Plan:
    text = req.text
    goal = text[:300]
    referent_type = (ctx.referent or {}).get("type")
    receptionist = _receptionist_plan(req, ctx)
    if receptionist:
        return receptionist
    operator = _operator_plan(req)
    if operator:
        return operator

    def one(agent: str, kind: str, conf: float, **kw) -> Plan:
        return Plan(kind=kind, goal=goal, confidence=conf, steps=[PlanStep(id=1, agent=agent, task=text, expected_output=kw.get("out", ""))], source="heuristic")

    # follow-up on earlier work
    if ctx.referent and (req.has_reference or req.followup_style):
        if referent_type == "code":
            return one("code_agent", "task", 0.85)
        if referent_type == "math":
            return one("math_agent", "question", 0.7)

    # code that the user pasted means code work, whether they phrase it as a task or a question ("why does this fail?")
    if req.has_code and not req.has_math:
        return one("code_agent", "task", 0.8)

    # only an explicit build/write/fix intent + a code-ish noun means code_agent. A bare mention of a language or
    # framework ("what is python used for", "compare React and Vue") must not hijack routing.
    has_code_noun = bool(_CODE_WORDS.search(text) or _CODE_INDIC.search(text))
    has_build_verb = bool(_BUILD_EN.search(text) or _BUILD_INDIC.search(text))
    code_intent = has_code_noun and has_build_verb
    if code_intent and _NOT_CODE.search(text) and not _STRONG_CODE.search(text):
        code_intent = False                                  # "make a python study plan" is not a program
    if req.has_math and not code_intent:
        return one("math_agent", "question", 0.85)
    if code_intent:
        return one("code_agent", "task", 0.85)

    query_like = req.is_question or req.is_command or not _FIRST_PERSON.search(text)
    if _SUMMARY_WORDS.search(text):
        # summarizing pasted/long material is the summarizer's job; "summarize the history of India" is a topic request
        if len(text) > 280 or ctx.referent:
            return one("summarizer_agent", "task", 0.75)
        return one("research_agent", "question", 0.7)
    if _LIVE_WORDS.search(text) and query_like and not _FIRST_PERSON.search(text):
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
    if any(s.agent == "receptionist_agent" for s in steps):
        plan.mission_type = "receptionist"
    elif any(s.agent == "operator_agent" for s in steps):
        plan.mission_type = "diagnostic"
    elif any(s.agent in {"web_agent", "research_agent"} for s in steps):
        plan.mission_type = "research"
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
- For appointment/front-desk requests, use receptionist_agent. It can check availability, take messages, look up bookings, and propose a booking; booking writes require explicit confirmation.
- If the intent is really unclear, set needs_clarification true with ONE short question.
- Set may_need_followup true only if the result may need another round (e.g. build then test).
- Write clarification_question in the user's language ({lang}).
Return JSON only:
{{"kind":"task|question|conversation|partial|unclear|unsupported","goal":"...","confidence":0.0,
 "steps":[{{"id":1,"agent":"...","task":"...","depends_on":[],"optional":false,"expected_output":"..."}}],
 "needs_clarification":false,"clarification_question":null,"may_need_followup":false,"mission_type":"general"}}"""


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

        # ---- 2. explicit workspace modes win over generic routing.
        workspace = _workspace_plan(req, ctx)
        if workspace:
            return assign_team(req, ctx, sanitize_plan(workspace))

        # ---- 3. explicit UI overrides (Web / Think composer toggles) - skip routing entirely
        if req.force_agent and req.force_agent in AGENTS:
            plan = Plan(kind="task", goal=req.text[:300], confidence=1.0, source="rule",
                       steps=[PlanStep(id=1, agent=req.force_agent, task=req.text, expected_output="")])
            return assign_team(req, ctx, sanitize_plan(plan))

        # ---- 3/4. heuristic, or LLM for complex requests (or "Think" toggle forces it)
        fallback = heuristic_plan(req, ctx)
        if (req.force_think or is_complex(req)) and self.router.available():
            try:
                return assign_team(req, ctx, await self._llm_plan(req, ctx, fallback))
            except Exception as exc:                       # bad JSON, provider down, ... -> cheap path still works
                log.warning("LLM planner failed (%s); using heuristic plan", exc)
        return assign_team(req, ctx, fallback)

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
