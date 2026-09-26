"""Input Normalizer.

Sits between the input adapters (AssemblyAI / free STT / typed text) and the brain.
It never throws the original text away and never decides "error" for input that is
simply casual or unclear - it only *describes* the input.
"""
from __future__ import annotations

import re
import unicodedata

from ..models import NormalizedRequest

# ------------------------------------------------------------------ scripts
_GU = re.compile(r"[\u0A80-\u0AFF]")
_DEV = re.compile(r"[\u0900-\u097F]")
_LAT = re.compile(r"[A-Za-z]")

# Romanized Gujarati / Hindi marker words (typed with an English keyboard).
_GU_ROMAN = {
    "che", "chhe", "chu", "chho", "cho", "mare", "mane", "tame", "tamne", "tamari", "mari", "maru", "aapo", "aapi",
    "javu", "jaau", "jau", "aavu", "aavo", "kem", "shu", "su", "kevi", "kya", "ane", "pan", "hu", "amne", "ame",
    "banavo", "banavi", "banavu", "lakho", "kaho", "kahi", "karo", "kari", "kariye", "joiye", "joie", "nathi",
    "aa", "aane", "aama", "ema", "ene", "tya", "ahi", "haa", "ha", "na", "majama", "saras", "bahu", "thodu",
}
_HI_ROMAN = {
    "hai", "hain", "mujhe", "kya", "kaise", "mera", "meri", "nahi", "nahin", "batao", "chahiye", "aap", "tum",
    "karo", "kijiye", "kaun", "kyun", "kyu", "abhi", "bahut", "accha", "acha", "theek", "ghar", "jana", "jaana",
}

# ---------------------------------------------------------------- vocab
_QUESTION_START = re.compile(
    r"^\s*(what|why|how|when|where|who|whom|whose|which|is|are|am|was|were|can|could|will|would|should|do|does|did|"
    r"kem|shu|kon|kyare|kevi rite|kaun|kya|kaise|kyun|"
    r"કેમ|શું|કોણ|ક્યારે|કેવી રીતે|ક્યાં|क्या|कैसे|क्यों|कौन|कब|कहाँ)\b",
    re.I,
)
_COMMAND_WORDS = re.compile(
    r"\b(create|build|make|write|add|fix|solve|generate|summari[sz]e|deploy|implement|design|draw|convert|calculate|"
    r"compute|find|list|show|give|develop|code|refactor|debug|translate|compare|plan|test|run|edit|change|update|"
    r"remove|delete|use|modify|explain|tell|rename|"
    r"banavo|banavi|banav|lakho|lakh|karo|kar|aapo|batavo|kaho|"
    r"બનાવ|લખ|કર|આપ|સમજાવ|બતાવ|ઉકેલ|ઉમેર|બદલ|સુધાર|ચલાવ|बनाओ|लिखो|करो|बताओ|समझाओ|हल|जोड़ो|बदलो)\w*",
    re.I,
)
_GREETING = re.compile(
    r"^\s*(hi|hello|hey|hii+|yo|good (morning|afternoon|evening|night)|thanks|thank you|thx|ok|okay|bye|namaste|"
    r"kem cho|kem chho|kemcho|majama|jai shree krishna|જય શ્રી કૃષ્ણ|કેમ છો|નમસ્તે|आभार|धन्यवाद|नमस्ते)\b",
    re.I,
)
_STATEMENT_FEELING = re.compile(
    r"\b(i want|i am|i'm|i feel|i need|i have|i like|i love|i hate|i'm tired|i wanna|"
    r"mare|mane|hu\b|મારે|મને|હું|मुझे|मैं)",
    re.I,
)
_CONNECTOR_END = re.compile(r"(\b(and|with|to|for|of|in|on|the|a|an|but|or|then|ane|pan|ke|ni|nu|na)|,|\.\.\.|…)\s*$", re.I)

_FOLLOWUP_VERB = re.compile(
    r"^\s*(please\s+)?(make|change|add|fix|update|remove|delete|use|edit|modify|improve|extend|continue|rename|rewrite|"
    r"optimi[sz]e|refactor|now|also|and then|ઉમેર|બદલ|સુધાર)",
    re.I,
)

