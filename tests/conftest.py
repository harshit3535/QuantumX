import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm.router import LLMRouter  # noqa: E402
from app.memory.db import Database  # noqa: E402
from app.pipeline import Nexus  # noqa: E402


class FakeProvider:
    """A scripted LLM. `script` is a function (system, messages, json_mode) -> str or an exception to raise."""
    name = "fake"

    def __init__(self, script):
        self.script = script
        self.calls: list[dict] = []

    def configured(self) -> bool:
        return True

    async def complete(self, system, messages, *, json_mode=False, temperature=0.3, max_tokens=2048, timeout=30.0):
        self.calls.append({"system": system, "messages": messages, "json_mode": json_mode})
        out = self.script(system, messages, json_mode)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def db(tmp_path):
    return Database(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def offline(db):
    """No AI provider configured at all."""
    return Nexus(db, LLMRouter(providers=[]))


@pytest.fixture
def make_llm(db):
    def factory(script):
        prov = FakeProvider(script)
        return Nexus(db, LLMRouter(providers=[prov])), prov
    return factory
