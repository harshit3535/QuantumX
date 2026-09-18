from __future__ import annotations

import json
import os
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init()

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init(self):
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()

    def create_session(self, title: str = "New mission") -> str:
        sid = str(uuid.uuid4())
        conn = self._conn()
        conn.execute("INSERT INTO sessions(id,title) VALUES(?,?)", (sid, title))
        conn.commit()
        return sid

    def get_session(self, sid: str):
        return self._conn().execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()

    def update_title(self, sid: str, title: str):
        self._conn().execute(
            "UPDATE sessions SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (title[:80], sid),
        )
        self._conn().commit()

    def add_message(self, sid: str, role: str, content: str, source: str = "text", metadata: dict[str, Any] | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO messages(session_id,role,content,source,metadata_json) VALUES(?,?,?,?,?)",
            (sid, role, content, source, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        conn.execute("UPDATE sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (sid,))
        conn.commit()

    def history(self, sid: str, limit: int = 30):
        rows = self._conn().execute(
            "SELECT role,content,source,metadata_json,created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (sid, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def save_run(self, sid: str, plan: dict[str, Any], results: list[dict[str, Any]]):
        self._conn().execute(
            "INSERT INTO runs(session_id,plan_json,results_json) VALUES(?,?,?)",
            (sid, json.dumps(plan, ensure_ascii=False), json.dumps(results, ensure_ascii=False)),
        )
        self._conn().commit()

    def sessions(self):
        rows = self._conn().execute(
            "SELECT id,title,created_at,updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
