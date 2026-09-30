from __future__ import annotations

from copy import deepcopy
from typing import Any


class OpsStore:
    def __init__(self) -> None:
        self.menu = [
            {"id": "burger", "name": "Classic Burger", "price": 149},
            {"id": "veg_pizza", "name": "Veg Pizza", "price": 249},
            {"id": "fries", "name": "French Fries", "price": 99},
            {"id": "cold_drink", "name": "Cold Drink", "price": 59},
            {"id": "sandwich", "name": "Veg Sandwich", "price": 129},
        ]
        self.orders: list[dict[str, Any]] = []
        self.inventory = {
            "burger_buns": {"name": "Burger Buns", "qty": 120, "unit": "pcs", "min": 40},
            "pizza_base": {"name": "Pizza Base", "qty": 35, "unit": "pcs", "min": 15},
            "fries": {"name": "French Fries", "qty": 45, "unit": "packs", "min": 20},
            "cold_drink": {"name": "Cold Drink", "qty": 60, "unit": "bottles", "min": 24},
        }
        self.issues: list[dict[str, Any]] = []
        self.checklists = {
            "opening": [
                "Machine power and emergency stop checked",
                "Floor dry and clear",
                "Fire extinguisher accessible",
                "First-aid kit present",
                "Inventory count started",
            ],
            "closing": [
                "Machines switched to safe state",
                "Waste cleared",
                "Cold storage checked",
                "Cash/order handoff completed",
            ],
        }

    def snapshot(self) -> dict[str, Any]:
        return deepcopy({
            "menu": self.menu,
            "orders": self.orders[-20:],
            "inventory": self.inventory,
            "issues": self.issues[-20:],
            "checklists": self.checklists,
        })

    def _menu_item(self, item_id: str) -> dict[str, Any] | None:
        return next((x for x in self.menu if x["id"] == item_id), None)

    def search_menu(self, query: str = "") -> dict[str, Any]:
        q = query.strip().lower()
        items = [x for x in self.menu if not q or q in x["name"].lower() or q in x["id"]]
        return {"ok": True, "items": items, "message": f"Found {len(items)} menu item(s)."}

    def create_order_draft(self) -> dict[str, Any]:
        order = {"id": f"ORD-{len(self.orders)+1001}", "customer": "", "items": [], "status": "draft"}
        self.orders.append(order)
        return {"ok": True, "order": order, "message": f"Draft {order['id']} created."}

    def _latest_draft(self) -> dict[str, Any] | None:
        return next((o for o in reversed(self.orders) if o["status"] == "draft"), None)

    def add_order_item(self, item_id: str, quantity: int = 1) -> dict[str, Any]:
        if quantity < 1:
            return {"ok": False, "message": "Quantity must be at least 1."}
        item = self._menu_item(item_id)
        if not item:
            return {"ok": False, "message": "Menu item not found."}
        order = self._latest_draft() or self.create_order_draft()["order"]
        existing = next((x for x in order["items"] if x["item_id"] == item_id), None)
        if existing:
            existing["quantity"] += quantity
        else:
            order["items"].append({"item_id": item_id, "name": item["name"], "unit_price": item["price"], "quantity": quantity})
        order["total"] = sum(x["unit_price"] * x["quantity"] for x in order["items"])
        return {"ok": True, "order": order, "message": f"Added {quantity} × {item['name']}."}

    def set_customer(self, customer: str) -> dict[str, Any]:
        order = self._latest_draft() or self.create_order_draft()["order"]
        order["customer"] = customer.strip()[:80]
        return {"ok": True, "order": order, "message": "Customer name saved."}

    def confirm_order(self) -> dict[str, Any]:
        order = self._latest_draft()
        if not order:
            return {"ok": False, "message": "There is no draft order to confirm."}
        if not order["items"]:
            return {"ok": False, "message": "The order has no items."}
        order["status"] = "confirmed"
        return {"ok": True, "order": order, "message": f"Order {order['id']} confirmed."}

    def check_inventory(self, item_id: str = "") -> dict[str, Any]:
        q = item_id.strip().lower()
        matches = {
            k: v for k, v in self.inventory.items()
            if not q or q in k.lower() or q in v["name"].lower()
        }
        result = []
        for k, v in matches.items():
            result.append({"id": k, **v, "low_stock": v["qty"] < v["min"]})
        return {"ok": True, "items": result, "message": f"Checked {len(result)} inventory item(s)."}

    def record_stock_count(self, item_id: str, qty: int) -> dict[str, Any]:
        if item_id not in self.inventory:
            return {"ok": False, "message": "Inventory item not found."}
        if qty < 0:
            return {"ok": False, "message": "Stock quantity cannot be negative."}
        self.inventory[item_id]["qty"] = qty
        item = self.inventory[item_id]
        return {"ok": True, "item": {"id": item_id, **item, "low_stock": qty < item["min"]}, "message": f"Stock for {item['name']} updated to {qty} {item['unit']}."}

    def log_issue(self, description: str, severity: str = "medium") -> dict[str, Any]:
        severity = severity.lower().strip()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        issue = {"id": f"ISS-{len(self.issues)+1:04d}", "description": description.strip()[:300], "severity": severity, "status": "open"}
        self.issues.append(issue)
        return {"ok": True, "issue": issue, "message": f"Issue {issue['id']} logged as {severity}."}

    def checklist(self, name: str = "opening") -> dict[str, Any]:
        key = name.lower().strip() if name else "opening"
        if key not in self.checklists:
            key = "opening"
        return {"ok": True, "name": key, "items": self.checklists[key], "message": f"Loaded {key} checklist."}

    def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "search_menu": lambda: self.search_menu(args.get("query", "")),
            "create_order_draft": lambda: self.create_order_draft(),
            "add_order_item": lambda: self.add_order_item(args.get("item_id", ""), int(args.get("quantity", 1))),
            "set_customer": lambda: self.set_customer(args.get("customer", "")),
            "confirm_order": lambda: self.confirm_order(),
            "check_inventory": lambda: self.check_inventory(args.get("item_id", "")),
            "record_stock_count": lambda: self.record_stock_count(args.get("item_id", ""), int(args.get("qty", -1))),
            "log_issue": lambda: self.log_issue(args.get("description", ""), args.get("severity", "medium")),
            "get_checklist": lambda: self.checklist(args.get("name", "opening")),
        }
        fn = mapping.get(tool)
        if not fn:
            return {"ok": False, "message": f"Unknown tool: {tool}"}
        try:
            return fn()
        except (TypeError, ValueError) as exc:
            return {"ok": False, "message": f"Invalid tool arguments: {exc}"}
