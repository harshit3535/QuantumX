# Astra / QuantumX v2.8 — Unified Merge Manifest

`System-main` is the base application. Four domain projects have been integrated as native workspaces instead of remaining as separate apps:

- **VoiceShift** → shift handovers, summaries, open items, search, closure.
- **VoicePilot** → reception/appointments, callbacks, reminders, notes, parking, expenses, maintenance, calculator.
- **VoiceBridge** → emergency guidance, incident logging, live weather, crop guidance, farm logs, market connector hook, voice forms.
- **VoiceOps** → restaurant ordering, menu lookup, inventory, stock counts, opening/closing checklists, floor issue logging.

## Architecture

Existing Astra AOB/planner/orchestrator remains the main entry point. `workspace_agent` is a native agent registered in the existing registry. Workspace selection is available in the dashboard and is also accepted by the API/voice layer.

## Persistence

Workspace SQLite data lives under `data/workspaces/`.

- VoiceBridge's source SQLite data was preserved.
- VoiceShift and VoicePilot start with clean stores when no source database existed.
- VoiceOps keeps its source in-process operational state model.

## Safety

Mutating/high-impact actions retain confirmation gates:

- VoicePilot: booking requires `confirmed=true`.
- VoiceBridge: form submission requires `confirmed=true`.
- VoiceOps: order confirmation requires `confirmed=true`.

## New API surface

- `GET /api/workspaces`
- `GET /api/workspaces/{workspace}/state`
- `POST /api/workspaces/tool`

## Validation

- Python compile check: passed
- Workspace tests: 5/5 passed
- Full existing + new pytest suite: **120 passed**
- Frontend `node --check`: passed
- Render/static test: passed
