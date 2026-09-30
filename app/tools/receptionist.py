"""Deterministic front-desk tools for the Astra v2.7 hackathon demo."""
from __future__ import annotations
import re
import secrets
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo
from ..config import settings
from ..errors import ToolError

SERVICES = [
    {"id":"consultation","name":"Consultation","duration_min":30,"description":"First conversation or discovery call."},
    {"id":"follow_up","name":"Follow-up","duration_min":30,"description":"Existing-customer follow-up."},
    {"id":"demo","name":"Product demo","duration_min":45,"description":"Guided product walkthrough."},
]
_DAYS = {"monday":0,"mon":0,"tuesday":1,"tue":1,"wednesday":2,"wed":2,"thursday":3,"thu":3,"friday":4,"fri":4,"saturday":5,"sat":5,"sunday":6,"sun":6}

def profile() -> dict[str,Any]:
    return {"business_name":settings.receptionist_business_name,"timezone":settings.receptionist_timezone,"hours":settings.receptionist_hours,"services":SERVICES,"slot_minutes":settings.receptionist_slot_minutes,"confirmation_required":settings.receptionist_confirm_required}

def _tz():
    try: return ZoneInfo(settings.receptionist_timezone)
    except Exception: return ZoneInfo("UTC")

def _now(): return datetime.now(_tz())

def parse_time(text:str)->str|None:
    m=re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",text.lower())
    if not m:return None
    h=int(m.group(1)); minute=int(m.group(2) or 0); mer=(m.group(3) or "").lower()
    if h>23 or minute>59:return None
    if mer=="pm" and h<12:h+=12
    if mer=="am" and h==12:h=0
    if not mer and h<8:h+=12
    return f"{h:02d}:{minute:02d}"

def parse_date(text:str, now:datetime|None=None)->str|None:
    now=now or _now(); low=text.lower()
    if "day after tomorrow" in low or "પરમદિવસ" in low:return (now.date()+timedelta(days=2)).isoformat()
    if "tomorrow" in low or "કાલે" in low or "कल" in low:return (now.date()+timedelta(days=1)).isoformat()
    if "today" in low or "આજે" in low or "आज" in low:return now.date().isoformat()
    m=re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",text)
    if m:
        try:return date(int(m.group(1)),int(m.group(2)),int(m.group(3))).isoformat()
        except ValueError:return None
    m=re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b",text)
    if m:
        try:return date(int(m.group(3) or now.year),int(m.group(1)),int(m.group(2))).isoformat()
        except ValueError:return None
    for word,wd in _DAYS.items():
        if re.search(rf"\b{re.escape(word)}\b",low):
            delta=(wd-now.weekday())%7
            if delta==0 and re.search(r"next\s+"+re.escape(word),low):delta=7
            return (now.date()+timedelta(days=delta)).isoformat()
    return None

def service_for(text:str)->dict[str,Any]|None:
    low=text.lower()
    if "demo" in low or "walkthrough" in low:return SERVICES[2]
    if "follow up" in low or "follow-up" in low:return SERVICES[1]
    if "consultation" in low or "consult" in low or "discovery" in low or "appointment" in low:return SERVICES[0]
    return None

def extract_booking_fields(text:str,draft:dict[str,Any]|None=None)->dict[str,Any]:
    out=dict(draft or {})
    d=parse_date(text); t=parse_time(text); svc=service_for(text)
    if d:out["date"]=d
    if t:out["time"]=t
    if svc:out["service_id"]=svc["id"]
    m=re.search(r"(?:my name is|i am|i'm|name is)\s+([A-Za-z][A-Za-z .'-]{1,60})",text,re.I)
    if m:out["customer_name"]=re.split(r"\b(?:and|at|on|for|tomorrow|today|next)\b",m.group(1).strip(" .,-"),flags=re.I)[0].strip()
    m=re.search(r"(?:maru naam|મારું નામ|मेरा नाम)\s+([A-Za-z][A-Za-z .'-]{1,60})",text,re.I)
    if m:out["customer_name"]=m.group(1).strip(" .,-")
    em=re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",text,re.I)
    if em:out["email"]=em.group(0)
    pm=re.search(r"(?:phone|mobile|call me|number|મોબાઇલ|ફોન|मोबाइल|फोन)\D{0,8}((?:\+?91[-\s]?)?[6-9]\d{9})\b",text,re.I)
    if pm:out["phone"]=re.sub(r"\D", "", pm.group(1))
    return out

def _window(day:date): return (time(9,0),time(17,0)) if day.weekday()<5 else None

def availability(db:Any,appointment_date:str,service_id:str="consultation")->dict[str,Any]:
    try:day=date.fromisoformat(appointment_date)
    except ValueError:raise ToolError("Please provide a valid appointment date.",kind="invalid_date",recoverable=True)
    w=_window(day)
    if not w:return {"date":appointment_date,"available":False,"reason":"The front desk is closed on weekends.","slots":[]}
    duration=next((x["duration_min"] for x in SERVICES if x["id"]==service_id),30); step=settings.receptionist_slot_minutes
    occupied={r["appointment_time"] for r in db.booking_slots(appointment_date) if r.get("status")!="cancelled"}
    slots=[]; cur=datetime.combine(day,w[0],tzinfo=_tz()); end=datetime.combine(day,w[1],tzinfo=_tz()); min_dt=_now()+timedelta(minutes=settings.receptionist_min_notice_minutes)
    while cur<end:
        finish=cur+timedelta(minutes=duration)
        if finish<=end and cur.strftime("%H:%M") not in occupied and cur>min_dt: slots.append(cur.strftime("%H:%M"))
        cur+=timedelta(minutes=step)
    return {"date":appointment_date,"available":bool(slots),"slots":slots,"occupied":sorted(occupied),"service_id":service_id}

def check_slot(db:Any,appointment_date:str,appointment_time:str,service_id:str="consultation"):
    av=availability(db,appointment_date,service_id)
    return (appointment_time in av.get("slots",[]),av.get("slots",[])[:3])

def book(db:Any,sid:str,draft:dict[str,Any])->dict[str,Any]:
    ok,_=check_slot(db,draft["date"],draft["time"],draft.get("service_id","consultation"))
    if not ok:raise ToolError("That slot is no longer available.",kind="slot_unavailable",recoverable=True)
    service=next(x for x in SERVICES if x["id"]==draft.get("service_id","consultation"))
    return db.create_booking(sid,"AST-"+secrets.token_hex(3).upper(),draft["customer_name"],draft.get("phone",""),draft.get("email",""),service["name"],draft["date"],draft["time"],draft.get("notes",""))

def lookup(db:Any,code:str|None=None,session_id:str|None=None):return db.find_booking(code=code,session_id=session_id)

def take_message(db:Any,sid:str,customer_name:str,message:str,phone:str="",priority:str="normal"):
    if not message.strip():raise ToolError("Please tell me the message to pass on.",kind="message_missing",recoverable=True)
    return db.add_reception_message(sid,customer_name,phone,message.strip(),priority)
