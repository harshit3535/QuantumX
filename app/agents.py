from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from sympy import sympify, solve, Eq

from .config import settings
from .llm import answer_with_llm
from .models import AgentResult


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    handler: Callable[..., Awaitable[AgentResult]]


def _extract_math_candidate(text: str) -> str:
    text = text.strip()
    m = re.search(r"(?:solve|calculate|compute|what is)\s+(.+?)(?:\?|$)", text, flags=re.I)
    if m:
        return m.group(1).strip()
    return text.rstrip("?").strip()


async def general_agent(task: str, context: str = "") -> AgentResult:
    prompt = f"User request: {task}\nRelevant context: {context}\nRespond naturally and briefly. Preserve the user's language."
    text = await answer_with_llm(prompt, "You are the general conversation agent for NEXUS. Do not pretend tools were used.")
    return AgentResult(agent="general_agent", status="success", summary=text, spoken_response=text, data={"text": text}, visual_type="text")


async def math_agent(task: str, context: str = "") -> AgentResult:
    candidate = _extract_math_candidate(task)
    try:
        equation = None
        if "=" in candidate:
            left, right = candidate.split("=", 1)
            equation = Eq(sympify(left.strip()), sympify(right.strip()))
            symbols = sorted(equation.free_symbols, key=lambda x: str(x))
            value = solve(equation, symbols[0]) if symbols else solve(equation)
        else:
            expr = sympify(candidate, evaluate=True)
            value = solve(expr) if getattr(expr, "free_symbols", set()) else expr
        rendered = ", ".join(str(v) for v in value) if isinstance(value, (list, tuple, set)) else str(value)
        spoken = f"The result is {rendered}."
        return AgentResult(
            agent="math_agent", status="success", summary=f"Solved: {rendered}",
            spoken_response=spoken,
            data={"expression": candidate, "result": rendered, "latex": rendered},
            visual_type="math",
        )
    except Exception:
        prompt = f"Solve this mathematical problem carefully and return JSON with result, latex and spoken_response. Problem: {task}"
        raw = await answer_with_llm(prompt, "You are a math specialist. Never hide uncertainty. Use LaTeX for display and natural language for speech.")
        try:
            obj = json.loads(raw)
        except Exception:
            obj = {"result": raw, "latex": raw, "spoken_response": raw}
        return AgentResult(
            agent="math_agent", status="success", summary=str(obj.get("result", raw)),
            spoken_response=str(obj.get("spoken_response", obj.get("result", raw))),
            data={"expression": candidate, "result": obj.get("result", raw), "latex": obj.get("latex", raw)},
            visual_type="math",
        )


async def code_agent(task: str, context: str = "") -> AgentResult:
    prompt = f"Create a correct, concise implementation for this request. Include a short explanation. User request: {task}\nContext: {context}"
    code_text = await answer_with_llm(prompt, "You are a senior coding agent. Return code first, then a concise explanation. Use a single language unless the user asks otherwise.")

    language = "python"
    lower = task.lower()
    if "javascript" in lower or "js" in lower:
        language = "javascript"
    elif "html" in lower:
        language = "html"
    elif "cpp" in lower or "c++" in lower:
        language = "cpp"

    extracted = code_text
    m = re.search(r"```(?:\w+)?\s*(.*?)```", code_text, flags=re.S)
    if m:
        extracted = m.group(1).strip()
        explanation = code_text.replace(m.group(0), "").strip()
    else:
        explanation = ""

    execution = None
    if language == "python" and settings.enable_code_execution:
        execution = await _run_python_safely(extracted)

    spoken = "I generated the requested code."
    if execution and execution.get("status") == "success":
        spoken += " I also ran it successfully."
    elif execution and execution.get("status") == "error":
        spoken += " The local execution found an error, so the verifier should inspect it."

    return AgentResult(
        agent="code_agent", status="success", summary=explanation or "Code generated.",
        spoken_response=spoken,
        data={"language": language, "code": extracted, "explanation": explanation, "execution": execution},
        visual_type="code",
    )


async def summarizer_agent(task: str, context: str = "") -> AgentResult:
    prompt = f"Summarize the user's material/request into a useful concise summary.\nRequest: {task}\nContext: {context}"
    text = await answer_with_llm(prompt, "You are a precise summarizer.")
    return AgentResult(agent="summarizer_agent", status="success", summary=text, spoken_response=text, data={"summary": text}, visual_type="text")


async def research_agent(task: str, context: str = "") -> AgentResult:
    # Intentionally honest: this base project does not claim live web research.
    text = await answer_with_llm(
        f"Explain what would be needed to answer this request accurately, and separate known information from missing live data. Request: {task}\nContext: {context}",
        "You are a research planning agent. Do not invent current facts or pretend that live browsing happened.",
    )
    return AgentResult(agent="research_agent", status="success", summary=text, spoken_response=text, data={"text": text, "live_search": False}, visual_type="text")


async def verifier_agent(task: str, context: str = "") -> AgentResult:
    prompt = f"Verify the following agent output. Identify concrete correctness issues and say PASS or FAIL.\nTask: {task}\nAgent output: {context}"
    text = await answer_with_llm(prompt, "You are a verifier. Do not rewrite unless a correction is needed. Be explicit about uncertainty.")
    status = "success" if "fail" not in text.lower()[:120] else "error"
    return AgentResult(agent="verifier_agent", status=status, summary=text, spoken_response=text, data={"verification": text}, visual_type="text")


async def _run_python_safely(code: str) -> dict[str, Any]:
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"status": "error", "error": f"SyntaxError: {e}"}

    with tempfile.TemporaryDirectory(prefix="nexus_run_") as td:
        file = Path(td) / "main.py"
        file.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["python", str(file)], capture_output=True, text=True,
                timeout=settings.code_exec_timeout, cwd=td,
            )
            return {"status": "success" if proc.returncode == 0 else "error", "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "returncode": proc.returncode}
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Execution timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


AGENTS: dict[str, AgentSpec] = {
    "general_agent": AgentSpec("general_agent", "Conversation and general questions", general_agent),
    "math_agent": AgentSpec("math_agent", "Math reasoning with structured display output", math_agent),
    "code_agent": AgentSpec("code_agent", "Code generation and optional local execution", code_agent),
    "research_agent": AgentSpec("research_agent", "Research planning and synthesis without fake live browsing", research_agent),
    "summarizer_agent": AgentSpec("summarizer_agent", "Summarize supplied material", summarizer_agent),
    "verifier_agent": AgentSpec("verifier_agent", "Verify outputs from other agents", verifier_agent),
}
