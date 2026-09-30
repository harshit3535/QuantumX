# Astra / QuantumX v2.7

## Mission model
Astra turns every substantive request into an outcome-first Task Contract, assigns an explicit team/role roster, executes dependent agents, reviews work, and stops only when the done-bar is satisfied or a bounded clarification/safety condition is reached.

## Agency-inspired concepts
- Outcome-first tasks
- Curated team presets
- Role + activation + done-when per step
- Build/review loop for code artifacts
- Research/verify loop for evidence-driven work

## Voice behavior
AssemblyAI Voice Agent mode uses an interactive tool execution contract. The agent is instructed to acknowledge substantive tasks in one short sentence, start `astra_resolve` immediately, keep the task running while the AOB works, and avoid replacing work with a summary. Barge-in stops current audio but does not silently cancel background Astra work.

## Code artifacts
Code responses produce named files in `response.meta.artifacts`, are rendered into an artifact workbench, and when `index.html` exists the UI provides a sandboxed live preview. Full code remains visible as typed code segments for history/export.

## Receptionist
The Front Desk scenario handles clarification, availability, confirmation-gated booking, lookup, and messages with persisted SQLite state.

## Render
The included `render.yaml` keeps secrets as `sync: false`. Required secrets are `ASSEMBLYAI_API_KEY` plus at least one of `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`; all other v2.7 runtime settings have safe defaults.
