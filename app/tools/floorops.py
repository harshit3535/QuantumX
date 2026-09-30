"""Voice-first warehouse/factory floor operations tools for Astra."""
from __future__ import annotations
import re, uuid
from typing import Any
from ..config import settings

DEFAULT_ITEMS=[
 ('SKU-104','Safety gloves','PPE',42,12,'pair'),
 ('SKU-207','Bearing kit','Maintenance',18,5,'kit'),
 ('SKU-311','Hydraulic hose','Maintenance',7,3,'unit'),
 ('SKU-502','Packing tape','Packaging',96,20,'roll'),
]
DEFAULT_CHECKLIST=[
 ('Machine start','Verify guards, emergency stop, warning lights, and work area.',1),
 ('Forklift pre-check','Verify tires, horn, brakes, forks, and battery/fuel.',1),
 ('End of shift','Record incidents, stock movements, and outstanding tasks.',1),
]

def seed(db:Any):
    if db.floor_inventory_count()==0:
        for row in DEFAULT_ITEMS: db.upsert_floor_item(*row)
    if db.floor_checklist_count()==0:
        for row in DEFAULT_CHECKLIST: db.add_floor_checklist(*row)

def _item(task:str):
    m=re.search(r'\bSKU[- ]?(\d{3})\b',task,re.I)
    return f"SKU-{m.group(1)}" if m else None

def inventory(db:Any, task:str):
    seed(db); sku=_item(task)
    if sku:
        return {'tool':'inventory_lookup','item':db.get_floor_item(sku)}
    return {'tool':'inventory_list','items':db.floor_inventory(limit=20)}

def checklist(db:Any):
    seed(db); return {'tool':'safety_checklist','items':db.floor_checklists(limit=20)}

def incident(db:Any, task:str):
    m=re.search(r'(?:incident|issue|problem|fault|alert|log)\s*[:,-]?\s*(.+)',task,re.I|re.S)
    desc=(m.group(1).strip() if m else task.strip())[:1000]
    rec=db.add_floor_incident(str(uuid.uuid4())[:8].upper(),desc,'open')
    return {'tool':'incident_log','incident':rec}

def shift_note(db:Any, task:str, sid:str):
    note=re.sub(r'^(?:add|create|log|write|save)\s+(?:a\s+)?(?:shift\s+)?(?:note|handoff)\s*[:,-]?','',task,flags=re.I).strip()[:1200]
    return {'tool':'shift_handoff','note':db.add_floor_shift_note(note,sid)}
