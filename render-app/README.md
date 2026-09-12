# Evo Ninja Render v1.0

This is a self-contained Render web service extracted from the original evo.ninja project concept.

## Architecture

Browser text/voice -> Render web service -> AssemblyAI STT (voice only) -> Gemini Planner/Router -> OpenRouter specialized agent -> Gemini Goal Verifier -> repeat until achieved or MAX_AGENT_STEPS.

The web UI is intentionally the output surface. A future Android app can load this hosted URL in a WebView/Capacitor shell and reuse the same backend.

## Render

This repo includes `../render.yaml`. You can deploy the repository as a Render Web Service with root directory `render-app`, or use the Blueprint. Render web services must listen on `0.0.0.0` and `$PORT`; this app does so.

Set the three API keys in Render Environment Variables. API keys are never sent to the browser.
