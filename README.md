# AOB v1.0 — Mode-aware Multimodal Agent System

A Python desktop prototype for a **single Agent Orchestration Brain (AOB)** that can run in two separate modes:

- **Hackathon Mode** — AssemblyAI realtime speech-to-text + voice-first UI
- **Personal Mode** — local optional faster-whisper STT + text/voice UI + local pyttsx3 TTS

Both modes share the same normalization, history, planning, agent routing, validation, and structured-response core.

## Architecture

```text
USER
  |
  v
MODE SELECTOR
  |
  +---------------------------+
  |                           |
  v                           v
HACKATHON MODE           PERSONAL MODE
AssemblyAI STT           Local STT / Text
Voice-first UI            Voice + Text UI
  |                           |
  +------------+--------------+
               |
               v
        INPUT NORMALIZER
               |
               v
        CONTEXT + HISTORY
               |
               v
       AGENT ORCHESTRATION BRAIN
       - understand
       - plan
       - select agents
       - route dependencies
       - execute
       - validate
               |
               v
              AGENTS
          /      |       \
      general  coding   math
                    \    /
                   validation
               |
               v
       STRUCTURED RESPONSE
         text / code / math
               |
               v
       OUTPUT / TTS LAYER
```

## Included v1.0 capabilities

1. Two separate UIs backed by one AOB.
2. AssemblyAI realtime v3 streaming adapter using the current `assemblyai.streaming.v3` SDK.
3. Final-turn gating from AssemblyAI `end_of_turn`; low-confidence transcripts ask for clarification instead of acting blindly.
4. Explicit session termination in `finally` to avoid leaving realtime sessions open.
5. Personal local STT adapter using optional `faster-whisper`.
6. Local/offline desktop TTS via `pyttsx3`.
7. Persistent JSON conversation history and task state.
8. LLM planner with strict structured JSON plan + heuristic fallback.
9. Agent dependency graph + topological execution.
10. General fallback agent for unknown/ambiguous input.
11. Coding, math, general, and validation agents.
12. Structured response segments for text, code, math, warnings, and errors.
13. TTS verbalizer that summarizes large code instead of reading raw code by default.
14. Deterministic arithmetic and optional SymPy equation handling.
15. OpenAI-compatible LLM adapter for cloud APIs or local servers such as Ollama.
16. No API keys embedded in source code.

## 1) Setup

Create a virtual environment:

```bash
python -m venv .venv
.venv\\Scripts\\activate
```

Install base dependencies:

```bash
pip install -r requirements.txt
```

For personal local voice + optional math support:

```bash
pip install -r requirements-personal.txt
```

Copy `.env.example` to `.env` and fill the keys you intend to use.

## 2) AssemblyAI

Set:

```env
ASSEMBLYAI_API_KEY=your_key_here
ASSEMBLYAI_SPEECH_MODEL=universal-3-5-pro
ASSEMBLYAI_MODE=balanced
```

Launch:

```bash
python main.py
```

Select **Hackathon Mode** and press **Start Listening**.

The adapter expects a desktop microphone that can provide 16 kHz mono PCM. The AssemblyAI v3 streaming SDK handles the WebSocket; the app streams microphone frames and commits finalized turns to the AOB.

## 3) LLM configuration

The project can run in `mock` mode with no LLM API key, which is useful for UI and architecture testing.

For an OpenAI-compatible API:

```env
AOB_LLM_PROVIDER=openai_compat
OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
OPENAI_COMPAT_API_KEY=your_key_here
OPENAI_COMPAT_MODEL=your_model
```

For a local Ollama server exposing an OpenAI-compatible endpoint:

```env
AOB_LLM_PROVIDER=openai_compat
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_COMPAT_API_KEY=
OPENAI_COMPAT_MODEL=your-installed-ollama-model
```

## 4) Personal local voice

Install `requirements-personal.txt`, launch Personal Mode, and press **Local Voice**.

The first use may download/load the selected Whisper model. Adjust:

```env
PERSONAL_STT_MODEL=small
PERSONAL_STT_DEVICE=cpu
PERSONAL_STT_COMPUTE_TYPE=int8
PERSONAL_RECORD_SECONDS=12
```

This v1.0 uses fixed-length recording for the personal local STT adapter; continuous streaming can be added in v1.1 without changing the AOB.

## 5) Response format

Agents return typed segments such as:

```json
{
  "type": "code",
  "language": "python",
  "content": "print('hello')"
}
```

or:

```json
{
  "type": "math",
  "content": "x^2 + 2x + 1 = 0"
}
```

That lets the output layer decide whether content should be rendered, summarized for TTS, or both.

## 6) Known v1.0 boundaries

- The personal local STT adapter is turn-based rather than fully streaming.
- The GUI math renderer is a readable text/math presentation rather than a full browser-grade equation engine.
- The project does not automatically browse the web or execute arbitrary generated code.
- Agent names are intentionally small and safe in v1.0; new agents can be registered in `agents/factory.py`.
- For production, API keys should stay server-side when exposing the app to untrusted clients.

## 7) Suggested v1.1 upgrades

- Continuous local STT with VAD.
- Interruptible TTS / barge-in.
- Streaming LLM tokens.
- True Markdown/LaTeX renderer.
- Sandboxed code execution.
- File/tool agents.
- Agent retry policies and per-agent timeouts.
- More granular memory: conversation vs task vs long-term facts.
- Agent trace viewer and evaluation metrics.
