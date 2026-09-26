# Astra · QuantumX v1.1

A voice-first **Agent Orchestration Brain (AOB)** with two interchangeable voice engines. Say **"Astra"** to wake it up in hands-free mode.

| UI switch | Voice in | Brain | Voice out |
|---|---|---|---|
| **AssemblyAI** (hackathon mode) | AssemblyAI real-time streaming STT | same AOB | browser TTS (swappable) |
| **Free API** (personal mode) | typed text · push-to-talk (Groq Whisper) · hands-free wake word | same AOB | text for text input, voice for voice input |

Only the *edges* change per mode. The brain never knows if you typed or spoke.

```
USER -> mode -> INPUT ADAPTER (AssemblyAI | Whisper | browser | text)
     -> INPUT NORMALIZER      language, code?, math?, question/command/chat, incomplete?, references
     -> CONTEXT + HISTORY     conversation, task state, artifacts, "it" / "the previous code" resolution
     -> AGENT ORCHESTRATION BRAIN
          plan -> execute (dependency-aware, parallel) -> validate -> retry -> [goal check -> more steps] -> compose
     -> STRUCTURED RESPONSE   text / code / math / table / list / warning
     -> OUTPUT DECISION       speak, show, or both; math verbalized, code summarized
     -> UI (rich render)  /  TTS
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # add at least one AI key (see below)
uvicorn app.main:app --reload
# open http://localhost:8000
python -m pytest tests -q                              # 67 tests
node tests/render.test.js                              # renderer + XSS test
```

Math (`solve x^2 - 5x + 6 = 0`), greetings and casual chat work with **no keys at all**.
Code, explanations, summaries need at least one AI key.

## Keys (all have free tiers)

| Key | Where | Used for |
|---|---|---|
| `ASSEMBLYAI_API_KEY` | assemblyai.com | hackathon-mode voice input |
| `GEMINI_API_KEY` | aistudio.google.com | AI brain (first choice) |
| `GROQ_API_KEY` | console.groq.com | AI fallback **and** free voice input (Whisper) |
| `OPENROUTER_API_KEY` | openrouter.ai | second AI fallback |

Providers are tried in the order of `LLM_PROVIDERS`; on rate limit / outage the router falls back to the next one
and skips a limited provider for 30 s. Model names change often on free tiers, so after deploying open
**`/api/diagnostics`**: it sends one tiny request to each configured provider and shows which one works.

## Deploy on Render (free)

1. Push this folder to GitHub.
2. Render -> New -> **Blueprint** (uses `render.yaml`) or New Web Service: build `pip install -r requirements.txt`,
   start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Environment: paste the keys above.
4. Open `https://<your-service>.onrender.com/api/diagnostics`, then `/`.

Free tier notes: the service sleeps after ~15 min idle (first request takes ~1 min, open it once before a demo),
and the disk is wiped on restart, so chat history resets. That is fine for a demo.

## What's new in v1.1

- **Live orchestration, streamed.** `/api/chat/stream` (SSE) reports plan/step progress as the AOB actually runs it -
  the UI shows a Claude-style collapsible "Thought for Ns · N steps" trace instead of a silent wait.
- **Web search agent.** `web_agent` searches DuckDuckGo (no API key) and answers with sources; the planner routes
  "latest/current/today/price of ..." questions to it automatically instead of the no-live-web `research_agent`.
- **Sample prompt chips** on a fresh mission, localized (English/Gujarati/Hindi).
- **Self-improvement, scoped safely.** No auto-modifying code. When a user asks "why did that happen" after an
  error, the explanation is saved (background, keyword-matched, in `knowledge` table). The next similar question
  from anyone gets that note folded into context automatically. Entirely invisible in the UI/demo - it costs the
  user's turn nothing (the save happens via `asyncio.create_task` after the response is already sent).
- **UI redesign**: one compact top row (menu, language, speak-replies, orchestration detail), voice engine switch
  moved into the side drawer, bigger orb with a small status pill instead of full-width state text, input box grows
  from one line up to ~8 then scrolls, and UI chrome text (not the technical orchestration panel) follows the
  selected/detected language.

