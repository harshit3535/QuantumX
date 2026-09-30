## Astra v2.8

# QuantumX / Astra v2.7

Astra v2.7 is a voice-first AI operator built around the existing QuantumX Agent Orchestration Brain (AOB). It combines a premium mission-console UI, AssemblyAI Voice Agent API for realtime conversational voice, adaptive clarification, and a safe allowlisted real-tool layer for live web search and public URL diagnostics.

## v2.7 headline workflow

```text
Voice / Text
  -> Astra session
  -> Understand + clarify only what is missing
  -> AOB planning
  -> Specialist agents / real tools
  -> Verified structured result
  -> Voice reply + mission telemetry
```

### Hackathon voice mode
AssemblyAI Voice Agent API is the realtime voice edge. The browser receives a short-lived token from `/api/voice-token`, opens `wss://agents.assemblyai.com/v1/ws`, streams 24 kHz PCM16, and receives audio, user/agent transcripts, tool calls, and interruption events. The managed API provides turn detection and barge-in; Astra handles the substantive task through the `astra_resolve` tool bridge.

### Real tools
The public v2.5 toolset is deliberately read-only:
- `operator_agent` -> real public URL health checks
- `web_agent` -> live DuckDuckGo web search
- `astra_resolve` -> bridges AssemblyAI voice turns into the Astra AOB

Local/private network targets are blocked by the URL diagnostic tool. No arbitrary shell or deployment mutation is exposed in this version.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/macOS
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

## Render

Build command:

```bash
python -m pip install --upgrade pip && python -m pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Health check path: `/api/health`

Required hackathon variable:

```text
ASSEMBLYAI_API_KEY=...
```

Add at least one LLM provider for Astra's AOB:

```text
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
```

Optional Voice Agent variables:

```text
ASSEMBLYAI_VOICE_AGENT=true
ASSEMBLYAI_VOICE=anna
ASSEMBLYAI_VOICE_TOKEN_TTL=300
```

Useful diagnostics after deployment:

```text
/api/health
/api/diagnostics
/api/selftest
```

## Tests

```bash
python -m pytest tests -q
node tests/render.test.js
```

Current local verification: 103 Python tests passed and the renderer security/structure test passed.


## AI receptionist / Front Desk
Switch the scenario to **Front Desk** for a deterministic hackathon demo that can answer business hours, check appointment availability, collect a caller name, propose a slot, request explicit confirmation, write a booking with a confirmation code, look up the latest booking, and capture messages. Data is stored in SQLite for the running service.

## Mission evidence and replay
Every mission can persist an audit event stream. The telemetry panel shows agents, events and evidence; the API exposes `/api/sessions/{session_id}/events`, `/api/sessions/{session_id}/replay`, and `/api/sessions/{session_id}/report`.


## Persistent chat memory
Local SQLite stores the active session. For Render/free-tier persistence, enable the optional Supabase snapshot layer with `CLOUD_MEMORY_ENABLED=true`, `SUPABASE_URL`, and the server-only `SUPABASE_SERVICE_ROLE_KEY`. Run `supabase_memory.sql` once in the Supabase SQL Editor. The app mirrors each session's messages, task state, and mission events and restores them on a new instance.

## Workspaces
Astra has three independent scenarios: **Resolve**, **Front Desk**, and **FloorOps**. Front Desk handles appointments and customer messages; FloorOps handles stock checks, safety checklists, incident logging, and shift handoff notes.
