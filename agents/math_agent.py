from __future__ import annotations

import ast
import operator
import re
from fractions import Fraction

from agents.base import Agent
from core.models import InputEnvelope, ResponseSegment
from core.response import ResponseParser


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_calc(expression: str):
    node = ast.parse(expression, mode="eval").body

    def visit(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(n.op)](visit(n.left), visit(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(n.op)](visit(n.operand))
        raise ValueError("Only basic numeric arithmetic is supported by the deterministic calculator.")

    return visit(node)


class MathAgent(Agent):
    name = "math"

    def _deterministic(self, text: str):
        cleaned = text.lower().replace("what is", "").replace("calculate", "").replace("=", "").strip()
        if re.fullmatch(r"[0-9+\-*/().%\s]+", cleaned):
            return safe_calc(cleaned)
        return None

    def run(self, task: str, envelope: InputEnvelope, context: str, previous_results: dict[str, str]) -> list[ResponseSegment]:
        deterministic = None
        try:
            deterministic = self._deterministic(envelope.text)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
            deterministic = None

        if deterministic is not None:
            return [
                ResponseSegment("text", f"The result is {deterministic}."),
                ResponseSegment("math", f"{envelope.text.strip()} = {deterministic}"),
            ]

        try:
            import sympy as sp  # optional dependency
            # A conservative equation handler for simple linear/quadratic forms.
            if "=" in envelope.text:
                equation = envelope.text.split("=", 1)
                left = sp.sympify(equation[0].strip())
                right = sp.sympify(equation[1].strip())
                symbols = sorted((left - right).free_symbols, key=lambda s: str(s))
                if symbols:
                    solutions = sp.solve(sp.Eq(left, right), symbols[0])
                    pretty = sp.pretty(solutions)
                    latex = sp.latex(sp.Eq(left, right))
                    return [
                        ResponseSegment("text", f"I solved the equation for {symbols[0]}:"),
                        ResponseSegment("math", latex, metadata={"pretty": pretty}),
                        ResponseSegment("text", f"Solutions: {solutions}"),
                    ]
        except Exception:
            pass

        raw = self._call_llm(
            "You are the Math Agent. Preserve equations exactly and explain steps without inventing calculations. Put display equations on their own lines.",
            f"User request: {envelope.text}\nTask: {task}\nContext:\n{context or '(none)'}",
        )
        return ResponseParser().parse(raw).segments
