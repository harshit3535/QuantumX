# Evo Ninja v1.0 — Render + Voice Conversion

This repository keeps the original evo.ninja source and adds a self-contained `render-app/` v1.0 runtime.

## What the v1.0 runtime does

1. User enters a text goal or speaks it in the web UI.
2. Browser microphone audio is streamed as PCM16 mono to `/ws/stt`.
3. Render proxies the stream to AssemblyAI Universal Streaming STT v3 and returns transcript events to the browser.
4. The Render server sends the goal and current history to a Gemini planner/router.
5. Gemini chooses the next specialized agent: Researcher, Developer, Synthesizer, or General.
6. The selected agent runs through OpenRouter.
7. Gemini verifies whether the user's goal is actually complete.
8. If not complete, the planner routes another step. This repeats until the goal is achieved or `MAX_AGENT_STEPS` is reached.
9. The final answer and execution trace are displayed in the web UI.

## API keys

Set these only as Render Environment Variables:

- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`
- `ASSEMBLYAI_API_KEY`

Optional model settings:

- `GEMINI_MODEL` (default `gemini-2.5-flash`)
- `OPENROUTER_MODEL` (default `openai/gpt-4o-mini`)
- `MAX_AGENT_STEPS` (default `8`)

The keys stay server-side; they are not embedded in the web page.

## Deploy

Use the included `render.yaml` Blueprint, or create a Render Node Web Service with:

- Root Directory: `render-app`
- Build Command: `npm install && npm run build`
- Start Command: `npm start`
- Health Check: `/health`

The app listens on `0.0.0.0:$PORT` for Render.

## Android later

No Android-specific UI is required for this v1.0. The hosted web UI is the output surface. A later Android APK/AAB can wrap the Render URL with WebView/Capacitor/TWA and continue using the same backend APIs.
