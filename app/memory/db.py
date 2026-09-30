"""SQLite storage: sessions, messages, task state, run log.

Note for Render free tier: the disk is ephemeral, so the database is wiped on
redeploy/restart. That is fine for a demo. For permanent history attach a
Render disk and point DATABASE_URL at it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from ..config import settings
from .cloud import SupabaseMemory


class Database:
    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            self.path = Path(url.removeprefix("sqlite:///"))
        else:
            self.path = Path("./data/nexus.db")
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._restoring_cloud = False
        self.cloud = SupabaseMemory(settings.supabase_url, settings.supabase_service_role_key, settings.supabase_table) if settings.cloud_memory_enabled else None
        self._init()
        if self.cloud and self.cloud.enabled():
            self._restore_cloud()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init(self) -> None:
        with self._lock:
            conn = self._conn()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'text',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS task_state (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    trace_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keywords TEXT NOT NULL,
                    question TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_updated ON knowledge(updated_at);
                CREATE TABLE IF NOT EXISTS mission_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_mission_events_session ON mission_events(session_id, id);
                CREATE TABLE IF NOT EXISTS receptionist_bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    confirmation_code TEXT NOT NULL UNIQUE,
                    customer_name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    service TEXT NOT NULL,
                    appointment_date TEXT NOT NULL,
                    appointment_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_receptionist_bookings_slot ON receptionist_bookings(appointment_date, appointment_time, status);
                CREATE TABLE IF NOT EXISTS receptionist_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    customer_name TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS floor_inventory (
                    sku TEXT PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General',
                    quantity INTEGER NOT NULL DEFAULT 0,
                    reorder_level INTEGER NOT NULL DEFAULT 0,
                    unit TEXT NOT NULL DEFAULT 'unit',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS floor_checklists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS floor_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    incident_code TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS floor_shift_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()


    # ------------------------------------------------------------ cloud memory
    def _snapshot(self, sid: str) -> dict[str, Any] | None:
        row = self.get_session(sid)
        if not row:
            return None
        return {
            "session_id": sid,
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": self.history(sid, 200),
            "task_state": self.get_task_state(sid),
            "events": self.mission_events(sid, 500),
        }

    def _sync_cloud(self, sid: str) -> None:
        if self._restoring_cloud or not self.cloud or not self.cloud.enabled():
            return
        snap = self._snapshot(sid)
        if snap:
            self.cloud.upsert(snap)

    def _restore_cloud(self) -> None:
        rows = self.cloud.all() if self.cloud else []
        if not rows:
            return
        self._restoring_cloud = True
        try:
            for snap in rows:
                sid = str(snap.get("session_id") or "").strip()
                if not sid or self.get_session(sid):
                    continue
                self.create_session(str(snap.get("title") or "Restored mission"), sid, _sync=False)
                for m in snap.get("messages") or []:
                    self.add_message(sid, m.get("role","assistant"), m.get("content","") or "", m.get("source","text"), m.get("metadata") or {}, _sync=False)
                self.set_task_state(sid, snap.get("task_state") or {}, _sync=False)
                for e in snap.get("events") or []:
                    self.add_mission_event(sid, e.get("event_type","event"), e.get("payload") or {}, e.get("label", ""), _sync=False)
        finally:
            self._restoring_cloud = False

    # ---------------------------------------------------------------- sessions
    def create_session(self, title: str = "New mission", sid: str | None = None, _sync: bool = True) -> str:
        sid = sid or str(uuid.uuid4())
        with self._lock:
            conn = self._conn()
            conn.execute("INSERT OR IGNORE INTO sessions(id,title) VALUES(?,?)", (sid, title))
            conn.commit()
        if _sync:
            self._sync_cloud(sid)
        return sid

    def get_session(self, sid: str):
        with self._lock:
            return self._conn().execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()

    def ensure_session(self, sid: str) -> None:
        if not self.get_session(sid):
            self.create_session("New mission", sid)

    def update_title(self, sid: str, title: str) -> None:
        with self._lock:
            self._conn().execute("UPDATE sessions SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (title[:80], sid))
            self._conn().commit()

    def sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT id,title,created_at,updated_at FROM sessions ORDER BY updated_at DESC, rowid DESC LIMIT 100"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, sid: str) -> None:
        with self._lock:
            c = self._conn()
            for table in ("messages", "task_state", "runs", "mission_events", "receptionist_bookings", "receptionist_messages", "floor_incidents", "floor_shift_notes"):
                c.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
            c.commit()
        if self.cloud and self.cloud.enabled() and not self._restoring_cloud:
            self.cloud.delete(sid)

    # ---------------------------------------------------------------- messages
    def add_message(self, sid: str, role: str, content: str, source: str = "text", metadata: dict[str, Any] | None = None, _sync: bool = True) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO messages(session_id,role,content,source,metadata_json) VALUES(?,?,?,?,?)",
                (sid, role, content, source, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.execute("UPDATE sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (sid,))
            conn.commit()
        if _sync:
            self._sync_cloud(sid)

    def history(self, sid: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT role,content,source,metadata_json,created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (sid, limit),
            ).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r)
            try:
                d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                d["metadata"] = {}
            out.append(d)
        return out

    # -------------------------------------------------------------- task state
    def get_task_state(self, sid: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn().execute("SELECT state_json FROM task_state WHERE session_id=?", (sid,)).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["state_json"])
        except json.JSONDecodeError:
            return {}

    def set_task_state(self, sid: str, state: dict[str, Any], _sync: bool = True) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT INTO task_state(session_id,state_json) VALUES(?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP",
                (sid, json.dumps(state, ensure_ascii=False)),
            )
            self._conn().commit()


    # --------------------------------------------------------------- floorops
    def floor_inventory_count(self) -> int:
        with self._lock:
            r=self._conn().execute("SELECT COUNT(*) AS n FROM floor_inventory").fetchone()
        return int(r["n"] if r else 0)
    def upsert_floor_item(self, sku:str, item_name:str, category:str, quantity:int, reorder_level:int, unit:str="unit") -> None:
        with self._lock:
            self._conn().execute("INSERT INTO floor_inventory(sku,item_name,category,quantity,reorder_level,unit) VALUES(?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET item_name=excluded.item_name,category=excluded.category,quantity=excluded.quantity,reorder_level=excluded.reorder_level,unit=excluded.unit,updated_at=CURRENT_TIMESTAMP", (sku,item_name,category,quantity,reorder_level,unit)); self._conn().commit()
    def get_floor_item(self, sku:str):
        with self._lock:
            r=self._conn().execute("SELECT * FROM floor_inventory WHERE sku=?",(sku,)).fetchone()
        return dict(r) if r else None
    def floor_inventory(self, limit:int=50):
        with self._lock:
            rows=self._conn().execute("SELECT * FROM floor_inventory ORDER BY sku LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]
    def floor_checklist_count(self)->int:
        with self._lock:
            r=self._conn().execute("SELECT COUNT(*) AS n FROM floor_checklists WHERE active=1").fetchone()
        return int(r["n"] if r else 0)
    def add_floor_checklist(self,name:str,instruction:str,active:int=1)->None:
        with self._lock:
            self._conn().execute("INSERT INTO floor_checklists(name,instruction,active) VALUES(?,?,?)",(name,instruction,active)); self._conn().commit()
    def floor_checklists(self,limit:int=50):
        with self._lock:
            rows=self._conn().execute("SELECT * FROM floor_checklists WHERE active=1 ORDER BY id LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]
    def add_floor_incident(self,sid:str,incident_code:str,description:str,status:str='open')->dict:
        with self._lock:
            c=self._conn(); c.execute("INSERT INTO floor_incidents(session_id,incident_code,description,status) VALUES(?,?,?,?)",(sid,incident_code,description,status)); c.commit(); r=c.execute("SELECT * FROM floor_incidents WHERE incident_code=?",(incident_code,)).fetchone()
        return dict(r)
    def add_floor_shift_note(self,note:str,sid:str=''):
        with self._lock:
            c=self._conn(); cur=c.execute("INSERT INTO floor_shift_notes(session_id,note) VALUES(?,?)",(sid,note)); c.commit(); r=c.execute("SELECT * FROM floor_shift_notes WHERE id=?",(cur.lastrowid,)).fetchone()
        return dict(r)
    def floor_incidents(self,limit:int=50):
        with self._lock:
            rows=self._conn().execute("SELECT * FROM floor_incidents ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]
    def floor_shift_notes(self,limit:int=50):
        with self._lock:
            rows=self._conn().execute("SELECT * FROM floor_shift_notes ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- knowledge
    def add_knowledge(self, keywords: str, question: str, explanation: str) -> None:
        """Background self-improvement store. Never called from a request the user is waiting on."""
        with self._lock:
            self._conn().execute(
                "INSERT INTO knowledge(keywords, question, explanation) VALUES(?,?,?)",
                (keywords, question[:500], explanation[:4000]),
            )
            self._conn().commit()

    def search_knowledge(self, keywords: set[str], limit: int = 1, min_overlap: int = 2) -> list[dict[str, Any]]:
        """Cheap keyword-overlap lookup - no embeddings/vector DB needed for a small free-tier store."""
        if not keywords:
            return []
        with self._lock:
            rows = self._conn().execute(
                "SELECT id, keywords, question, explanation, hits FROM knowledge ORDER BY id DESC LIMIT 500"
            ).fetchall()
        scored = []
        for r in rows:
            stored = set(r["keywords"].split(","))
            overlap = len(stored & keywords)
            if overlap >= min_overlap:
                scored.append((overlap, dict(r)))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = [d for _, d in scored[:limit]]
        if hits:
            with self._lock:
                self._conn().executemany("UPDATE knowledge SET hits = hits + 1 WHERE id = ?", [(h["id"],) for h in hits])
                self._conn().commit()
        return hits


    # ----------------------------------------------------------- mission audit
    def add_mission_event(self, sid: str, event_type: str, payload: dict[str, Any] | None = None, label: str = "", _sync: bool = True) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT INTO mission_events(session_id,event_type,label,payload_json) VALUES(?,?,?,?)",
                (sid, event_type, label[:240], json.dumps(payload or {}, ensure_ascii=False)),
            )
            self._conn().commit()
        if _sync:
            self._sync_cloud(sid)

    def mission_events(self, sid: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT id,event_type,label,payload_json,created_at FROM mission_events WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (sid, max(1, min(int(limit), 2000))),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                d["payload"] = {}
            out.append(d)
        return out

    def mission_event_count(self, sid: str) -> int:
        with self._lock:
            row = self._conn().execute("SELECT COUNT(*) AS n FROM mission_events WHERE session_id=?", (sid,)).fetchone()
        return int(row["n"] if row else 0)

    # ---------------------------------------------------------- receptionist
    def booking_slots(self, appointment_date: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT id,confirmation_code,customer_name,service,appointment_date,appointment_time,status,created_at FROM receptionist_bookings WHERE appointment_date=? ORDER BY appointment_time",
                (appointment_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def booking_slots_for_dashboard(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT confirmation_code,customer_name,email,service,appointment_date,appointment_time,status,created_at FROM receptionist_bookings ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),)
            ).fetchall()
        return [dict(r) for r in rows]

    def create_booking(self, sid: str, confirmation_code: str, customer_name: str, phone: str, email: str,
                       service: str, appointment_date: str, appointment_time: str, notes: str = "") -> dict[str, Any]:
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO receptionist_bookings(session_id,confirmation_code,customer_name,phone,email,service,appointment_date,appointment_time,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sid, confirmation_code, customer_name, phone, email, service, appointment_date, appointment_time, "confirmed", notes),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM receptionist_bookings WHERE confirmation_code=?", (confirmation_code,)).fetchone()
        return dict(row)

    def find_booking(self, code: str | None = None, session_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            conn = self._conn()
            if code:
                row = conn.execute("SELECT * FROM receptionist_bookings WHERE confirmation_code=?", (code.upper(),)).fetchone()
            elif session_id:
                row = conn.execute("SELECT * FROM receptionist_bookings WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
            else:
                row = None
        return dict(row) if row else None

    def add_reception_message(self, sid: str, customer_name: str, phone: str, message: str, priority: str = "normal") -> dict[str, Any]:
        with self._lock:
            conn = self._conn()
            cur = conn.execute(
                "INSERT INTO receptionist_messages(session_id,customer_name,phone,message,priority,status) VALUES(?,?,?,?,?,'new')",
                (sid, customer_name, phone, message, priority),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM receptionist_messages WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def receptionist_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT * FROM receptionist_messages ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 500)),)
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------- runs
    def save_run(self, sid: str, plan: dict[str, Any], trace: list[dict[str, Any]]) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT INTO runs(session_id,plan_json,trace_json) VALUES(?,?,?)",
                (sid, json.dumps(plan, ensure_ascii=False), json.dumps(trace, ensure_ascii=False)),
            )
            self._conn().commit()
