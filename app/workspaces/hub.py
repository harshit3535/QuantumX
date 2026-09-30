from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..config import settings
from ..llm.jsonutil import extract_json
from ..models import AgentResult, Segment
from ..response.parser import markdown_to_segments
from ..agents.base import AgentContext
from .shift_store import ShiftStore
from .pilot_store import PilotStore
from .bridge_store import BridgeStore
from .ops_store import OpsStore

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DATA = ROOT / "data" / "workspaces"
WORKSPACE_DATA.mkdir(parents=True, exist_ok=True)

WORKSPACES = {
    "shift": {"label": "VoiceShift", "description": "Shift handover and operational continuity"},
    "pilot": {"label": "VoicePilot", "description": "Reception, drive memory, reminders, expenses and maintenance"},
    "bridge": {"label": "VoiceBridge", "description": "Emergency guidance, farm assistance and voice forms"},
    "ops": {"label": "VoiceOps", "description": "Restaurant ordering, inventory, checklists and floor operations"},
}

SHIFT_TOOLS = {"create_handover", "get_shift_summary", "get_latest_handover", "list_open_items", "search_handover", "close_item"}
PILOT_TOOLS = {
    "business_info", "list_services", "list_providers", "available_slots", "prepare_booking", "book_appointment",
    "cancel_appointment", "reschedule_appointment", "add_waitlist", "list_waitlist", "create_callback", "list_callbacks",
    "set_reminder", "list_reminders", "save_note", "recent_notes", "save_parking", "get_parking", "log_expense",
    "expense_total", "log_maintenance", "list_maintenance", "calculate",
}
BRIDGE_TOOLS = {"emergency_steps", "log_incident", "get_weather", "crop_advice", "log_farm", "recent_farm_logs", "market_price", "list_forms", "start_form", "set_form_answer", "validate_form", "preview_form", "submit_form"}
OPS_TOOLS = {"search_menu", "create_order_draft", "add_order_item", "set_customer", "confirm_order", "check_inventory", "record_stock_count", "get_checklist", "log_issue"}


def _pilot_settings() -> Any:
    return SimpleNamespace(
        timezone=os.getenv("TIMEZONE", "Asia/Kolkata"),
        data_path=str(WORKSPACE_DATA / "voicepilot.db"),
        business_name=os.getenv("BUSINESS_NAME", settings.receptionist_business_name),
        business_phone=os.getenv("BUSINESS_PHONE", "+91 00000 00000"),
        business_address=os.getenv("BUSINESS_ADDRESS", "Main Road, Gujarat"),
        business_hours=os.getenv("BUSINESS_HOURS", settings.receptionist_hours),
    )


def _bridge_settings() -> Any:
    return SimpleNamespace(
        emergency_number=os.getenv("EMERGENCY_NUMBER", ""),
        farm_lat=float(os.getenv("FARM_LAT", "23.0225")),
        farm_lon=float(os.getenv("FARM_LON", "72.5714")),
        farm_location=os.getenv("FARM_LOCATION", "Ahmedabad, Gujarat"),
        business_name=os.getenv("BUSINESS_NAME", settings.receptionist_business_name),
        business_phone=os.getenv("BUSINESS_PHONE", "+91 00000 00000"),
        business_address=os.getenv("BUSINESS_ADDRESS", "Main Road, Gujarat"),
        business_hours=os.getenv("BUSINESS_HOURS", settings.receptionist_hours),
        database_path=str(WORKSPACE_DATA / "voicebridge.db"),
    )


