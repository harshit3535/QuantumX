# Astra v2.4 — Hackathon Demo Script

## 45-second story

1. Open Astra in **AssemblyAI** mode.
2. Press **Start** and ask by voice: **“Research the latest Python release, compare it with the previous release, and give me the key changes with sources.”**
3. Show the live Mission Control phases moving from UNDERSTAND → PLAN → EXECUTE → VERIFY → FINALIZE.
4. Point at the tool shelf: context, planner, live web search, research/summarizer, verifier.
5. Show the answer with sources and the execution trace.

## Stronger multi-agent demo

Say: **“Build a Python calculator app, explain the design, and then review the code for bugs.”**

The planner can split work across code_agent + verifier_agent; the UI shows the dependency-aware trace and retry/validation behavior.

## Why the architecture is distinctive

Astra is not a single prompt wrapper. It is a voice-first orchestration system with a unified input bus, a dependency-aware planner, progressive tool access, validation/retry, persistent task context, structured rendering, and a human approval gate for high-impact actions.

## Before demo

- Set `ASSEMBLYAI_API_KEY`.
- Set at least one LLM key: `GEMINI_API_KEY`, `GROQ_API_KEY`, or `OPENROUTER_API_KEY`.
- Open `/api/health` and `/api/diagnostics`.
- Keep `ENABLE_CODE_EXECUTION=false` on a public demo unless you understand the security implications.
