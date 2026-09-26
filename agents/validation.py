from __future__ import annotations

import ast

from agents.base import Agent
from core.models import InputEnvelope, ResponseSegment


class ValidationAgent(Agent):
    name = "validation"

    def run(self, task: str, envelope: InputEnvelope, context: str, previous_results: dict[str, str]) -> list[ResponseSegment]:
        coding = previous_results.get("coding", "")
        issues: list[str] = []
        for block in self._extract_code_blocks(coding):
            try:
                ast.parse(block)
            except SyntaxError as exc:
                issues.append(f"Python syntax error: line {exc.lineno}: {exc.msg}")

        if issues:
            self.log("validation: issues detected")
            return [ResponseSegment("warning", "Validation found issues: " + "; ".join(issues))]

        if coding:
            return [ResponseSegment("text", "Validation pass: no obvious Python syntax problems were detected in generated code.")]
        return [ResponseSegment("text", "Validation completed with no code artifact to inspect.")]

    @staticmethod
    def _extract_code_blocks(text: str) -> list[str]:
        import re
        return re.findall(r"```python\s*\n?(.*?)```", text, re.S | re.I)