_READ_ALOUD = re.compile(
    r"(read|say|speak|recite|narrate)\b.{0,30}\b(aloud|out loud|loud|out)\b|"
    r"\bread (the |that |this |my |it |out )?(code|program|function|script)\b|"
    r"\bcode (vanch|bol)\w*|વાંચ|बोलकर पढ़",
    re.I,
)

_REFERENCE = re.compile(
    r"\b(add|make|change|fix|update|use|edit|modify|improve|extend|continue|run|remove|delete|rewrite|optimi[sz]e|"
    r"explain|convert|translate|save|show)\b.{0,60}?"
    r"\b(it|this|that|these|those|them|previous|above|same|earlier|last one|before)\b"
    r"|\b(the )?(previous|last|earlier|above) (code|answer|result|project|one|response|program|file|function|equation)\b"
    r"|\buse the previous\b|(એમાં|એને|આમાં|આને|આનું|ઉપરનું|પહેલાનું|इसमें|इसे|पिछला)"
    r"|\b(aama|ema|ene|aane)\b.{0,40}\b(add|kar|karo|umero|nakh|badlo)\w*",
    re.I,
)

_CODE_KEYWORDS = re.compile(
    r"(^|\n)\s*(def |class |import |from \w+ import |#include|function\s+\w+\s*\(|const |let |var |public (static )?\w+|"
    r"for\s*\(|while\s*\(|if\s*\(.+\)\s*\{|print\(|console\.log|return\b.*;|SELECT .+ FROM|<\w+[^>]*>.*</\w+>)",
    re.I,
)
_CODE_CHARS = re.compile(r"[{};]|=>|::|\)\s*:\s*$", re.M)

_MATH_PATTERNS = [
    re.compile(r"\d\s*[\+\-\*/\^×÷]\s*[\dA-Za-z(]"),
    re.compile(r"[A-Za-z]\s*[\^²³]\s*\d?|[A-Za-z]\d?\s*=\s*[-\d(]"),
    re.compile(r"[√∫∑∏π±≤≥≠∞]|\\(frac|sqrt|sum|int|pm|times|cdot|lim|sin|cos|tan|log)\b"),
    re.compile(r"\b(sin|cos|tan|log|ln|sqrt|exp)\s*\("),
    re.compile(r"\d+\s*%\s*of\s*\d+", re.I),
    re.compile(r"\b(solve|equation|derivative|differentiate|integral|integrate|factori[sz]e|simplify|expand|limit of|"
               r"quadratic|matrix|determinant)\b", re.I),
    re.compile(r"(સમીકરણ|ઉકેલો|ગણતરી|समीकरण|हल करो|अवकलज)"),
]


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    # keep newlines (needed for pasted code) but collapse runs of spaces/tabs and blank lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_language(text: str, hint: str = "auto") -> tuple[str, bool, str]:
    gu = len(_GU.findall(text))
    dev = len(_DEV.findall(text))
    lat = len(_LAT.findall(text))
    total = gu + dev + lat

    if total == 0:
        lang = hint if hint in {"en", "gu", "hi"} else "und"
        return lang, False, "latin"
    if gu and gu >= max(dev, 1) and gu / total > 0.2:
        return "gu", False, "gujarati"
    if dev and dev / total > 0.2:
        return "hi", False, "devanagari"

    words = re.findall(r"[a-z']+", text.lower())
    gu_hits = sum(1 for w in words if w in _GU_ROMAN)
    hi_hits = sum(1 for w in words if w in _HI_ROMAN)
    # single-word markers like "aa", "na", "ha" are too weak alone
    strong_gu = {"che", "chhe", "chu", "mare", "mane", "javu", "kem", "banavo", "banavi", "nathi", "tamne", "joiye", "cho"}
    strong_hi = {"hai", "hain", "mujhe", "kya", "kaise", "nahi", "chahiye", "batao"}
    gu_strong = sum(1 for w in words if w in strong_gu)
    hi_strong = sum(1 for w in words if w in strong_hi)

    if gu_strong and gu_hits >= hi_hits and gu_hits >= 2:
        return "gu", True, "latin"
    if hi_strong and hi_hits > gu_hits and hi_hits >= 2:
        return "hi", True, "latin"
    if gu_strong >= 1 and len(words) <= 4 and gu_hits >= hi_hits:
        return "gu", True, "latin"
    if hint in {"gu", "hi"} and lat == 0:
        return hint, False, "latin"
    return "en", False, "latin"


