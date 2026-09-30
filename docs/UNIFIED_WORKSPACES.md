# Astra 2.8 Unified Workspaces

This build merges the working domain logic from four uploaded projects into the existing `System-main` AOB instead of running four independent FastAPI apps.

| Source project | Unified workspace | Main functionality | State |
|---|---|---|---|
| VoiceShift v1.0 | `shift` | handover capture, latest summary, open items, search, close issue/task | SQLite |
| VoicePilot v1.1 | `pilot` | receptionist, availability/booking, waitlist/callbacks, drive notes/parking/reminders/expenses/maintenance/calculator | SQLite |
| VoiceBridge v1.0 | `bridge` | emergency guidance, farm weather/logs/crop guidance, voice forms | SQLite + live weather connector |
| VoiceOps v1.0 | `ops` | restaurant orders, inventory, stock count, checklists, floor issue log | in-process demo state |

## Integration points

- `app/workspaces/hub.py` is the single adapter/tool router.
- `app/workspaces/*_store.py` retains the source projects' domain stores.
- `workspace_agent` is registered in the normal Astra agent registry.
- `ChatRequest.workspace` supports `auto`, `shift`, `pilot`, `bridge`, or `ops` selection (the client sends null for Auto).
- `/api/workspaces`, `/api/workspaces/{workspace}/state`, and `/api/workspaces/tool` expose the domain layer for UI/dashboard integrations.
- AssemblyAI `astra_resolve` now forwards the selected workspace when present.

## Safety/confirmation behavior

Appointment booking, form submission and order confirmation are explicitly gated. Emergency guidance remains general first aid rather than diagnosis. Farm guidance avoids definitive disease claims. Floor/machine issues are logged without hazardous repair instructions.

## Run

Use the normal Astra commands in the root README. No second server is required for the merged workspaces.
