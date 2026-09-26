"""Validation of agent output *before* it is accepted (spec section 19).

Deterministic checks first - they are free, instant and do not burn API quota.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field

from ..models import AgentResult, Segment

_PLACEHOLDER = re.compile(r"^\s*(#|//)?\s*(\.\.\.|…|rest of (the )?code|your code here|todo:? implement)\s*$", re.I | re.M)


@dataclass
class ValidationReport:
    ok: bool = True
    issues: list[str] = field(default_factory=list)

    @property
    def feedback(self) -> str:
        return "; ".join(self.issues)


def _balanced(code: str) -> str | None:
    """Very small bracket checker for JS/TS/JSON-like code (ignores strings and comments)."""
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            i = code.find("\n", i)
            if i == -1:
                break
        elif c == "/" and nxt == "*":
            j = code.find("*/", i + 2)
            i = n if j == -1 else j + 1
        elif c in "\"'`":
            q = c
            i += 1
            while i < n and code[i] != q:
                if code[i] == "\\":
                    i += 1
                i += 1
        elif c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack.pop() != pairs[c]:
                return f"unbalanced '{c}'"
        i += 1
    return f"unclosed '{stack[-1]}'" if stack else None


def _check_code(seg: Segment) -> list[str]:
    issues: list[str] = []
    code = seg.content
    lang = (seg.language or "").lower()
    if not code.strip():
        return ["a code block is empty"]
    if _PLACEHOLDER.search(code):
        issues.append("the code contains placeholders like '...' - return the complete code")
    if lang in {"python", "py"}:
        try:
            ast.parse(code)
        except SyntaxError as exc:
            issues.append(f"Python syntax error on line {exc.lineno}: {exc.msg}")
    elif lang == "json":
        try:
            json.loads(code)
        except json.JSONDecodeError as exc:
            issues.append(f"invalid JSON: {exc.msg} (line {exc.lineno})")
    elif lang in {"javascript", "js", "typescript", "ts", "jsx", "tsx", "java", "c", "cpp", "csharp", "go", "rust", "kotlin", "php"}:
        problem = _balanced(code)
        if problem:
            issues.append(f"{lang} code has {problem}")
    return issues


def validate(result: AgentResult) -> ValidationReport:
    rep = ValidationReport()
    if result.status != "success":
        return rep
    if result.agent in {"verifier_agent"}:
        return rep

    if not result.segments:
        rep.ok = False
        rep.issues.append("the agent returned an empty answer")
        return rep

    for seg in result.segments:
        if seg.type == "code":
            rep.issues.extend(_check_code(seg))
        elif seg.type == "math" and not seg.content.strip():
            rep.issues.append("an equation block is empty")

    if result.agent == "math_agent" and result.data.get("verified") is False:
        rep.issues.append("the answer did not pass the substitution check")

    rep.ok = not rep.issues
    return rep
