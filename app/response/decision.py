"""Output Decision Layer.

Decides, for one finished response, whether to speak it, show it, or both, and
builds the *spoken form* (math verbalized, code summarized, markdown stripped).
The actual voice engine stays behind `tts_provider`, so it can change without
touching the brain.
"""
from __future__ import annotations

import re

from ..models import NormalizedRequest, OutputDecision, Segment, StructuredResponse
from ..modes import ModeConfig
from .verbalizer import code_summary_speech, code_to_speech, math_to_speech, text_to_speech

MAX_SPOKEN_CHARS = 700

_GU = re.compile(r"[\u0A80-\u0AFF]")
_DEV = re.compile(r"[\u0900-\u097F]")

_ON_SCREEN = {
    "en": "The full answer is on screen.",
    "gu": "પૂરો જવાબ સ્ક્રીન પર છે.",
    "hi": "पूरा जवाब स्क्रीन पर है।",
}
_TABLE = {
    "en": "A table with {n} rows is shown on screen.",
    "gu": "{n} હરોળની ટેબલ સ્ક્રીન પર બતાવી છે.",
    "hi": "{n} पंक्तियों की तालिका स्क्रीन पर दिखाई गई है।",
}


def speech_language(text: str, fallback: str = "en") -> str:
    """Language of the *text that will be spoken* (script decides, so romanized text is not sent to a Gujarati voice)."""
    if _GU.search(text):
        return "gu"
    if _DEV.search(text):
        return "hi"
    return "en" if fallback not in {"gu", "hi"} else "en"


_LOCALE = {"en": "en-US", "gu": "gu-IN", "hi": "hi-IN"}


def _lang_of_segments(segments: list[Segment], req_lang: str) -> str:
    joined = " ".join(s.content for s in segments if s.type in {"text", "warning", "error"})
    if not joined.strip():                      # math/code only: follow the user's language
        return req_lang if req_lang in {"gu", "hi"} else "en"
    return speech_language(joined, req_lang)


def build_speech(response: StructuredResponse, lang: str, *, on_screen: bool = True, read_code_aloud: bool = False) -> str:
    pieces: list[str] = []
    code_segments = [s for s in response.segments if s.type == "code"]
    summarized_code = False

    for seg in response.segments:
        if seg.type in {"text", "warning", "error"}:
            t = text_to_speech(seg.content, lang, limit=MAX_SPOKEN_CHARS)
            if t:
                pieces.append(t)
        elif seg.type == "list":
            items = [text_to_speech(i, lang, limit=200) for i in seg.items[:6]]
            pieces.append(" ".join(i if re.search(r"[.!?।]$", i) else i + "." for i in items if i))
        elif seg.type == "math":
            m = seg.speak or math_to_speech(seg.content, lang)
            if m:
                pieces.append(m + ("." if not m.endswith((".", "।")) else ""))
        elif seg.type == "code":
            if read_code_aloud:
                pieces.append(code_to_speech(seg.content))
            elif not summarized_code:
                if len(code_segments) > 2:
                    pieces.append({"en": f"I created {len(code_segments)} code files. The complete code is displayed on screen."}.get(lang, code_summary_speech(seg, lang, on_screen)))
                else:
                    pieces.append(code_summary_speech(seg, lang, on_screen))
                summarized_code = len(code_segments) > 2 or summarized_code
        elif seg.type == "table":
            pieces.append(_TABLE.get(lang, _TABLE["en"]).format(n=len(seg.rows)))
        elif seg.type in {"link", "image", "file"}:
            pass

    text = " ".join(p.strip() for p in pieces if p and p.strip())
    if not read_code_aloud and len(text) > MAX_SPOKEN_CHARS * 1.3:
        cut = text[:MAX_SPOKEN_CHARS]
        ends = list(re.finditer(r"[.!?।]\s", cut))
        text = (cut[: ends[-1].end()] if ends else cut).strip()
        if on_screen:
            text += " " + _ON_SCREEN.get(lang, _ON_SCREEN["en"])
    return text


def decide_output(cfg: ModeConfig, req: NormalizedRequest, response: StructuredResponse) -> OutputDecision:
    pref = cfg.output_pref
    if pref == "voice" or pref == "both":
        speak, reason = True, f"user asked for {pref} output"
    elif pref == "text":
        speak, reason = False, "user asked for text output"
    elif cfg.mode == "hackathon":
        speak, reason = True, "hackathon mode is voice-first"
    elif req.modality == "voice":
        speak, reason = True, "personal mode: voice in -> voice out"
    else:
        speak, reason = False, "personal mode: text in -> text out"

    read_aloud = bool(req.read_aloud and any(s.type == "code" for s in response.segments))
    lang = _lang_of_segments(response.segments, req.language)
    speech = build_speech(response, lang, on_screen=cfg.can_display, read_code_aloud=read_aloud) if speak else ""
    if speak and read_aloud:
        reason += "; reading code verbatim on request"
    elif speak and any(s.type == "code" for s in response.segments):
        reason += "; code summarized instead of read"
    return OutputDecision(
        display=cfg.can_display, speak=bool(speak and speech), speech_text=speech, speech_lang=_LOCALE.get(lang, "en-US"),
        tts_provider=cfg.tts_provider, reason=reason, read_code_aloud=read_aloud,
    )
