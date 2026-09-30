import asyncio
from app.memory.db import Database
from app.models import ContextBundle, NormalizedRequest
from app.agents.base import AgentContext
from app.agents.floorops_agent import floorops_agent
from app.llm.router import LLMRouter

def make_ctx(db,text):
    req=NormalizedRequest(original_text=text,text=text,language="en",intent_hint="task",workspace="floorops")
    return AgentContext(request=req,context=ContextBundle(session_id="s1",task_state={},db=db),router=LLMRouter(),db=db)

def test_floorops_inventory(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'f.db'}")
    r=asyncio.run(floorops_agent("check SKU-104 stock",make_ctx(db,"check SKU-104 stock")))
    assert r.data["item"]["sku"]=="SKU-104" and "42" in r.text

def test_floorops_incident(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'f.db'}")
    r=asyncio.run(floorops_agent("log incident: conveyor warning light is off",make_ctx(db,"log incident: conveyor warning light is off")))
    assert r.data["outcome"]=="incident_logged" and len(db.floor_incidents())==1

def test_floorops_handoff(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'f.db'}")
    r=asyncio.run(floorops_agent("add shift note: belt needs inspection",make_ctx(db,"add shift note: belt needs inspection")))
    assert r.data["outcome"]=="shift_note_saved" and len(db.floor_shift_notes())==1
