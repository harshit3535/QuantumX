from __future__ import annotations

import json
import re
from typing import Any

from ..errors import InvalidAgentOutput


def extract_json(text: str) -> Any:
    """Pull a JSON object/array out of an LLM reply (handles ``` fences and stray prose)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = t.find(opener), t.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise InvalidAgentOutput("The model did not return valid JSON")
