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
