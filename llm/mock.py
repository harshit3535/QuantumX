from __future__ import annotations

from llm.base import LLMClient


class MockLLM(LLMClient):
    """A deterministic fallback so the architecture is testable without an LLM key."""

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        user = messages[-1]["content"].lower() if messages else ""
        if "return only valid json" in (messages[0]["content"].lower() if messages else ""):
            if any(k in user for k in ("build", "create", "code", "python", "program")):
                return (
                    '{"intent":"coding","clarification_needed":false,'
                    '"clarification_question":"","steps":['
                    '{"agent":"coding","task":"Implement the requested code","depends_on":[]},'
                    '{"agent":"validation","task":"Review the generated code for obvious issues","depends_on":["coding"]}'
                    '],"expected_response_types":["text","code"],"notes":"Use a coding-first plan."}'
                )
            if any(k in user for k in ("solve", "equation", "calculate", "math")):
                return (
                    '{"intent":"math","clarification_needed":false,'
                    '"clarification_question":"","steps":['
                    '{"agent":"math","task":"Solve or explain the mathematical request","depends_on":[]}'
                    '],"expected_response_types":["text","math"],"notes":"Prefer deterministic math when possible."}'
                )
            return (
                '{"intent":"general","clarification_needed":false,'
                '"clarification_question":"","steps":['
                '{"agent":"general","task":"Respond helpfully to the user request","depends_on":[]}'
                '],"expected_response_types":["text"],"notes":"General fallback."}'
            )

        if any(k in user for k in ("calculator", "python")):
            return (
                "Here is a small Python example:\n\n"
                "```python\n"
                "def add(a, b):\n"
                "    return a + b\n"
                "\n"
                "print(add(2, 3))\n"
                "```"
            )
        if any(k in user for k in ("home", "ghar")):
            return "I can help with that. Tell me your starting location and whether you want walking, driving, or public transport."
        return "I received your request. Configure an OpenAI-compatible LLM endpoint for full agent reasoning; v1.0 is running in safe mock mode right now."

    def info(self) -> dict[str, str]:
        return {"provider": "mock", "model": "builtin-fallback"}
