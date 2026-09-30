from __future__ import annotations

import ast
import operator as op
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from typing import Any


class PilotStore:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self.db_path = Path(settings.data_path)
        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        self.providers = [
            {"id": "alex", "name": "Alex Mehta", "role": "Senior Consultant", "days": ["Mon", "Tue", "Wed", "Thu", "Fri"]},
            {"id": "riya", "name": "Riya Shah", "role": "Specialist", "days": ["Mon", "Wed", "Fri"]},
        ]
        self.pending_booking: dict[str, Any] | None = None
        self.services = [
            {"id": "general_consultation", "name": "General Consultation", "price": 500, "duration_min": 20},
            {"id": "specialist_consultation", "name": "Specialist Consultation", "price": 700, "duration_min": 30},
            {"id": "follow_up", "name": "Follow-up Visit", "price": 300, "duration_min": 15},
        ]

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.db() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS appointments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                service_id TEXT NOT NULL,
                service TEXT NOT NULL,
                price INTEGER NOT NULL,
                start TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'booked',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS waitlist(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient TEXT NOT NULL,
                service_id TEXT NOT NULL,
                service TEXT NOT NULL,
                preferred_provider_id TEXT,
                preferred_provider TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS callbacks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person TEXT NOT NULL,
                contact TEXT,
                request TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                due TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS parking(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS maintenance(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item TEXT NOT NULL,
                due_km INTEGER,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            );
            """)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _rows(self, conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def snapshot(self) -> dict[str, Any]:
        self._mark_due_reminders()
        with self.db() as conn:
            appointments = self._rows(conn, "SELECT * FROM appointments ORDER BY id DESC LIMIT 30")
            waitlist = self._rows(conn, "SELECT * FROM waitlist WHERE status='waiting' ORDER BY id DESC LIMIT 30")
            callbacks = self._rows(conn, "SELECT * FROM callbacks WHERE status='open' ORDER BY id DESC LIMIT 30")
            reminders = self._rows(conn, "SELECT * FROM reminders WHERE status IN ('active','due') ORDER BY due ASC LIMIT 30")
            notes = self._rows(conn, "SELECT * FROM notes ORDER BY id DESC LIMIT 20")
            parking = self._rows(conn, "SELECT * FROM parking ORDER BY id DESC LIMIT 5")
            expenses = self._rows(conn, "SELECT * FROM expenses ORDER BY id DESC LIMIT 20")
            maintenance = self._rows(conn, "SELECT * FROM maintenance WHERE status='open' ORDER BY id DESC LIMIT 20")
        return {
            "business": {"name": self.settings.business_name, "phone": self.settings.business_phone, "address": self.settings.business_address, "hours": self.settings.business_hours},
            "services": self.services,
            "providers": self.providers,
            "appointments": appointments,
            "waitlist": waitlist,
            "callbacks": callbacks,
            "reminders": reminders,
            "notes": notes,
            "parking": parking,
            "expenses": expenses,
            "maintenance": maintenance,
        }

    def business_info(self, topic: str = "") -> dict[str, Any]:
        info = {"name": self.settings.business_name, "phone": self.settings.business_phone, "address": self.settings.business_address, "hours": self.settings.business_hours}
        return {"ok": True, "info": info, "message": f"{self.settings.business_name}. Hours: {self.settings.business_hours}. Phone: {self.settings.business_phone}."}

    def list_services(self, query: str = "") -> dict[str, Any]:
        q = query.lower().strip()
        items = [x for x in self.services if not q or q in x["name"].lower() or q in x["id"]]
        return {"ok": True, "items": items, "message": f"Found {len(items)} service(s)."}

    def list_providers(self, query: str = "") -> dict[str, Any]:
        q = query.lower().strip()
        items = [x for x in self.providers if not q or q in x["name"].lower() or q in x["role"].lower()]
        return {"ok": True, "items": items, "message": f"Found {len(items)} provider(s)."}

    def available_slots(self, provider_id: str = "", service_id: str = "") -> dict[str, Any]:
        provider = next((x for x in self.providers if x["id"] == provider_id), None) if provider_id else self.providers[0]
        service = next((x for x in self.services if x["id"] == service_id), None) if service_id else self.services[0]
        if not provider or not service:
            return {"ok": False, "message": "Provider or service not found."}
        with self.db() as conn:
            booked = {(r["provider_id"], r["start"]) for r in conn.execute("SELECT provider_id,start FROM appointments WHERE status='booked'").fetchall()}
        slots: list[dict[str, Any]] = []
        today = self.now().date()
        for offset in range(1, 10):
            d = today + timedelta(days=offset)
            day = d.strftime("%a")
            if day not in provider["days"]:
                continue
            for hour in (9, 10, 11, 13, 15, 16, 17):
                when = datetime(d.year, d.month, d.day, hour, 0, tzinfo=self.tz)
                start = when.isoformat()
                if (provider["id"], start) not in booked:
                    slots.append({"start": start, "label": when.strftime("%a %d %b, %I:%M %p"), "provider_id": provider["id"], "service_id": service["id"]})
                if len(slots) >= 8:
                    break
            if len(slots) >= 8:
                break
        return {"ok": True, "provider": provider, "service": service, "slots": slots, "message": f"Found {len(slots)} available slot(s)."}

    def prepare_booking(self, patient: str, provider_id: str, service_id: str, start: str) -> dict[str, Any]:
        patient = patient.strip()[:80]
        provider = next((x for x in self.providers if x["id"] == provider_id), None)
        service = next((x for x in self.services if x["id"] == service_id), None)
        if not patient or not provider or not service or not start:
            return {"ok": False, "message": "Patient name, provider, service and time are required."}
        try:
            when = datetime.fromisoformat(start)
        except ValueError:
            return {"ok": False, "message": "Invalid appointment time."}
        if when.tzinfo is None:
            when = when.replace(tzinfo=self.tz)
        if when <= self.now():
            return {"ok": False, "message": "That time is in the past."}
        slot_check = self.available_slots(provider_id, service_id)["slots"]
        if not any(x["start"] == when.isoformat() for x in slot_check):
            return {"ok": False, "message": "That slot is not available."}
        return {"ok": True, "proposal": {"patient": patient, "provider_id": provider_id, "provider": provider["name"], "service_id": service_id, "service": service["name"], "price": service["price"], "start": when.isoformat(), "label": when.astimezone(self.tz).strftime("%a %d %b, %I:%M %p")}, "message": f"Ready to book {patient} with {provider['name']} for {service['name']} at {when.astimezone(self.tz).strftime('%a %d %b, %I:%M %p')} for {service['price']} rupees. Please confirm."}

    def book_appointment(self, patient: str, provider_id: str, service_id: str, start: str) -> dict[str, Any]:
        proposal = self.prepare_booking(patient, provider_id, service_id, start)
        if not proposal.get("ok"):
            return proposal
        p = proposal["proposal"]
        with self.db() as conn:
            cur = conn.execute("INSERT INTO appointments(patient,provider_id,provider,service_id,service,price,start,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (p["patient"], p["provider_id"], p["provider"], p["service_id"], p["service"], p["price"], p["start"], "booked", self.now().isoformat()))
            appt_id = cur.lastrowid
        appt = {"id": f"APT-{1000+appt_id}", **p, "status": "booked"}
        return {"ok": True, "appointment": appt, "message": f"Appointment {appt['id']} booked for {appt['patient']}."}

    def cancel_appointment(self, appointment_id: str) -> dict[str, Any]:
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM appointments WHERE status='booked' ORDER BY id DESC").fetchall()
            target = next((r for r in rows if f"APT-{1000+r['id']}".lower() == appointment_id.lower().strip()), None)
            if not target:
                return {"ok": False, "message": "Booked appointment not found."}
            conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (target["id"],))
        return {"ok": True, "appointment": dict(target), "message": f"Appointment APT-{1000+target['id']} cancelled."}

    def reschedule_appointment(self, appointment_id: str, new_start: str) -> dict[str, Any]:
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM appointments WHERE status='booked' ORDER BY id DESC").fetchall()
        target = next((r for r in rows if f"APT-{1000+r['id']}".lower() == appointment_id.lower().strip()), None)
        if not target:
            return {"ok": False, "message": "Booked appointment not found."}
        try:
            when = datetime.fromisoformat(new_start)
        except ValueError:
            return {"ok": False, "message": "Invalid new appointment time."}
        slots = self.available_slots(target["provider_id"], target["service_id"])["slots"]
        if not any(x["start"] == when.isoformat() for x in slots):
            return {"ok": False, "message": "The new slot is not available."}
        with self.db() as conn:
            conn.execute("UPDATE appointments SET status='rescheduled' WHERE id=?", (target["id"],))
            cur = conn.execute("INSERT INTO appointments(patient,provider_id,provider,service_id,service,price,start,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (target["patient"], target["provider_id"], target["provider"], target["service_id"], target["service"], target["price"], when.isoformat(), "booked", self.now().isoformat()))
            new_id = cur.lastrowid
        return {"ok": True, "appointment": {"id": f"APT-{1000+new_id}", "patient": target["patient"], "provider": target["provider"], "service": target["service"], "price": target["price"], "start": when.isoformat(), "label": when.astimezone(self.tz).strftime("%a %d %b, %I:%M %p"), "status": "booked"}, "message": f"Appointment rescheduled to {when.astimezone(self.tz).strftime('%a %d %b, %I:%M %p')}."}

    def add_waitlist(self, patient: str, service_id: str, provider_id: str = "", note: str = "") -> dict[str, Any]:
        service = next((x for x in self.services if x["id"] == service_id), None)
        provider = next((x for x in self.providers if x["id"] == provider_id), None) if provider_id else None
        if not patient.strip() or not service:
            return {"ok": False, "message": "Patient and service are required."}
        with self.db() as conn:
            cur = conn.execute("INSERT INTO waitlist(patient,service_id,service,preferred_provider_id,preferred_provider,note,created_at) VALUES(?,?,?,?,?,?,?)", (patient.strip()[:80], service_id, service["name"], provider_id or None, provider["name"] if provider else None, note[:200], self.now().isoformat()))
        return {"ok": True, "waitlist_id": f"WAIT-{1000+cur.lastrowid}", "message": f"Added {patient.strip()} to the {service['name']} waitlist."}

    def list_waitlist(self) -> dict[str, Any]:
        with self.db() as conn:
            rows = self._rows(conn, "SELECT * FROM waitlist WHERE status='waiting' ORDER BY id ASC LIMIT 30")
        return {"ok": True, "items": rows, "message": f"There are {len(rows)} people waiting."}

    def create_callback(self, person: str, request: str, contact: str = "", priority: str = "normal") -> dict[str, Any]:
        priority = priority if priority in {"normal", "high"} else "normal"
        with self.db() as conn:
            cur = conn.execute("INSERT INTO callbacks(person,contact,request,priority,created_at) VALUES(?,?,?,?,?)", (person.strip()[:80], contact.strip()[:80], request.strip()[:300], priority, self.now().isoformat()))
        return {"ok": True, "callback_id": f"CALL-{1000+cur.lastrowid}", "message": f"Callback request created for {person.strip()}."}

    def list_callbacks(self) -> dict[str, Any]:
        with self.db() as conn:
            rows = self._rows(conn, "SELECT * FROM callbacks WHERE status='open' ORDER BY id DESC LIMIT 30")
        return {"ok": True, "items": rows, "message": f"There are {len(rows)} open callback requests."}

    def set_reminder(self, message: str, minutes: int) -> dict[str, Any]:
        minutes = max(1, min(int(minutes), 24*60))
        due = self.now() + timedelta(minutes=minutes)
        with self.db() as conn:
            cur = conn.execute("INSERT INTO reminders(message,due,created_at) VALUES(?,?,?)", (message.strip()[:240], due.isoformat(), self.now().isoformat()))
        return {"ok": True, "reminder": {"id": f"REM-{1000+cur.lastrowid}", "message": message.strip()[:240], "due": due.isoformat(), "label": due.strftime('%I:%M %p'), "status": "active"}, "message": f"Reminder set for {due.strftime('%I:%M %p')}."}

    def list_reminders(self) -> dict[str, Any]:
        self._mark_due_reminders()
        with self.db() as conn:
            rows = self._rows(conn, "SELECT * FROM reminders WHERE status IN ('active','due') ORDER BY due ASC LIMIT 30")
        return {"ok": True, "items": rows, "message": f"You have {len(rows)} active or due reminder(s)."}

    def save_note(self, text: str, category: str = "general") -> dict[str, Any]:
        with self.db() as conn:
            cur = conn.execute("INSERT INTO notes(text,category,created_at) VALUES(?,?,?)", (text.strip()[:400], category[:40], self.now().isoformat()))
        return {"ok": True, "note_id": f"NOTE-{1000+cur.lastrowid}", "message": "Voice note saved."}

    def recent_notes(self, category: str = "") -> dict[str, Any]:
        with self.db() as conn:
            rows = self._rows(conn, "SELECT * FROM notes WHERE (?='' OR category=?) ORDER BY id DESC LIMIT 10", (category, category))
        return {"ok": True, "items": rows, "message": f"Found {len(rows)} note(s)."}

    def save_parking(self, location: str, detail: str = "") -> dict[str, Any]:
        with self.db() as conn:
            cur = conn.execute("INSERT INTO parking(location,detail,created_at) VALUES(?,?,?)", (location.strip()[:120], detail.strip()[:180], self.now().isoformat()))
        return {"ok": True, "parking_id": f"PARK-{1000+cur.lastrowid}", "message": f"Parking spot saved: {location.strip()}."}

    def get_parking(self) -> dict[str, Any]:
        with self.db() as conn:
            row = conn.execute("SELECT * FROM parking ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return {"ok": True, "parking": None, "message": "No parking location saved."}
        return {"ok": True, "parking": dict(row), "message": f"Your last saved parking spot is {row['location']}."}

    def log_expense(self, kind: str, amount: float, note: str = "") -> dict[str, Any]:
        if amount < 0:
            return {"ok": False, "message": "Expense cannot be negative."}
        with self.db() as conn:
            cur = conn.execute("INSERT INTO expenses(kind,amount,note,created_at) VALUES(?,?,?,?)", (kind[:40], round(float(amount),2), note[:180], self.now().isoformat()))
        return {"ok": True, "expense_id": f"EXP-{1000+cur.lastrowid}", "message": f"Logged {kind} expense of ₹{amount:.2f}."}

    def expense_total(self) -> dict[str, Any]:
        with self.db() as conn:
            row = conn.execute("SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS count FROM expenses").fetchone()
        return {"ok": True, "total": round(float(row["total"]), 2), "count": int(row["count"]), "message": f"Recorded trip expenses total ₹{float(row['total']):.2f}."}

    def log_maintenance(self, item: str, due_km: int = 0, note: str = "") -> dict[str, Any]:
        with self.db() as conn:
            cur = conn.execute("INSERT INTO maintenance(item,due_km,note,created_at) VALUES(?,?,?,?)", (item.strip()[:120], int(due_km) if due_km else None, note[:200], self.now().isoformat()))
        return {"ok": True, "maintenance_id": f"MAINT-{1000+cur.lastrowid}", "message": f"Maintenance item logged: {item.strip()}."}

    def list_maintenance(self) -> dict[str, Any]:
        with self.db() as conn:
            rows = self._rows(conn, "SELECT * FROM maintenance WHERE status='open' ORDER BY id DESC LIMIT 20")
        return {"ok": True, "items": rows, "message": f"There are {len(rows)} open maintenance items."}

    def calculate(self, expression: str) -> dict[str, Any]:
        allowed = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv, ast.Mod: op.mod, ast.Pow: op.pow}
        try:
            tree = ast.parse(expression, mode="eval")
            def ev(node: ast.AST) -> float:
                if isinstance(node, ast.Expression): return ev(node.body)
                if isinstance(node, ast.Constant) and isinstance(node.value,(int,float)): return float(node.value)
                if isinstance(node, ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                    value=ev(node.operand); return -value if isinstance(node.op,ast.USub) else value
                if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                    right=ev(node.right)
                    if isinstance(node.op,ast.Pow) and abs(right)>8: raise ValueError("Exponent too large")
                    return allowed[type(node.op)](ev(node.left),right)
                raise ValueError("Unsupported expression")
            value=round(ev(tree),2)
            if isinstance(value,float) and value.is_integer(): value=int(value)
            return {"ok":True,"value":value,"message":f"The answer is {value}."}
        except (SyntaxError,ValueError,ZeroDivisionError) as exc:
            return {"ok":False,"message":f"I could not calculate that: {exc}."}

    def _mark_due_reminders(self) -> None:
        now = self.now()
        with self.db() as conn:
            rows = conn.execute("SELECT id,due FROM reminders WHERE status='active'").fetchall()
            for row in rows:
                try:
                    if datetime.fromisoformat(row["due"]) <= now:
                        conn.execute("UPDATE reminders SET status='due' WHERE id=?", (row["id"],))
                except ValueError:
                    pass

    def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "business_info": lambda: self.business_info(args.get("topic", "")),
            "list_services": lambda: self.list_services(args.get("query", "")),
            "list_providers": lambda: self.list_providers(args.get("query", "")),
            "available_slots": lambda: self.available_slots(args.get("provider_id", ""), args.get("service_id", "")),
            "prepare_booking": lambda: self.prepare_booking(args.get("patient", ""), args.get("provider_id", ""), args.get("service_id", ""), args.get("start", "")),
            "book_appointment": lambda: self.book_appointment(args.get("patient", ""), args.get("provider_id", ""), args.get("service_id", ""), args.get("start", "")),
            "cancel_appointment": lambda: self.cancel_appointment(args.get("appointment_id", "")),
            "reschedule_appointment": lambda: self.reschedule_appointment(args.get("appointment_id", ""), args.get("new_start", "")),
            "add_waitlist": lambda: self.add_waitlist(args.get("patient", ""), args.get("service_id", ""), args.get("provider_id", ""), args.get("note", "")),
            "list_waitlist": lambda: self.list_waitlist(),
            "create_callback": lambda: self.create_callback(args.get("person", ""), args.get("request", ""), args.get("contact", ""), args.get("priority", "normal")),
            "list_callbacks": lambda: self.list_callbacks(),
            "set_reminder": lambda: self.set_reminder(args.get("message", ""), int(args.get("minutes", 5))),
            "list_reminders": lambda: self.list_reminders(),
            "save_note": lambda: self.save_note(args.get("text", ""), args.get("category", "general")),
            "recent_notes": lambda: self.recent_notes(args.get("category", "")),
            "save_parking": lambda: self.save_parking(args.get("location", ""), args.get("detail", "")),
            "get_parking": lambda: self.get_parking(),
            "log_expense": lambda: self.log_expense(args.get("kind", "trip"), float(args.get("amount", 0)), args.get("note", "")),
            "expense_total": lambda: self.expense_total(),
            "log_maintenance": lambda: self.log_maintenance(args.get("item", ""), int(args.get("due_km", 0)), args.get("note", "")),
            "list_maintenance": lambda: self.list_maintenance(),
            "calculate": lambda: self.calculate(args.get("expression", "")),
        }
        fn=mapping.get(tool)
        if not fn: return {"ok":False,"message":f"Unknown tool: {tool}"}
        try: return fn()
        except (TypeError,ValueError) as exc: return {"ok":False,"message":f"Invalid tool arguments: {exc}"}