## How the important problems are handled

* **Unknown input is not an error.** `mare ghare javu che` is classified as conversation and answered (or one short
  clarifying question is asked). Real errors carry a *layer* (`llm`, `stt`, `network`, `agent`, `validation`, ...) and
  a *kind*; one failing agent never crashes the request (its dependents are skipped, the rest is returned).
* **History is a layer, not one giant prompt.** Recent messages + task state + artifacts. "Add login to it",
  "Make the button blue", "Use the previous code" resolve to the latest matching artifact.
* **Code is first class.** Parsed into `code` segments with language, filename, exact indentation. UI shows a card with
  Copy / Save (and Run for Python if you enable `ENABLE_CODE_EXECUTION`, off by default).
* **Math is first class.** SymPy solves and *verifies* ordinary math with no AI call. The UI renders LaTeX (MathJax).
* **TTS never reads raw code or LaTeX.** `x = (-b ± √(b² - 4ac)) / 2a` is spoken as *"x equals negative b plus or
  minus the square root of b squared minus four a c, divided by two a"*. Code is summarized ("The complete code is
  displayed on screen"); say **"read the code aloud"** for a verbatim reading.
* **No infinite loops.** Max iterations, max agent calls, max retries, per-agent timeout and a request deadline
  (`MAX_ITERATIONS`, `MAX_AGENT_CALLS`, `MAX_STEP_RETRIES`, `AGENT_TIMEOUT`, `REQUEST_DEADLINE`).
* **Free-tier friendly.** "Cheap path first": simple requests cost exactly one AI call (no planner call). The LLM
  planner runs only for multi-step requests, and the goal-check only when a step failed or the plan asks for it.

## The AOB loop (your diagram)

```
input -> planner -> steps ──(independent steps run in parallel)──> agents
                     ^                                                |
                     └── goal check: done? no -> extra steps  <── validated results
                                        yes -> compose -> user
```

Agents: `general`, `math`, `code`, `research` (no live web, says so), `summarizer`, `verifier`.
Add an agent = one file + one line in `app/agents/registry.py`; the planner discovers it automatically.

## Android app later (WebView)

The web app is the product; the app only loads it: `https://<your-service>.onrender.com/?app=1&mode=hackathon`
(`app=1` hides the side rail for a compact layout). Two things are required in the app, otherwise voice will not work:

```kotlin
webView.settings.javaScriptEnabled = true
webView.settings.mediaPlaybackRequiresUserGesture = false
webView.webChromeClient = object : WebChromeClient() {
    override fun onPermissionRequest(request: PermissionRequest) { request.grant(request.resources) }   // after RECORD_AUDIO is granted
}
```
and `<uses-permission android:name="android.permission.RECORD_AUDIO"/>` (ask the user at runtime).
Hands-free wake word uses the browser SpeechRecognition API, which Android WebView usually does not provide; the
Talk button (Whisper) and AssemblyAI mode do work in WebView.

## API

`GET /api/health` · `GET /api/diagnostics` · `POST /api/chat` · `GET /api/assemblyai/token?language=en|hi|gu` ·
`POST /api/stt` · `POST/GET/DELETE /api/sessions` · `GET /api/sessions/{id}/history` · `POST /api/run` (off by default)

## Known limits (v1.0)

* Live calls to AssemblyAI / Gemini / Groq / OpenRouter could not be made while building (no keys). The AssemblyAI
  streaming path was tested against a protocol-accurate fake server in a real browser, and request formats were checked
  against the providers' docs (Sep 2026). Use `/api/diagnostics` after deploying.
* While the agent speaks, the microphone is muted (no barge-in) to avoid the agent hearing itself.
* Gujarati/Hindi replies are spoken only if the device has that TTS voice; otherwise the answer stays on screen.
* Hackathon-mode speech languages: English and Hindi use `universal-3-5-pro`, Gujarati uses `whisper-rt`
  (change with `ASSEMBLYAI_MODEL_*`).
* Tested on Python 3.12; targets 3.11 (Render).