def _looks_like_code(text: str) -> bool:
    if "```" in text:
        return True
    lines = [l for l in text.split("\n") if l.strip()]
    kw = len(_CODE_KEYWORDS.findall(text))
    chars = len(_CODE_CHARS.findall(text))
    if kw >= 2 or (kw >= 1 and chars >= 1 and len(lines) >= 2):
        return True
    return len(lines) >= 3 and chars >= 3


def _looks_like_math(text: str) -> bool:
    return any(p.search(text) for p in _MATH_PATTERNS)


def normalize(
    text: str,
    *,
    modality: str = "text",
    mode: str = "personal",
    language_hint: str = "auto",
    output_pref: str = "auto",
) -> NormalizedRequest:
    original = text if text is not None else ""
    cleaned = _clean(original)
    lang, romanized, script = _detect_language(cleaned, language_hint)

    has_code = _looks_like_code(cleaned)
    has_math = (not has_code) and _looks_like_math(cleaned)
    if has_code and re.search(r"\b(solve|equation|derivative|integral)\b", cleaned, re.I):
        has_math = True

    words = re.findall(r"[\w'\u0A80-\u0AFF\u0900-\u097F]+", cleaned)
    is_greeting = bool(_GREETING.match(cleaned)) and len(words) <= 6
    is_question = (not is_greeting) and bool(cleaned.endswith("?") or cleaned.endswith("？") or _QUESTION_START.match(cleaned))
    is_command = bool(_COMMAND_WORDS.search(cleaned)) and not cleaned.endswith("?") and not is_greeting
    is_statement_feeling = bool(_STATEMENT_FEELING.search(cleaned)) and not is_command and not is_question
    is_conversational = is_greeting or is_statement_feeling or (not is_command and not is_question and not has_code and not has_math and len(words) <= 12)

    has_reference = bool(_REFERENCE.search(cleaned))
    reference_hint = None
    if has_reference:
        low = cleaned.lower()
        if re.search(r"code|project|app|website|program|function|script|button|file|class|કોડ|प्रोजेक्ट", low):
            reference_hint = "code"
        elif re.search(r"equation|answer|result|solution|sum|समीकरण|સમીકરણ", low):
            reference_hint = "math"
        else:
            reference_hint = "any"

    read_aloud = bool(_READ_ALOUD.search(cleaned))
    followup_style = bool(_FOLLOWUP_VERB.match(cleaned)) and not re.search(r"\b(create|build|write|generate|new)\b", cleaned, re.I)

    is_incomplete = False
    reason = None
    if not cleaned or not re.search(r"[\w\u0A80-\u0AFF\u0900-\u097F]", cleaned):
        is_incomplete = True
        reason = "empty"
    elif _CONNECTOR_END.search(cleaned) and len(words) >= 2 and not has_code:
        is_incomplete = True
        reason = "trailing_connector"
    elif len(words) == 1 and not is_greeting and not has_math and not has_code and len(cleaned) <= 3:
        is_incomplete = True
        reason = "too_short"

    needs_clarification = is_incomplete and reason in {"empty", "too_short", "trailing_connector"}

    if needs_clarification:
        intent = "unclear"
    elif has_code or (is_command and not is_greeting):
        intent = "task"
    elif is_question or has_math:
        intent = "question"
    elif is_conversational:
        intent = "conversation"
    else:
        intent = "statement"

    return NormalizedRequest(
        original_text=original,
        text=cleaned,
        language=lang,  # type: ignore[arg-type]
        romanized=romanized,
        script=script,
        modality="voice" if modality == "voice" else "text",
        mode=mode,
        output_pref=output_pref,
        has_code=has_code,
        has_math=has_math,
        is_question=is_question,
        is_command=is_command,
        is_conversational=is_conversational,
        is_incomplete=is_incomplete,
        needs_clarification=needs_clarification,
        clarification_reason=reason,
        has_reference=has_reference,
        reference_hint=reference_hint,
        read_aloud=read_aloud,
        followup_style=followup_style,
        intent_hint=intent,  # type: ignore[arg-type]
    )
