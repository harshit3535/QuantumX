from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BridgeStore:
    def __init__(self, settings: Any):
        self.settings = settings
        self.db = Path(settings.database_path)
        if not self.db.is_absolute():
            self.db = Path(__file__).resolve().parents[2] / self.db
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._seed()
        self.sessions: dict[str, list[dict[str, str]]] = {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS farm_logs (
                    id TEXT PRIMARY KEY,
                    crop TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS form_submissions (
                    id TEXT PRIMARY KEY,
                    form_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS form_drafts (
                    session_id TEXT PRIMARY KEY,
                    form_id TEXT NOT NULL,
                    answers TEXT NOT NULL,
                    updated TEXT NOT NULL
                );
                """
            )

    def _seed(self) -> None:
        with self._connect() as c:
            existing = c.execute("SELECT COUNT(*) n FROM farm_logs").fetchone()[0]
            if existing == 0:
                c.execute(
                    "INSERT INTO farm_logs(id,crop,note,created) VALUES(?,?,?,?)",
                    ("DEMO-FARM-001", "cotton", "Starter crop note: scout lower leaves and record symptoms before treatment.", now_iso()),
                )

    # ---------- emergency ----------
    def emergency_steps(self, scenario: str) -> dict[str, Any]:
        key = scenario.lower().strip().replace(" ", "_")
        guides = {
            "severe_bleeding": {
                "title": "Severe bleeding",
                "urgent": True,
                "steps": [
                    "Call local emergency services now, especially if bleeding is heavy, spurting, or the person is becoming faint.",
                    "Use clean cloth or gauze and apply firm, continuous pressure to the wound.",
                    "If blood soaks through, add more cloth or gauze on top rather than removing the first layer.",
                    "Keep the person still and watch their breathing and responsiveness until help arrives.",
                ],
            },
            "burn": {
                "title": "Burn",
                "urgent": False,
                "steps": [
                    "Move away from the heat source and stop the burning process if it is safe to do so.",
                    "Cool the affected area with cool running water for about 20 minutes when available.",
                    "Do not apply ice, butter, toothpaste, or other household products.",
                    "Seek urgent medical help for large, deep, chemical, electrical, facial, hand, or airway burns.",
                ],
            },
            "fainting": {
                "title": "Fainting / unresponsive person",
                "urgent": True,
                "steps": [
                    "Check whether the person responds and is breathing normally.",
                    "Call local emergency services if they are not responding, not breathing normally, or have a serious injury.",
                    "If they are breathing and there is no suspected injury, keep them lying flat and monitor them.",
                    "If they do not recover promptly or have repeated fainting, arrange urgent medical assessment.",
                ],
            },
            "choking": {
                "title": "Choking",
                "urgent": True,
                "steps": [
                    "If the person can cough or speak, encourage them to keep coughing.",
                    "If they cannot breathe, speak, or cough effectively, call local emergency services and start the emergency choking protocol you have been trained to use.",
                    "If they become unresponsive, follow local CPR guidance and emergency dispatcher instructions.",
                ],
            },
            "allergic_reaction": {
                "title": "Severe allergic reaction",
                "urgent": True,
                "steps": [
                    "Call local emergency services if there is trouble breathing, swelling of the tongue or throat, collapse, or rapidly worsening symptoms.",
                    "If the person has their prescribed emergency medicine or auto-injector, help them use it according to their prescribed instructions.",
                    "Keep them monitored and do not leave them alone while waiting for help.",
                ],
            },
        }
        guide = guides.get(key)
        if not guide:
            guide = {
                "title": "Unspecified emergency",
                "urgent": True,
                "steps": [
                    "If the situation may be life-threatening, call local emergency services now.",
                    "Stay with the person, check responsiveness and breathing, and follow dispatcher instructions.",
                    "Do not attempt risky procedures based only on this assistant.",
                ],
            }
        return {"ok": True, "scenario": key, **guide, "emergency_number": self.settings.emergency_number or None,
                "message": f"Emergency guidance ready for {guide['title']}."}

    def log_incident(self, scenario: str, note: str) -> dict[str, Any]:
        incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        with self._connect() as c:
            c.execute("INSERT INTO incidents VALUES(?,?,?,?)", (incident_id, scenario[:80], note[:500], now_iso()))
        return {"ok": True, "id": incident_id, "message": f"Incident note {incident_id} recorded locally."}

    # ---------- farm ----------
    def log_farm(self, crop: str, note: str) -> dict[str, Any]:
        crop = crop.strip()[:80]
        note = note.strip()[:500]
        if not crop or not note:
            return {"ok": False, "message": "Crop and observation are required."}
        farm_id = f"FARM-{uuid.uuid4().hex[:8].upper()}"
        with self._connect() as c:
            c.execute("INSERT INTO farm_logs VALUES(?,?,?,?)", (farm_id, crop, note, now_iso()))
        return {"ok": True, "id": farm_id, "message": f"Field observation {farm_id} saved."}

    def recent_farm_logs(self) -> dict[str, Any]:
        with self._connect() as c:
            rows = c.execute("SELECT id,crop,note,created FROM farm_logs ORDER BY created DESC LIMIT 6").fetchall()
        return {"ok": True, "logs": [dict(r) for r in rows], "message": f"Showing {len(rows)} recent field notes."}

    def crop_advice(self, crop: str, symptom: str) -> dict[str, Any]:
        c = crop.lower().strip()
        s = symptom.lower().strip()
        rules = []
        if "cotton" in c and ("white" in s or "aphid" in s or "sticky" in s):
            rules = [
                "Inspect several plants, especially the undersides of leaves, before deciding on treatment.",
                "Check whether the symptom is spreading and record the affected area and plant stage.",
                "Use your local agricultural extension or agronomist to confirm the cause before applying a pesticide.",
            ]
        elif "groundnut" in c and ("spot" in s or "leaf" in s):
            rules = [
                "Record where the spots first appeared and whether lower leaves are affected more heavily.",
                "Avoid assuming a disease from appearance alone; check with a local agronomist before treatment.",
                "Keep a dated field photo log so changes over the next few days can be compared.",
            ]
        else:
            rules = [
                "Record the crop, location in the field, symptom, date, and whether it is spreading.",
                "Take clear photos of the whole plant and the affected part when possible.",
                "Use a local agronomist or agricultural extension service to confirm the cause before treatment decisions.",
            ]
        return {"ok": True, "crop": crop, "symptom": symptom, "guidance": rules,
                "message": "General field guidance provided; this is not a definitive diagnosis."}

    # ---------- forms ----------
    FORMS: dict[str, dict[str, Any]] = {
        "scholarship": {
            "name": "Scholarship application",
            "description": "A demo scholarship intake form.",
            "fields": [
                {"id": "full_name", "label": "Full name", "required": True},
                {"id": "course", "label": "Course or program", "required": True},
                {"id": "institution", "label": "Institution", "required": True},
                {"id": "annual_income", "label": "Annual family income", "required": True},
                {"id": "phone", "label": "Phone number", "required": True},
            ],
        },
        "service_request": {
            "name": "Public service request",
            "description": "A demo issue/request intake form.",
            "fields": [
                {"id": "full_name", "label": "Full name", "required": True},
                {"id": "service", "label": "Service needed", "required": True},
                {"id": "location", "label": "Location or village", "required": True},
                {"id": "description", "label": "Problem description", "required": True},
                {"id": "phone", "label": "Phone number", "required": True},
            ],
        },
        "farmer_support": {
            "name": "Farmer support request",
            "description": "A demo agricultural support intake form.",
            "fields": [
                {"id": "farmer_name", "label": "Farmer name", "required": True},
                {"id": "crop", "label": "Crop", "required": True},
                {"id": "village", "label": "Village", "required": True},
                {"id": "land_area", "label": "Land area", "required": True},
                {"id": "problem", "label": "What help is needed", "required": True},
            ],
        },
    }

    def list_forms(self) -> dict[str, Any]:
        items = [{"id": k, "name": v["name"], "description": v["description"], "field_count": len(v["fields"])} for k, v in self.FORMS.items()]
        return {"ok": True, "forms": items, "message": f"There are {len(items)} voice forms available."}

    def start_form(self, session_id: str, form_id: str) -> dict[str, Any]:
        form = self.FORMS.get(form_id)
        if not form:
            return {"ok": False, "message": "Form not found."}
        answers = {}
        with self._connect() as c:
            c.execute("INSERT OR REPLACE INTO form_drafts(session_id,form_id,answers,updated) VALUES(?,?,?,?)", (session_id, form_id, json.dumps(answers), now_iso()))
        first = form["fields"][0]
        return {"ok": True, "form_id": form_id, "form": form, "next_field": first, "message": f"Started {form['name']}. First question: {first['label']}."}

    def _draft(self, session_id: str):
        with self._connect() as c:
            row = c.execute("SELECT form_id,answers FROM form_drafts WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return None
        return row["form_id"], json.loads(row["answers"])

    def set_form_answer(self, session_id: str, field: str, value: str) -> dict[str, Any]:
        draft = self._draft(session_id)
        if not draft:
            return {"ok": False, "message": "Start a form first."}
        form_id, answers = draft
        form = self.FORMS[form_id]
        valid = {f["id"] for f in form["fields"]}
        if field not in valid:
            return {"ok": False, "message": "That field is not part of the active form."}
        answers[field] = str(value).strip()[:500]
        with self._connect() as c:
            c.execute("UPDATE form_drafts SET answers=?,updated=? WHERE session_id=?", (json.dumps(answers), now_iso(), session_id))
        next_field = next((f for f in form["fields"] if f["id"] not in answers), None)
        msg = "Answer saved. The form is complete." if not next_field else f"Answer saved. Next question: {next_field['label']}."
        return {"ok": True, "form_id": form_id, "answers": answers, "next_field": next_field, "message": msg}

    def validate_form(self, session_id: str) -> dict[str, Any]:
        draft = self._draft(session_id)
        if not draft:
            return {"ok": False, "message": "Start a form first."}
        form_id, answers = draft
        form = self.FORMS[form_id]
        missing = [f["label"] for f in form["fields"] if f["required"] and not answers.get(f["id"], "").strip()]
        phone = answers.get("phone", "")
        issues = list(missing)
        if phone and sum(ch.isdigit() for ch in phone) < 7:
            issues.append("Phone number looks incomplete")
        return {"ok": not issues, "form_id": form_id, "missing_or_invalid": issues,
                "answers": answers, "message": "Form is ready for preview." if not issues else f"Form needs {len(issues)} correction(s)."}

    def preview_form(self, session_id: str) -> dict[str, Any]:
        check = self.validate_form(session_id)
        if not check["ok"]:
            return check
        form_id, answers = self._draft(session_id)
        form = self.FORMS[form_id]
        return {"ok": True, "form": form, "answers": answers, "message": "Review this preview and explicitly confirm submission."}

    def submit_form(self, session_id: str, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            return {"ok": False, "requires_confirmation": True, "message": "I need your explicit confirmation before submitting the form."}
        check = self.validate_form(session_id)
        if not check["ok"]:
            return check
        form_id, answers = self._draft(session_id)
        submission_id = f"FORM-{uuid.uuid4().hex[:8].upper()}"
        with self._connect() as c:
            c.execute("INSERT INTO form_submissions VALUES(?,?,?,?,?)", (submission_id, form_id, json.dumps(answers), "submitted-local", now_iso()))
        return {"ok": True, "id": submission_id, "status": "submitted-local", "message": f"Demo submission {submission_id} completed locally."}

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as c:
            incidents = c.execute("SELECT id,scenario,note,created FROM incidents ORDER BY created DESC LIMIT 5").fetchall()
            farm_logs = c.execute("SELECT id,crop,note,created FROM farm_logs ORDER BY created DESC LIMIT 5").fetchall()
            submissions = c.execute("SELECT id,form_id,status,created FROM form_submissions ORDER BY created DESC LIMIT 5").fetchall()
        return {
            "incidents": [dict(x) for x in incidents],
            "farm_logs": [dict(x) for x in farm_logs],
            "submissions": [dict(x) for x in submissions],
            "location": self.settings.farm_location,
        }
