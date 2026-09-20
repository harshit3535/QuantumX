# QuantumX — Web Personal Mode

This version keeps the existing AOB/agents and adds a Render-compatible FastAPI web interface.

## Render
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn web.main:app --host 0.0.0.0 --port $PORT`

## Environment variables
- `APP_MODE=personal`
- `OPENROUTER_API_KEY=...`
- `OPENROUTER_MODEL=openai/gpt-4o-mini`
- `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`

Do not commit `.env` or API keys to GitHub.

The browser UI uses the browser's speech recognition/synthesis when supported, so the Render server does not need PyAudio or a local microphone.
