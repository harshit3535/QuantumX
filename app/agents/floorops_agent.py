"""Astra FloorOps: voice-first warehouse/factory floor operator."""
from __future__ import annotations
import re
from ..models import AgentResult, Segment
from ..tools.floorops import inventory, checklist, incident, shift_note, seed
from .base import AgentContext
_INV=re.compile(r'\b(stock|inventory|sku|how many|quantity|available units|પસાર|સ્ટોક|ઇન્વેન્ટરી|सामान|स्टॉक)\b',re.I)
_CHECK=re.compile(r'\b(safety checklist|machine checklist|pre.?check|safety check|checklist|સેફ્ટી|ચેકલિસ્ટ|सुरक्षा|चेकलिस्ट)\b',re.I)
_INC=_INCIDENT_WORDS=re.compile(r'\b(incident|issue|problem|fault|warning|alert|broken|not working|unsafe|log this|report this|ઇન્સિડન્ટ|સમસ્યા|ખામી|સેફ્ટી|incident log|दिक्कत|खराब|unsafe)\b',re.I)
_SHIFT=re.compile(r'\b(shift handoff|shift note|handoff|end of shift|log a note|add a note)\b|હેન્ડઓફ|નોટ|हैंडऑफ|नोट',re.I)

def _say(ctx,en,gu,hi):
    return {'en':en,'gu':gu,'hi':hi}.get(ctx.request.language,en)

async def floorops_agent(task:str,ctx:AgentContext)->AgentResult:
    db=ctx.db or getattr(ctx.context,'db',None)
    if db is None: raise RuntimeError('FloorOps persistence is unavailable')
    low=task.lower(); seed(db)
    if _INV.search(task):
        r=inventory(db,task); item=r.get('item')
        if item:
            text=_say(ctx,f"{item['sku']} has {item['quantity']} {item['unit']} on hand; reorder level is {item['reorder_level']}.",f"{item['sku']} માં {item['quantity']} {item['unit']} stock છે અને reorder level {item['reorder_level']} છે.",f"{item['sku']} में {item['quantity']} {item['unit']} stock है और reorder level {item['reorder_level']} है।")
        else:
            text=_say(ctx,f"I found {len(r['items'])} tracked inventory items.",f"મને {len(r['items'])} inventory items મળ્યા.",f"मुझे {len(r['items'])} inventory items मिले।")
        return AgentResult(agent='floorops_agent',segments=[Segment(type='text',content=text)],spoken=text,data={**r,'evidence':[{'type':'inventory','label':'Inventory record','value':str(item['sku'] if item else len(r['items']))}]})
    if _CHECK.search(task):
        r=checklist(db); text=_say(ctx,f"I loaded {len(r['items'])} safety checklists. Tell me 'start' and I’ll walk you through them one by one.",f"મેં {len(r['items'])} safety checklists લોડ કરી છે. 'start' કહો અને હું એક પછી એક કરાવીશ.",f"मैंने {len(r['items'])} safety checklists लोड की हैं। 'start' कहें, मैं एक-एक करके कराऊँगा।")
        return AgentResult(agent='floorops_agent',segments=[Segment(type='text',content=text)],spoken=text,data={**r,'evidence':[{'type':'checklist','label':'Safety checklist','value':str(len(r['items']))+' steps'}]})
    if _INC.search(task):
        r=incident(db,task); text=_say(ctx,f"Incident logged as {r['incident']['incident_code']}. It is open for follow-up.",f"Incident {r['incident']['incident_code']} તરીકે log થયો છે અને follow-up માટે open છે.",f"Incident {r['incident']['incident_code']} के रूप में log हो गया है और follow-up के लिए open है।")
        return AgentResult(agent='floorops_agent',segments=[Segment(type='text',content=text)],spoken=text,data={**r,'evidence':[{'type':'incident','label':'Incident record','value':r['incident']['incident_code']}],'outcome':'incident_logged'})
    if _SHIFT.search(task):
        r=shift_note(db,task,ctx.context.session_id); text=_say(ctx,'Shift note saved for handoff.','Shift note handoff માટે save થઈ ગઈ.','Shift note handoff के लिए save हो गई।')
        return AgentResult(agent='floorops_agent',segments=[Segment(type='text',content=text)],spoken=text,data={**r,'evidence':[{'type':'handoff','label':'Shift note','value':str(r['note']['id'])}],'outcome':'shift_note_saved'})
    text=_say(ctx,'I’m FloorOps. I can check stock, run safety checklists, log incidents, and save shift handoff notes.','હું FloorOps છું. હું stock ચેક, safety checklist, incident log અને shift handoff કરી શકું છું.','मैं FloorOps हूँ। मैं stock check, safety checklist, incident log और shift handoff कर सकता हूँ।')
    return AgentResult(agent='floorops_agent',segments=[Segment(type='text',content=text)],spoken=text,data={'tool':'floorops_help'})
