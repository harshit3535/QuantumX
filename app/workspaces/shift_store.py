from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "workspaces"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "voiceshift.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ShiftStore:
    def __init__(self) -> None:
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS handovers (
                    id TEXT PRIMARY KEY,
                    shift TEXT NOT NULL,
                    area TEXT NOT NULL,
                    employee TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS issues (
                    id TEXT PRIMARY KEY,
                    handover_id TEXT,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(handover_id) REFERENCES handovers(id)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    handover_id TEXT,
                    task TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(handover_id) REFERENCES handovers(id)
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    handover_id TEXT,
                    category TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(handover_id) REFERENCES handovers(id)
                );
                """
            )
            if self.db.execute("SELECT COUNT(*) FROM handovers").fetchone()[0] == 0:
                self._seed()

    def _seed(self) -> None:
        h_id = "HO-1001"
        created = now_iso()
        self.db.execute(
            "INSERT INTO handovers VALUES (?, ?, ?, ?, ?, ?)",
            (h_id, "Morning", "Warehouse", "Ravi", "12 pallets received. Conveyor 2 has intermittent noise. Evening dispatch at 18:30. Verify barcode scanner before dispatch.", created),
        )
        self.db.execute(
            "INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ISS-1001", h_id, "Conveyor 2 intermittent noise", "medium", "open", "Maintenance", created),
        )
        self.db.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("TASK-1001", h_id, "Verify barcode scanner before 18:30 dispatch", "high", "open", "Evening Shift", created),
        )
        self.db.execute(
            "INSERT INTO notes VALUES (?, ?, ?, ?, ?)",
            ("NOTE-1001", h_id, "dispatch", "Evening dispatch scheduled for 18:30", created),
        )
        self.db.commit()

    def create_handover(self, *, shift: str, area: str, employee: str, summary: str, issues: list[dict[str, Any]] | None = None, tasks: list[dict[str, Any]] | None = None, notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        h_id = f"HO-{datetime.now().strftime('%H%M%S')}-{uuid4().hex[:4].upper()}"
        created = now_iso()
        issues = issues or []
        tasks = tasks or []
        notes = notes or []
        with self.db:
            self.db.execute("INSERT INTO handovers VALUES (?, ?, ?, ?, ?, ?)", (h_id, shift, area, employee or "Unknown", summary, created))
            for item in issues:
                i_id = f"ISS-{uuid4().hex[:6].upper()}"
                self.db.execute("INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?)", (i_id, h_id, item.get("title", "Operational issue"), item.get("severity", "medium"), "open", item.get("owner"), created))
            for item in tasks:
                t_id = f"TASK-{uuid4().hex[:6].upper()}"
                self.db.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)", (t_id, h_id, item.get("task", "Follow-up task"), item.get("priority", "medium"), "open", item.get("owner"), created))
            for item in notes:
                n_id = f"NOTE-{uuid4().hex[:6].upper()}"
                self.db.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?)", (n_id, h_id, item.get("category", "general"), item.get("text", ""), created))
        return self.get_handover(h_id)

    def get_handover(self, h_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM handovers WHERE id = ?", (h_id,)).fetchone()
        if not row:
            return {"ok": False, "message": "Handover not found."}
        return {
            "ok": True,
            "handover": dict(row),
            "issues": [dict(r) for r in self.db.execute("SELECT * FROM issues WHERE handover_id = ? ORDER BY created_at", (h_id,))],
            "tasks": [dict(r) for r in self.db.execute("SELECT * FROM tasks WHERE handover_id = ? ORDER BY created_at", (h_id,))],
            "notes": [dict(r) for r in self.db.execute("SELECT * FROM notes WHERE handover_id = ? ORDER BY created_at", (h_id,))],
        }

    def latest_handover(self, area: str = "") -> dict[str, Any]:
        if area:
            row = self.db.execute("SELECT id FROM handovers WHERE lower(area)=lower(?) ORDER BY created_at DESC LIMIT 1", (area,)).fetchone()
        else:
            row = self.db.execute("SELECT id FROM handovers ORDER BY created_at DESC LIMIT 1").fetchone()
        return self.get_handover(row[0]) if row else {"ok": False, "message": "No handovers found."}

    def list_handover(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM handovers ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 20)),)).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str) -> dict[str, Any]:
        q = f"%{query.strip()}%"
        handovers = [dict(r) for r in self.db.execute("SELECT * FROM handovers WHERE summary LIKE ? OR area LIKE ? OR employee LIKE ? ORDER BY created_at DESC LIMIT 10", (q, q, q))]
        issues = [dict(r) for r in self.db.execute("SELECT * FROM issues WHERE title LIKE ? OR status LIKE ? ORDER BY created_at DESC LIMIT 10", (q, q))]
        tasks = [dict(r) for r in self.db.execute("SELECT * FROM tasks WHERE task LIKE ? OR status LIKE ? ORDER BY created_at DESC LIMIT 10", (q, q))]
        return {"ok": True, "query": query, "handovers": handovers, "issues": issues, "tasks": tasks}

    def open_items(self) -> dict[str, Any]:
        issues = [dict(r) for r in self.db.execute("SELECT * FROM issues WHERE status='open' ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at DESC")]
        tasks = [dict(r) for r in self.db.execute("SELECT * FROM tasks WHERE status='open' ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at DESC")]
        return {"ok": True, "issues": issues, "tasks": tasks}

    def close_item(self, item_type: str, item_id: str) -> dict[str, Any]:
        if item_type == "issue":
            r = self.db.execute("UPDATE issues SET status='closed' WHERE id=?", (item_id,))
            table = "issue"
        elif item_type == "task":
            r = self.db.execute("UPDATE tasks SET status='done' WHERE id=?", (item_id,))
            table = "task"
        else:
            return {"ok": False, "message": "item_type must be issue or task."}
        self.db.commit()
        if r.rowcount != 1:
            return {"ok": False, "message": f"{table.title()} {item_id} not found."}
        return {"ok": True, "message": f"{table.title()} {item_id} updated successfully."}

    def snapshot(self) -> dict[str, Any]:
        open_issues = self.db.execute("SELECT COUNT(*) FROM issues WHERE status='open'").fetchone()[0]
        open_tasks = self.db.execute("SELECT COUNT(*) FROM tasks WHERE status='open'").fetchone()[0]
        handover_count = self.db.execute("SELECT COUNT(*) FROM handovers").fetchone()[0]
        high_priority = self.db.execute("SELECT COUNT(*) FROM tasks WHERE status='open' AND priority='high'").fetchone()[0] + self.db.execute("SELECT COUNT(*) FROM issues WHERE status='open' AND severity='high'").fetchone()[0]
        return {
            "ok": True,
            "metrics": {"open_issues": open_issues, "open_tasks": open_tasks, "handovers": handover_count, "urgent_items": high_priority},
            "latest": self.latest_handover(),
            "recent": self.list_handover(6),
            "open": self.open_items(),
        }

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "create_handover":
            return self.create_handover(
                shift=str(arguments.get("shift", "Unknown")),
                area=str(arguments.get("area", "General")),
                employee=str(arguments.get("employee", "")),
                summary=str(arguments.get("summary", "")),
                issues=arguments.get("issues") if isinstance(arguments.get("issues"), list) else [],
                tasks=arguments.get("tasks") if isinstance(arguments.get("tasks"), list) else [],
                notes=arguments.get("notes") if isinstance(arguments.get("notes"), list) else [],
            )
        if tool == "get_latest_handover":
            return self.latest_handover(str(arguments.get("area", "")))
        if tool == "list_open_items":
            return self.open_items()
        if tool == "search_handover":
            return self.search(str(arguments.get("query", "")))
        if tool == "close_item":
            return self.close_item(str(arguments.get("item_type", "")), str(arguments.get("item_id", "")))
        if tool == "get_shift_summary":
            payload = self.latest_handover(str(arguments.get("area", "")))
            if not payload.get("ok"):
                return payload
            h = payload["handover"]
            return {"ok": True, "message": "Shift summary loaded.", "summary": {
                "handover_id": h["id"], "shift": h["shift"], "area": h["area"], "employee": h["employee"], "summary": h["summary"],
                "issues": payload["issues"], "tasks": payload["tasks"], "notes": payload["notes"]}}
        return {"ok": False, "message": f"Unknown tool: {tool}"}
