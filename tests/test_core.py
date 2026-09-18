import asyncio
import tempfile
from pathlib import Path

from app.db import Database
from app.core import Core
from app.config import settings


def make_core(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    return Core(db), db


def test_conversation_does_not_error(tmp_path):
    core, db = make_core(tmp_path)
    sid = db.create_session()
    result = asyncio.run(core.handle(sid, "mare ghare javu che", "text", "gu"))
    assert result.final.status == "success"
    assert result.plan.intent in {"conversation", "question"}


def test_math_renders_structured_output(tmp_path):
    core, db = make_core(tmp_path)
    sid = db.create_session()
    result = asyncio.run(core.handle(sid, "solve x + 3 = 7", "text", "en"))
    assert result.final.visual_type == "math"
    assert result.final.data


def test_history_is_persistent(tmp_path):
    core, db = make_core(tmp_path)
    sid = db.create_session()
    asyncio.run(core.handle(sid, "hello", "text", "en"))
    asyncio.run(core.handle(sid, "what is 2 + 2?", "text", "en"))
    history = db.history(sid)
    assert len(history) >= 4
