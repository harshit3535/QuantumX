"""Astra Front Desk / AI receptionist agent."""
from __future__ import annotations
import re
from datetime import datetime
from ..config import settings
from ..models import AgentResult,Segment
from ..tools.receptionist import SERVICES,availability,book,extract_booking_fields,lookup,profile,take_message
from .base import AgentContext
_AFFIRM=re.compile(r"\b(yes|yeah|yep|sure|confirm|confirmed|do it|book it|go ahead|okay|ok|haan|હા|બરાબર|हाँ|कर दीजिए)\b",re.I)
_NEGATE=re.compile(r"\b(no|nope|cancel|don't|do not|stop|not now|નહીં|ના|રદ્દ|नहीं|रद्द)\b",re.I)
_BOOK=re.compile(r"\b(book|schedule|appointment|reserve|slot|availability|available|meeting|consultation|demo)\b|બુક|અપોઇન્ટમેન્ટ|સમય|स्लॉट|अपॉइंटમેન્ટ|बुक",re.I)
_MESSAGE=re.compile(r"\b(leave a message|take a message|tell them|pass on a message|callback|call me back)\b|મેસેજ|સંદેશ|message",re.I)
_HOURS=re.compile(r"\b(hours|opening hours|working hours|open|close|when are you open)\b|ક્યારે ખુલ્લું|સમય|घंटे|कब खुले",re.I)
_LOOKUP=re.compile(r"\b(confirmation|booking code|appointment status|my appointment|look up.*appointment)\b|કન્ફર્મેશન|बुकिंग|अपॉइंटमेंट",re.I)

def lang(ctx):return ctx.request.language if ctx.request.language in {"gu","hi"} else "en"
def say(ctx,en,gu,hi):return {"en":en,"gu":gu,"hi":hi}[lang(ctx)]
def fd(v):
    try:return datetime.fromisoformat(v).strftime("%A, %d %b %Y")
    except:return v
def ft(v):
    try:return datetime.strptime(v,"%H:%M").strftime("%I:%M %p").lstrip("0")
    except:return v

