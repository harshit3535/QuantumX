# Astra / QuantumX v2.6 — AssemblyAI Hackathon Build

## Core story
**Speak the problem. Astra investigates, acts, verifies — or works as your front desk.**

## Golden AI receptionist demo
1. Start AssemblyAI Voice Agent.
2. Say: “I need an appointment tomorrow at 3 PM. My name is Harshit.”
3. Astra asks only for the missing detail, if any.
4. Astra checks real availability from the application database.
5. Astra reads back the exact slot and asks for confirmation.
6. Say: “Yes, confirm it.”
7. Astra writes the booking and returns a real confirmation code.
8. Open Mission Control and show agent, tool, evidence and audit timeline.

## Other demo scenarios
- “Check whether my website is reachable.”
- “What are your opening hours?”
- “Look up my appointment.”
- “Take a message for the team.”

## v2.6 features
- Premium AI command-center UI
- AssemblyAI managed Voice Agent mode
- Natural turn-taking and barge-in
- Adaptive clarification across turns
- Real allowlisted tool execution
- Read-back + approval gate before booking writes
- Evidence chain
- Live agent/tool timeline
- Bounded retry/recovery behavior
- Mission report + replay API
- AI receptionist with availability, booking, lookup and message capture


## Render
Build: `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`
Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
Health: `/api/health`

Required secrets: `ASSEMBLYAI_API_KEY` plus at least one of `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`.
Non-secret v2.6 defaults are included in `render.yaml` and `.env.example`.