class WorkspaceHub:
    def __init__(self) -> None:
        self.stores = {
            "shift": ShiftStore(),
            "pilot": PilotStore(_pilot_settings()),
            "bridge": BridgeStore(_bridge_settings()),
            "ops": OpsStore(),
        }

    def metadata(self) -> list[dict[str, Any]]:
        out = []
        for key, meta in WORKSPACES.items():
            tools = sorted(self._tools_for(key))
            out.append({"id": key, **meta, "tools": tools})
        return out

    def _tools_for(self, workspace: str) -> set[str]:
        return {"shift": SHIFT_TOOLS, "pilot": PILOT_TOOLS, "bridge": BRIDGE_TOOLS, "ops": OPS_TOOLS}.get(workspace, set())

    def state(self, workspace: str) -> dict[str, Any]:
        if workspace not in self.stores:
            return {"ok": False, "message": "Unknown workspace."}
        return self.stores[workspace].snapshot()

    def _tool_schema(self, name: str, desc: str, props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "function", "name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required or []}}

    def tools(self, workspace: str) -> list[dict[str, Any]]:
        f = self._tool_schema
        if workspace == "shift":
            return [
                f("create_handover", "Persist a shift handover with issues, tasks and notes.", {"shift":{"type":"string"},"area":{"type":"string"},"employee":{"type":"string"},"summary":{"type":"string"},"issues":{"type":"array"},"tasks":{"type":"array"},"notes":{"type":"array"}}, ["shift","area","summary"]),
                f("get_shift_summary", "Get the latest saved shift summary.", {"area":{"type":"string"}}),
                f("get_latest_handover", "Get the latest saved handover record.", {"area":{"type":"string"}}),
                f("list_open_items", "List open operational issues and tasks.", {}),
                f("search_handover", "Search saved handovers, issues and tasks.", {"query":{"type":"string"}}, ["query"]),
                f("close_item", "Close a specific issue or task after explicit user request.", {"item_type":{"type":"string","enum":["issue","task"]},"item_id":{"type":"string"}}, ["item_type","item_id"]),
            ]
        if workspace == "pilot":
            return [
                f("business_info","Get business hours, phone and address.",{"topic":{"type":"string"}}),
                f("list_services","List services and prices.",{"query":{"type":"string"}}),
                f("list_providers","List providers or staff.",{"query":{"type":"string"}}),
                f("available_slots","Find future appointment slots.",{"provider_id":{"type":"string"},"service_id":{"type":"string"}}),
                f("prepare_booking","Prepare a booking proposal. Do not book yet.",{"patient":{"type":"string"},"provider_id":{"type":"string"},"service_id":{"type":"string"},"start":{"type":"string"}},["patient","provider_id","service_id","start"]),
                f("book_appointment","Finalize a previously approved booking. Requires confirmed=true.",{"patient":{"type":"string"},"provider_id":{"type":"string"},"service_id":{"type":"string"},"start":{"type":"string"},"confirmed":{"type":"boolean"}},["patient","provider_id","service_id","start","confirmed"]),
                f("cancel_appointment","Cancel a booking.",{"appointment_id":{"type":"string"}},["appointment_id"]),
                f("reschedule_appointment","Reschedule a booking.",{"appointment_id":{"type":"string"},"new_start":{"type":"string"}},["appointment_id","new_start"]),
                f("add_waitlist","Add a customer to the waitlist.",{"patient":{"type":"string"},"service_id":{"type":"string"},"provider_id":{"type":"string"},"note":{"type":"string"}},["patient","service_id"]),
                f("list_waitlist","List waiting customers.",{}),
                f("create_callback","Create a human callback request.",{"person":{"type":"string"},"request":{"type":"string"},"contact":{"type":"string"},"priority":{"type":"string"}},["person","request"]),
                f("list_callbacks","List open callback requests.",{}),
                f("set_reminder","Set a reminder in minutes.",{"message":{"type":"string"},"minutes":{"type":"integer"}},["message","minutes"]),
                f("list_reminders","List active reminders.",{}),
                f("save_note","Save a note.",{"text":{"type":"string"},"category":{"type":"string"}},["text"]),
                f("recent_notes","Read recent notes.",{"category":{"type":"string"}}),
                f("save_parking","Save a parking location.",{"location":{"type":"string"},"detail":{"type":"string"}},["location"]),
                f("get_parking","Retrieve the saved parking location.",{}),
                f("log_expense","Log a trip expense.",{"kind":{"type":"string"},"amount":{"type":"number"},"note":{"type":"string"}},["kind","amount"]),
                f("expense_total","Calculate total logged trip expenses.",{}),
                f("log_maintenance","Save a maintenance item.",{"item":{"type":"string"},"due_km":{"type":"integer"},"note":{"type":"string"}},["item"]),
                f("list_maintenance","List open maintenance items.",{}),
                f("calculate","Calculate simple arithmetic.",{"expression":{"type":"string"}},["expression"]),
            ]
        if workspace == "bridge":
            return [
                f("emergency_steps","Get general first-aid steps for a known scenario. Never diagnose.",{"scenario":{"type":"string"}},["scenario"]),
                f("log_incident","Record a local incident note.",{"scenario":{"type":"string"},"note":{"type":"string"}},["scenario","note"]),
                f("get_weather","Fetch current farm weather from Open-Meteo.",{"hours":{"type":"integer"}}),
                f("crop_advice","Give conservative general crop guidance without definitive diagnosis.",{"crop":{"type":"string"},"symptom":{"type":"string"}},["crop","symptom"]),
                f("log_farm","Save a field observation.",{"crop":{"type":"string"},"note":{"type":"string"}},["crop","note"]),
                f("recent_farm_logs","Read recent field observations.",{}),
                f("market_price","Fetch current market data only when a connector is configured.",{"crop":{"type":"string"}},["crop"]),
                f("list_forms","List available demo forms.",{}),
                f("start_form","Start a form for the current session.",{"form_id":{"type":"string"}},["form_id"]),
                f("set_form_answer","Store one form answer.",{"field":{"type":"string"},"value":{"type":"string"}},["field","value"]),
                f("validate_form","Validate the current form.",{}),
                f("preview_form","Preview the current form before submission.",{}),
                f("submit_form","Submit a validated form only with confirmed=true.",{"confirmed":{"type":"boolean"}},["confirmed"]),
            ]
        return [
            f("search_menu","Search menu items and prices.",{"query":{"type":"string"}}),
            f("create_order_draft","Create a new draft order.",{}),
            f("add_order_item","Add an item to the current draft order.",{"item_id":{"type":"string"},"quantity":{"type":"integer","minimum":1}},["item_id","quantity"]),
            f("set_customer","Set the customer name on the current draft.",{"customer":{"type":"string"}},["customer"]),
            f("confirm_order","Confirm an order only with confirmed=true after explicit user approval.",{"confirmed":{"type":"boolean"}},["confirmed"]),
            f("check_inventory","Check inventory and low-stock items.",{"item_id":{"type":"string"}}),
            f("record_stock_count","Record a physical stock count.",{"item_id":{"type":"string"},"qty":{"type":"integer","minimum":0}},["item_id","qty"]),
            f("get_checklist","Load opening or closing checklist.",{"name":{"type":"string","enum":["opening","closing"]}}),
            f("log_issue","Log a floor/safety issue without giving hazardous repair steps.",{"description":{"type":"string"},"severity":{"type":"string","enum":["low","medium","high"]}},["description","severity"]),
        ]

    async def execute(self, workspace: str, tool: str, args: dict[str, Any], session_id: str) -> dict[str, Any]:
        if workspace not in self.stores:
            return {"ok": False, "message": "Unknown workspace."}
        if tool not in self._tools_for(workspace):
            return {"ok": False, "message": "Tool is not allowed in this workspace."}

        # Confirmation gates on state-changing operations.
        if workspace == "pilot" and tool == "book_appointment" and not bool(args.get("confirmed", False)):
            return {"ok": False, "requires_confirmation": True, "message": "Booking is prepared but not confirmed. I need explicit confirmation before I finalize it."}
        if workspace == "bridge" and tool == "submit_form" and not bool(args.get("confirmed", False)):
            return {"ok": False, "requires_confirmation": True, "message": "The form is ready. I need your explicit confirmation before submission."}
        if workspace == "ops" and tool == "confirm_order" and not bool(args.get("confirmed", False)):
            return {"ok": False, "requires_confirmation": True, "message": "The order is ready. I need your explicit confirmation before I confirm it."}

        store = self.stores[workspace]
        if workspace == "shift":
            return store.execute(tool, args)
        if workspace == "pilot":
            return store.execute(tool, {k: v for k, v in args.items() if k != "confirmed"})
        if workspace == "ops":
            return store.execute(tool, {k: v for k, v in args.items() if k != "confirmed"})
        # Bridge has two async live connectors; local store handles everything else.
        if tool == "get_weather":
            import httpx
            hours = max(1, min(int(args.get("hours", 12) or 12), 48))
            bs = _bridge_settings()
            params = {"latitude": bs.farm_lat, "longitude": bs.farm_lon, "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m", "hourly": "precipitation_probability,temperature_2m,wind_speed_10m", "forecast_days": 2, "timezone": "auto"}
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                    r.raise_for_status()
                    data = r.json()
                return {"ok": True, "location": bs.farm_location, "current": data.get("current", {}), "next_hours": {k: v[:hours] for k, v in data.get("hourly", {}).items() if k in {"time", "precipitation_probability", "temperature_2m", "wind_speed_10m"}}, "message": f"Weather fetched for {bs.farm_location}."}
            except Exception as exc:
                return {"ok": False, "message": f"Weather tool failed: {type(exc).__name__}."}
        if tool == "market_price":
            url = os.getenv("MARKET_API_URL", "").strip().rstrip("/")
            if not url:
                return {"ok": False, "live": False, "message": "No live market-price connector is configured. I will not invent a current price."}
            import httpx
            headers = {"Authorization": f"Bearer {os.getenv('MARKET_API_KEY','')}"} if os.getenv("MARKET_API_KEY") else {}
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get(url, params={"crop": str(args.get("crop", ""))}, headers=headers)
                    r.raise_for_status()
                    return {"ok": True, "live": True, "crop": str(args.get("crop", "")), "data": r.json(), "message": "Market data received from the configured connector."}
            except Exception as exc:
                return {"ok": False, "live": True, "message": f"Market connector failed: {type(exc).__name__}."}
        if tool == "submit_form":
            return store.submit_form(session_id, True)
        if tool in {"start_form", "set_form_answer", "validate_form", "preview_form"}:
            # Bridge store keeps form drafts by session.
            mapping = {
                "start_form": lambda: store.start_form(session_id, str(args.get("form_id", ""))),
                "set_form_answer": lambda: store.set_form_answer(session_id, str(args.get("field", "")), str(args.get("value", ""))),
                "validate_form": lambda: store.validate_form(session_id),
                "preview_form": lambda: store.preview_form(session_id),
            }
            return mapping[tool]()
        return store.execute(tool, args)

    def _shift_local(self, text: str) -> dict[str, Any]:
        t = text.lower().strip(); store = self.stores["shift"]
        if any(k in t for k in ["summary", "last shift", "previous shift", "last handover", "shift summary"]):
            r=store.execute("get_shift_summary", {}); return {"reply": r.get("message", "Shift summary loaded."), "tool":"get_shift_summary", "arguments":{}, "tool_result":r}
        if any(k in t for k in ["open items", "pending", "open issue", "open task"]):
            r=store.execute("list_open_items", {}); return {"reply":f"There are {len(r.get('issues',[]))} open issues and {len(r.get('tasks',[]))} open tasks.","tool":"list_open_items","arguments":{},"tool_result":r}
        if any(k in t for k in ["search", "find", "malyu", "malyo"]):
            q=re.sub(r".*?(?:search|find|malyu|malyo)","",t).strip(" :") or "dispatch"; r=store.execute("search_handover",{"query":q}); return {"reply":f"Found {len(r.get('handovers',[]))} handovers, {len(r.get('issues',[]))} issues and {len(r.get('tasks',[]))} tasks for {q}.","tool":"search_handover","arguments":{"query":q},"tool_result":r}
        shift="Morning" if any(k in t for k in ["morning","savare","સવારે"]) else "Evening" if any(k in t for k in ["evening","sanje","સાંજે"]) else "Current"
        area="Warehouse" if any(k in t for k in ["warehouse","godown","inventory","વેરહાઉસ"]) else "Operations"
        r=store.execute("create_handover",{"shift":shift,"area":area,"summary":text}); return {"reply":f"Handover saved as {r['handover']['id']}.","tool":"create_handover","arguments":{"shift":shift,"area":area,"summary":text},"tool_result":r}

    def _pilot_local(self, text: str) -> dict[str, Any]:
        t=text.lower().strip(); store=self.stores["pilot"]
        if any(k in t for k in ["hours","open","close","phone","address","timing"]): r=store.execute("business_info",{"topic":text}); return {"reply":r["message"],"tool":"business_info","arguments":{"topic":text},"tool_result":r}
        if any(k in t for k in ["price","fee","cost","service","charges","su che","shu che"]): r=store.execute("list_services",{}); return {"reply":"; ".join(f"{x['name']}: ₹{x['price']}" for x in r.get('items',[]))+".","tool":"list_services","arguments":{},"tool_result":r}
        if any(k in t for k in ["parking","parked"]):
            if any(k in t for k in ["where","find","remember"]) and not any(k in t for k in ["save","parked at"]): r=store.execute("get_parking",{}); return {"reply":r["message"],"tool":"get_parking","arguments":{},"tool_result":r}
            loc=re.sub(r"(?i).*?(?:at|in|spot|parking)\s+","",text,1).strip(" .") or text; r=store.execute("save_parking",{"location":loc}); return {"reply":r["message"],"tool":"save_parking","arguments":{"location":loc},"tool_result":r}
        if any(k in t for k in ["expense total","spent so far"]): r=store.execute("expense_total",{}); return {"reply":r["message"],"tool":"expense_total","arguments":{},"tool_result":r}
        if any(k in t for k in ["expense","fuel","petrol","diesel","toll"]):
            m=re.search(r"(\d+(?:\.\d+)?)",t); amt=float(m.group(1)) if m else 0; kind="fuel" if any(k in t for k in ["fuel","petrol","diesel"]) else "toll" if "toll" in t else "parking"; r=store.execute("log_expense",{"kind":kind,"amount":amt,"note":text}); return {"reply":r["message"],"tool":"log_expense","arguments":{"kind":kind,"amount":amt,"note":text},"tool_result":r}
        if any(k in t for k in ["maintenance","service due","oil change","tyre","tire","brake"]): r=store.execute("log_maintenance",{"item":text}); return {"reply":r["message"],"tool":"log_maintenance","arguments":{"item":text},"tool_result":r}
        if any(k in t for k in ["remind","reminder"]):
            m=re.search(r"(\d+)\s*(?:minutes?|mins?|min)",t); mins=int(m.group(1)) if m else 5; mm=re.search(r"(?:remind me|reminder)\s*(?:in\s*)?\d+\s*(?:minutes?|mins?|min)\s*(?:to\s*)?(.+)$",text,re.I); msg=mm.group(1).strip() if mm else "Follow up on this task"; r=store.execute("set_reminder",{"message":msg,"minutes":mins}); return {"reply":r["message"],"tool":"set_reminder","arguments":{"message":msg,"minutes":mins},"tool_result":r}
        if any(k in t for k in ["remember","note","save this","yaad"]):
            msg=re.sub(r"(?i)^(?:remember|note|save this|yaad rakho)\s*","",text).strip() or text; r=store.execute("save_note",{"text":msg,"category":"drive"}); return {"reply":r["message"],"tool":"save_note","arguments":{"text":msg,"category":"drive"},"tool_result":r}
        return {"reply":"I can handle business info, parking, reminders, notes, trip expenses and maintenance.","tool":None,"arguments":{},"tool_result":None}

    def _bridge_local(self, text: str) -> dict[str, Any]:
        t=text.lower().strip()
        if any(k in t for k in ["bleeding","blood","bleed","burn","choking","fainting","allergic"]):
            scenario="severe_bleeding" if any(k in t for k in ["bleeding","blood","bleed"]) else "burn" if "burn" in t else "choking" if "choking" in t else "fainting" if "faint" in t else "allergic_reaction"
            return {"reply":"I’ll load the safe general emergency guidance.","tool":"emergency_steps","arguments":{"scenario":scenario}}
        if any(k in t for k in ["weather","rain","temperature"]): return {"reply":"I’ll check the current field weather.","tool":"get_weather","arguments":{"hours":12}}
        if any(k in t for k in ["crop","farm","field","pesticide","leaf","plant"]):
            crop=next((c for c in ["cotton","groundnut","wheat","rice"] if c in t),""); return {"reply":"Tell me the crop and symptom or observation.","tool":"crop_advice","arguments":{"crop":crop,"symptom":text}}
        if "market" in t or "bhaav" in t or "price" in t: return {"reply":"I’ll check whether a live market-price connector is configured.","tool":"market_price","arguments":{"crop":""}}
        if "form" in t or "application" in t: return {"reply":"I can list the available voice forms.","tool":"list_forms","arguments":{}}
        return {"reply":"I can help with emergency guidance, farm notes/weather, and voice forms.","tool":None,"arguments":{}}

    def _ops_local(self, text: str) -> dict[str, Any]:
        t=text.lower().strip(); store=self.stores["ops"]
        if any(k in t for k in ["menu","price","what do you have","su che","shu che"]): r=store.search_menu(""); return {"reply":"Available items: "+", ".join(f"{x['name']} ₹{x['price']}" for x in r['items'])+".","tool":"search_menu","arguments":{},"tool_result":r}
        if any(k in t for k in ["confirm", "final order", "done"]): r=store.execute("confirm_order",{"confirmed":True}); return {"reply":r["message"],"tool":"confirm_order","arguments":{"confirmed":True},"tool_result":r}
        if any(k in t for k in ["stock","inventory","ketlu","ketla"]): r=store.execute("check_inventory",{}); low=[x['name'] for x in r.get('items',[]) if x.get('low_stock')]; return {"reply":"Inventory checked. "+("Low stock: "+", ".join(low)+"." if low else "No listed items are below minimum level."),"tool":"check_inventory","arguments":{},"tool_result":r}
        if any(k in t for k in ["checklist","opening","closing"]): name="closing" if "closing" in t else "opening"; r=store.execute("get_checklist",{"name":name}); return {"reply":f"{name.title()} checklist loaded with {len(r['items'])} steps.","tool":"get_checklist","arguments":{"name":name},"tool_result":r}
        if any(k in t for k in ["issue","problem","machine","broken","danger","fire","electric"]): severity="high" if any(k in t for k in ["danger","fire","electric","injury","smoke"]) else "medium"; r=store.execute("log_issue",{"description":text,"severity":severity}); return {"reply":r["message"]+" Follow your site's safety procedure.","tool":"log_issue","arguments":{"description":text,"severity":severity},"tool_result":r}
        return {"reply":"I can handle restaurant orders, inventory, checklists and floor issues.","tool":None,"arguments":{}}

    def infer_workspace(self, text: str) -> str:
        t = text.lower()
        # Keep explicit/high-signal terms deterministic so an LLM planner cannot
        # silently send a domain request to the wrong store.
        checks = [
            ("bridge", ["voicebridge", "first aid", "bleeding", "choking", "burn", "farm assistant", "crop advice", "field log", "voice form", "scholarship form"]),
            ("ops", ["voiceops", "order desk", "restaurant order", "drive thru", "drive-thru", "inventory", "stock count", "opening checklist", "floor ops"]),
            ("pilot", ["voicepilot", "drive mode", "parking spot", "parked", "fuel expense", "trip expense", "vehicle maintenance", "toll"]),
            ("shift", ["voiceshift", "shift handover", "handover", "next shift", "conveyor", "dispatch", "warehouse shift"]),
        ]
        for key, terms in checks:
            if any(term in t for term in terms):
                return key
        return "shift"

    def local_parse(self, workspace: str, text: str) -> dict[str, Any]:
        return {"shift": self._shift_local, "pilot": self._pilot_local, "bridge": self._bridge_local, "ops": self._ops_local}[workspace](text)

    async def agent(self, task: str, ctx: AgentContext, workspace: str) -> AgentResult:
        if workspace not in self.stores:
            return AgentResult(agent="workspace_agent", status="error", data={"workspace":workspace}, segments=[Segment(type="error", content="Unknown workspace.")])
        state = self.state(workspace)
        tools = self.tools(workspace)
        local = self.local_parse(workspace, task)
        if not ctx.router.available():
            result = None
        else:
            system = f"""You are Astra's {WORKSPACES[workspace]['label']} domain workspace. {WORKSPACES[workspace]['description']}.\nUse only the allowed tools below. Never invent saved state or successful actions. Keep the spoken reply concise. Follow explicit confirmation gates for writes.\nIf the task is a general question unrelated to this workspace, say so briefly.\n\nALLOWED TOOLS:\n{json.dumps(tools, separators=(',', ':'))}\n\nReturn ONLY JSON: {{\"reply\":string,\"tool\":string|null,\"arguments\":object}}."""
            if workspace == "bridge":
                system += " Emergency guidance is general first aid, not diagnosis. For potentially life-threatening situations prioritize local emergency services. Farm advice is conservative and not a definitive diagnosis."
            if workspace == "pilot":
                system += " Never claim GPS, vehicle sensors, calling or messaging access. Appointment booking must be prepared and explicitly confirmed before finalization."
            if workspace == "ops":
                system += " Order confirmation requires explicit user approval. Never provide hazardous machine repair instructions."
            try:
                raw = await ctx.router.complete(system, [{"role":"user","content":f"Workspace state:\n{json.dumps(state)[:10000]}\n\nUser request: {task}"}], json_mode=True, temperature=0.1, max_tokens=1000, timeout=ctx.router.providers()[0].timeout if ctx.router.providers() and hasattr(ctx.router.providers()[0], 'timeout') else 30.0)
                obj = extract_json(raw)
                if isinstance(obj, dict) and "reply" in obj:
                    result = {"reply":str(obj.get("reply", "")),"tool":obj.get("tool"),"arguments":obj.get("arguments") if isinstance(obj.get("arguments"),dict) else {}}
            except Exception:
                result = None
        if result is None:
            result = local
        tool_name = result.get("tool")
        tool_result = None
        if tool_name:
            tool_result = await self.execute(workspace, tool_name, result.get("arguments") or {}, ctx.context.session_id)
            if tool_result.get("requires_confirmation"):
                reply = tool_result.get("message", result.get("reply", "Confirmation required."))
            elif tool_result.get("message"):
                reply = str(tool_result["message"])
                if workspace == "bridge" and tool_result.get("steps"):
                    reply += " " + str(tool_result["steps"][0])
                if workspace == "bridge" and tool_result.get("guidance"):
                    reply += " " + str(tool_result["guidance"][0])
                if workspace == "pilot" and tool_result.get("order", {}).get("total") is not None:
                    reply += f" Running total ₹{tool_result['order']['total']}."
                result["reply"] = reply
        segs = markdown_to_segments(str(result.get("reply", "")).strip()) or [Segment(type="text", content=str(result.get("reply", "")).strip())]
        return AgentResult(agent="workspace_agent", status="success", segments=segs, data={"workspace":workspace,"tool":tool_name,"arguments":result.get("arguments") or {},"tool_result":tool_result,"provider":ctx.router.last_used if ctx.router.available() else "local"})


workspace_hub = WorkspaceHub()


async def workspace_agent(task: str, ctx: AgentContext) -> AgentResult:
    workspace = getattr(ctx.request, "workspace", None) or "shift"
    return await workspace_hub.agent(task, ctx, workspace)
