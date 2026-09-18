from __future__ import annotations

import json
import re
from typing import Any
import httpx

from .config import settings

SYSTEM_PROMPT = """
You are the CORE planner of NEXUS, a multi-agent task execution system.
You are NOT the specialist agents. Your job is to classify the latest user message,
understand the current goal, and produce a small executable plan using only the
registered agents.

Rules:
- Casual statements like 'I want to go home' are conversation, not errors.
- Use clarification only when the user's intent cannot reasonably be understood.
- Prefer the smallest useful plan.
- Do not invent tools/agents.
- Never claim that work happened unless a downstream agent reports it.
- For math choose math_agent; for programming choose code_agent; for summaries choose summarizer_agent.
- Use general_agent for ordinary questions/conversation.
- A plan may have multiple dependent steps.
- response_mode is 'math' for equations/calculation display, 'code' for code generation,
  'table' for structured tabular output, and 'text' otherwise.

Registered agents:
- general_agent: normal explanation and conversation
- math_agent: mathematical reasoning and LaTeX output
- code_agent: code generation and optional local execution
- research_agent: simple research from the supplied context; no browsing unless a source tool is configured
- summarizer_agent: compress/summarize supplied content
- verifier_agent: checks downstream outputs

Return JSON only, matching:
{
  "intent": "task|question|conversation|clarification|unknown",
  "goal": "...",
  "confidence": 0.0,
  "steps": [
    {"id":1,"agent":"agent_name","task":"...","input_from":[],"expected_output":"...","depends_on":[]}
  ],
  "response_mode":"text|math|code|table|conversation",
  "needs_clarification": false,
  "clarification_question": null
}
""".strip()


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("LLM did not return JSON")
    return json.loads(text[start : end + 1])


def _mock_plan(message: str) -> dict[str, Any]:
    low = message.lower()
    mathish = any(x in low for x in ["solve", "equation", "calculate", "derivative", "integral", "what is", "+", "-", "*", "/"]) and any(ch.isdigit() for ch in low)
    coding = any(x in low for x in ["python", "javascript", "code", "program", "function", "api", "html", "css"])
    summary = any(x in low for x in ["summarize", "summary", "shorten", "brief"])
    conversation = any(x in low for x in ["home", "tired", "hello", "hi", "kem cho", "majama", "વતન", "ઘરે", "મજા", "કેમ cho"])
    if mathish:
        return {
            "intent": "question", "goal": message, "confidence": 0.72,
            "steps": [{"id": 1, "agent": "math_agent", "task": message, "input_from": [], "expected_output": "verified result", "depends_on": []}],
            "response_mode": "math", "needs_clarification": False, "clarification_question": None,
        }
    if coding:
        return {
            "intent": "task", "goal": message, "confidence": 0.82,
            "steps": [{"id": 1, "agent": "code_agent", "task": message, "input_from": [], "expected_output": "code and explanation", "depends_on": []}, {"id": 2, "agent": "verifier_agent", "task": "Verify the generated code/result.", "input_from": ["step 1"], "expected_output": "verification", "depends_on": [1]}],
            "response_mode": "code", "needs_clarification": False, "clarification_question": None,
        }
    if summary:
        return {
            "intent": "task", "goal": message, "confidence": 0.8,
            "steps": [{"id": 1, "agent": "summarizer_agent", "task": message, "input_from": [], "expected_output": "summary", "depends_on": []}],
            "response_mode": "text", "needs_clarification": False, "clarification_question": None,
        }
    if conversation:
        return {
            "intent": "conversation", "goal": message, "confidence": 0.92,
            "steps": [{"id": 1, "agent": "general_agent", "task": message, "input_from": [], "expected_output": "natural response", "depends_on": []}],
            "response_mode": "conversation", "needs_clarification": False, "clarification_question": None,
        }
    return {
        "intent": "question", "goal": message, "confidence": 0.55,
        "steps": [{"id": 1, "agent": "general_agent", "task": message, "input_from": [], "expected_output": "answer", "depends_on": []}],
        "response_mode": "text", "needs_clarification": False, "clarification_question": None,
    }


def _messages(history: list[dict[str, Any]], current: str) -> list[dict[str, str]]:
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-20:]:
        role = item["role"] if item["role"] in {"user", "assistant"} else "user"
        out.append({"role": role, "content": item["content"]})
    out.append({"role": "user", "content": current})
    return out


async def plan(history: list[dict[str, Any]], current: str) -> dict[str, Any]:
    provider = settings.llm_provider
    if provider == "mock":
        return _mock_plan(current)

    payload_messages = _messages(history, current)
    if provider == "openrouter":
        if not settings.openrouter_api_key:
            return _mock_plan(current)
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
            "Content-Type": "application/json",
        }
        body = {"model": settings.openrouter_model, "messages": payload_messages, "temperature": 0.1}
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            return _extract_json(data["choices"][0]["message"]["content"])

    if provider == "gemini":
        if not settings.gemini_api_key:
            return _mock_plan(current)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        contents = []
        for m in payload_messages:
            contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]})
        body = {"contents": contents, "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}}
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return _extract_json(text)

    return _mock_plan(current)


async def answer_with_llm(prompt: str, system: str = "You are a helpful specialist agent.") -> str:
    provider = settings.llm_provider
    if provider == "mock" or (provider == "gemini" and not settings.gemini_api_key) or (provider == "openrouter" and not settings.openrouter_api_key):
        return prompt

    if provider == "openrouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}", "HTTP-Referer": settings.openrouter_site_url, "X-Title": settings.openrouter_app_name}
        body = {"model": settings.openrouter_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": 0.2}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
