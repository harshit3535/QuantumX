# NEXUS Voice Agent

A voice-first multi-agent task orchestration app built around AssemblyAI streaming STT.

## What it solves

1. **Planner/router instead of one generic chatbot**
   - A Core Planner turns each user request into a structured execution plan.
   - Specialist agents are selected from a registry.
   - Each agent has a capability contract and structured output.

2. **Math/code are rendered correctly**
   - Math is returned as LaTeX for the UI and a natural-language `spoken_response` for TTS.
   - Code is rendered in a code panel and the voice layer reads a short natural-language summary instead of reading code literally.

3. **Persistent multi-turn sessions**
   - Conversation history, current goal, plans and agent results are stored in SQLite.
   - New messages continue the same session rather than replacing the previous prompt.

4. **Unknown/casual input handling**
   - Inputs are classified as task, question, conversation, clarification or unknown.
   - Casual sentences such as “mare ghare javu che” do not trigger an error.
   - Low-confidence requests fall back to a clarification response.

## Language policy

- English: Universal-3 Pro Streaming STT + browser TTS.
- Hindi/Gujarati: AssemblyAI Whisper Streaming (`whisper-rt`) + automatic language detection; the app keeps the response text-first and does not auto-TTS these languages by default. AssemblyAI documents Gujarati and Hindi among Whisper Streaming's 99+ supported languages.

## LLM providers

Set `LLM_PROVIDER` to `gemini`, `openrouter`, or `mock`.

The app uses raw HTTP for the LLM calls, so the provider SDK is not tied to the orchestrator.


## Deploy directly to Render (one URL)

This repository is configured as a single Render Web Service. You do **not** need Vercel. Render serves both the FastAPI backend and the `/static` frontend from the same public URL.

### Deploy

1. Push this repository to GitHub.
2. In Render, choose **New → Web Service** and connect the repository.
3. Render can use the included `render.yaml`; otherwise use:

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check: /api/health
```

4. In Render → **Environment**, add your secret API keys. **Do not commit `.env` or keys to GitHub.**

```env
ASSEMBLYAI_API_KEY=your_key
GEMINI_API_KEY=your_key
```

If using OpenRouter instead of Gemini:

```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key
OPENROUTER_MODEL=google/gemini-2.5-flash
```

The app then works from one Render URL, for example:

```text
https://nexus-voice-agent.onrender.com
```

### Important Render storage note

The default database is SQLite. On Render Free, the service filesystem is ephemeral, so SQLite data can disappear after a restart/redeploy/spin-down. Render documents that Free web services do not have persistent disks. For a hackathon demo this is usually acceptable; for durable multi-user memory, connect the app to a managed Postgres database and set `DATABASE_URL`.

Render Free web services can also spin down after 15 minutes without traffic and take about a minute to wake up.

## Run

### 1. Create virtual environment

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate
```

### 2. Install

```bash
pip install -r requirements.txt
```

### 3. Configure

Copy `.env.example` to `.env` and add keys.

Minimum for full voice:

```env
ASSEMBLYAI_API_KEY=...
```

For planning:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

Or:

```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=google/gemini-2.5-flash
```

### 4. Run

```bash
uvicorn app.main:app --reload
```

Open:

`http://127.0.0.1:8000`

## Important

Code execution is disabled by default. To enable the local Code Agent runner:

```env
ENABLE_CODE_EXECUTION=true
```

The runner is intentionally small and is not a hardened security sandbox. Do not expose it to untrusted users.

## Architecture

```text
User Voice/Text
      |
      v
  Input Layer
      |
      +--> AssemblyAI Universal Streaming STT
      |
      v
  CORE ORCHESTRATOR
      |
      +--> intent classification
      +--> plan generation
      +--> context selection
      +--> agent dispatch
      |
      +-------------------------------+
      |       |         |              |
   General   Math     Code         Research
              |         |
            SymPy   optional runner
      |       |         |
      +-------+---------+
              |
          Verifier
              |
        Response Envelope
          /          \
     Visual UI       TTS text
```

## Current built-in agents

- `general_agent`
- `math_agent`
- `code_agent`
- `research_agent` (basic no-key fallback; optional Tavily hook can be added)
- `summarizer_agent`
- `verifier_agent`

## Notes for hackathon hardening

Before submission, add your final branded UI, demo scenario, public deployment, source links, and a short architecture diagram explaining why AssemblyAI is used for the realtime voice layer.

Official AssemblyAI Voice Agent docs:
https://www.assemblyai.com/docs/voice-agents/voice-agent-api

Universal Streaming multilingual STT docs:
https://www.assemblyai.com/docs/universal-streaming/multilingual-transcription