async def receptionist_agent(task:str,ctx:AgentContext)->AgentResult:
    db=ctx.db or getattr(ctx.context,"db",None)
    if db is None:raise RuntimeError("Receptionist persistence is unavailable")
    state=dict(ctx.context.task_state or {});pending=state.get("pending_action");draft=extract_booking_fields(task,state.get("draft_booking"))
    if pending and _AFFIRM.search(task):
        booking=book(db,ctx.context.session_id,dict(pending.get("payload",{})))
        spoken=say(ctx,f"Booked. Your {booking['service']} is confirmed for {fd(booking['appointment_date'])} at {ft(booking['appointment_time'])}. Your confirmation code is {booking['confirmation_code']}.",f"બુકિંગ થઈ ગયું. તમારું {booking['service']} {fd(booking['appointment_date'])} ના {ft(booking['appointment_time'])} માટે confirm છે. Confirmation code {booking['confirmation_code']} છે.",f"बुक हो गया। आपका {booking['service']} {fd(booking['appointment_date'])} को {ft(booking['appointment_time'])} पर confirm है। Confirmation code {booking['confirmation_code']} है।")
        return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=spoken)],spoken=spoken,data={"tool":"book_appointment","booking":booking,"evidence":[{"type":"booking","label":"Confirmed appointment","value":f"{booking['service']} · {booking['appointment_date']} · {booking['appointment_time']} · {booking['confirmation_code']}"}],"clear_pending_action":True,"clear_draft_booking":True,"outcome":"appointment_scheduled"})
    if pending and _NEGATE.search(task):
        text=say(ctx,"Okay. I cancelled the pending booking action. Nothing was saved.","બરાબર. મેં pending booking action cancel કરી દીધું. કંઈ save થયું નથી.","ठीक है। मैंने pending booking action रद्द कर दिया है। कुछ भी save नहीं किया गया।")
        return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=text)],data={"clear_pending_action":True,"clear_draft_booking":True,"outcome":"booking_not_saved"})
    if _LOOKUP.search(task) and not _BOOK.search(task):
        m=re.search(r"\b([A-Z]{3}-[0-9A-F]{6})\b",task,re.I);rec=lookup(db,code=m.group(1) if m else None,session_id=ctx.context.session_id)
        if not rec:
            text=say(ctx,"I couldn't find an appointment for this session.","આ session માટે કોઈ appointment મળ્યો નથી.","इस session के लिए कोई appointment नहीं मिला।")
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=text)],data={"tool":"lookup_appointment","found":False})
        text=say(ctx,f"I found {rec['service']} for {rec['customer_name']} on {fd(rec['appointment_date'])} at {ft(rec['appointment_time'])}. Confirmation code {rec['confirmation_code']}.",f"મને {rec['customer_name']} માટે {rec['service']} નું booking {fd(rec['appointment_date'])} ના {ft(rec['appointment_time'])} માટે મળ્યું. Confirmation code {rec['confirmation_code']} છે.",f"मुझे {rec['customer_name']} की {rec['service']} booking {fd(rec['appointment_date'])} को {ft(rec['appointment_time'])} पर मिली। Confirmation code {rec['confirmation_code']} है।")
        return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=text)],spoken=text,data={"tool":"lookup_appointment","booking":rec,"evidence":[{"type":"booking","label":"Appointment record","value":rec["confirmation_code"]}]})
    if _HOURS.search(task) and not _BOOK.search(task):
        text=say(ctx,f"We're open {profile()['hours']}. Appointments use the {profile()['timezone']} timezone.",f"અમે {profile()['hours']} ખુલ્લા છીએ. Appointment {profile()['timezone']} timezone મુજબ થાય છે.",f"हम {profile()['hours']} खुले रहते हैं। Appointments {profile()['timezone']} timezone के अनुसार होते हैं।")
        return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=text)],spoken=text,data={"tool":"front_desk_info","evidence":[{"type":"policy","label":"Business hours","value":profile()['hours']}]})
    if _MESSAGE.search(task) and not _BOOK.search(task):
        msg=re.sub(r".*?(?:leave a message|take a message|tell them|pass on a message|message|સંદેશ|મેસેજ|संदेश)\s*[:,-]?","",task,flags=re.I).strip();name="Visitor";m=re.search(r"(?:my name is|name is|i'm)\s+([A-Za-z][A-Za-z .'-]{1,50})",task,re.I)
        if m:name=m.group(1).strip()
        if not msg:
            q=say(ctx,"What message would you like me to pass to the team?","ટીમને કયો message આપવો છે?","टीम को कौन-सा संदेश देना है?")
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=q)],data={"needs_input":"message"})
        rec=take_message(db,ctx.context.session_id,name,msg);text=say(ctx,"Done. I took the message and marked it for the team.","થઈ ગયું. મેં message લઈ લીધો અને team માટે mark કર્યો છે.","हो गया। मैंने संदेश ले लिया है और टीम के लिए mark कर दिया है।")
        return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=text)],spoken=text,data={"tool":"take_message","message":rec,"evidence":[{"type":"message","label":"Front-desk message","value":f"#{rec['id']} · {rec['priority']}"}],"outcome":"message_captured"})
    if _BOOK.search(task):
        if not draft.get("date"):
            q=say(ctx,"What day would you like the appointment?","કયા દિવસે appointment જોઈએ?","किस दिन appointment चाहिए?")
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=q)],data={"needs_input":"date","draft_booking":draft})
        if not draft.get("time"):
            q=say(ctx,f"What time should I check for {fd(draft['date'])}?",f"{fd(draft['date'])} માટે કયો સમય ચેક કરું?",f"{fd(draft['date'])} के लिए कौन-सा समय चेक करूँ?")
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=q)],data={"needs_input":"time","draft_booking":draft})
        if not draft.get("customer_name"):
            q=say(ctx,"What name should I put on the appointment?","Appointment પર કયું નામ લખું?","Appointment किस नाम पर रखना है?")
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=q)],data={"needs_input":"customer_name","draft_booking":draft})
        svc=draft.get("service_id","consultation");av=availability(db,draft["date"],svc)
        if draft["time"] not in av.get("slots",[]):
            alt=", ".join(ft(x) for x in av.get("slots",[])[:3]) or "no nearby slots";q=say(ctx,f"That time isn't available. The next options are {alt}. Which one should I use?",f"એ સમય available નથી. આગળના options {alt} છે. કયો પસંદ કરું?",f"वह समय उपलब्ध नहीं है। अगले options {alt} हैं। कौन-सा लें?");draft["alternatives"]=av.get("slots",[])[:5]
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=q)],data={"tool":"check_availability","needs_input":"time","draft_booking":draft,"evidence":[{"type":"availability","label":"Available slots","value":alt}]})
        service=next(x for x in SERVICES if x["id"]==svc);proposal=dict(draft)
        if settings.receptionist_confirm_required:
            spoken=say(ctx,f"I found an opening for a {service['name']} on {fd(draft['date'])} at {ft(draft['time'])} for {draft['customer_name']}. Shall I confirm the appointment?",f"{draft['customer_name']} માટે {service['name']} નો slot {fd(draft['date'])} ના {ft(draft['time'])}એ available છે. Appointment confirm કરું?",f"{draft['customer_name']} के लिए {service['name']} का slot {fd(draft['date'])} को {ft(draft['time'])} पर उपलब्ध है। Appointment confirm कर दूँ?")
            return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=spoken)],spoken=spoken,data={"tool":"check_availability","approval_required":True,"pending_action":{"kind":"book_appointment","label":f"Book {service['name']}","payload":proposal},"draft_booking":proposal,"evidence":[{"type":"availability","label":"Slot verified","value":f"{fd(draft['date'])} · {ft(draft['time'])}"}]})
    text=say(ctx,"I'm the front desk. I can book an appointment, check availability, look up a booking, or take a message. What would you like me to handle?","હું front desk છું. હું appointment book કરી શકું, availability ચેક કરી શકું, booking શોધી શકું અથવા message લઈ શકું. શું handle કરું?","मैं front desk हूँ। मैं appointment book कर सकता हूँ, availability check कर सकता हूँ, booking ढूँढ सकता हूँ या message ले सकता हूँ। क्या करना है?")
    return AgentResult(agent="receptionist_agent",segments=[Segment(type="text",content=text)],spoken=text,data={"tool":"front_desk_info"})
