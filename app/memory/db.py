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
        self._init()

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
                """
            )
            conn.commit()

    # ---------------------------------------------------------------- sessions
    def create_session(self, title: str = "New mission", sid: str | None = None) -> str:
        sid = sid or str(uuid.uuid4())
        with self._lock:
            conn = self._conn()
            conn.execute("INSERT OR IGNORE INTO sessions(id,title) VALUES(?,?)", (sid, title))
            conn.commit()
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
            for table in ("messages", "task_state", "runs"):
                c.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
            c.commit()

    # ---------------------------------------------------------------- messages
    def add_message(self, sid: str, role: str, content: str, source: str = "text", metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO messages(session_id,role,content,source,metadata_json) VALUES(?,?,?,?,?)",
                (sid, role, content, source, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.execute("UPDATE sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (sid,))
            conn.commit()

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

    def set_task_state(self, sid: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT INTO task_state(session_id,state_json) VALUES(?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP",
                (sid, json.dumps(state, ensure_ascii=False)),
            )
            self._conn().commit()

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

    # -------------------------------------------------------------------- runs
    def save_run(self, sid: str, plan: dict[str, Any], trace: list[dict[str, Any]]) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT INTO runs(session_id,plan_json,trace_json) VALUES(?,?,?)",
                (sid, json.dumps(plan, ensure_ascii=False), json.dumps(trace, ensure_ascii=False)),
            )
            self._conn().commit()
