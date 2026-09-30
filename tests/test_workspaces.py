from __future__ import annotations

import asyncio

from app.workspaces.hub import workspace_hub


def test_workspace_catalog_has_all_four_domains():
    ids = {x["id"] for x in workspace_hub.metadata()}
    assert ids == {"shift", "pilot", "bridge", "ops"}


def test_shift_capture_and_retrieval():
    r = workspace_hub.stores["shift"].execute("create_handover", {"shift":"Test","area":"Lab","summary":"Test handover from unified build"})
    assert r["ok"] and r["handover"]["area"] == "Lab"
    latest = workspace_hub.stores["shift"].execute("get_latest_handover", {})
    assert latest["ok"]


def test_pilot_parking_roundtrip():
    store = workspace_hub.stores["pilot"]
    saved = store.execute("save_parking", {"location":"B42", "detail":"Unified test"})
    got = store.execute("get_parking", {})
    assert saved["ok"] and got["ok"]


def test_bridge_form_confirmation_gate():
    blocked = asyncio.run(workspace_hub.execute("bridge", "submit_form", {"confirmed": False}, "workspace-test"))
    assert blocked["requires_confirmation"] is True


def test_ops_order_confirmation_gate():
    blocked = asyncio.run(workspace_hub.execute("ops", "confirm_order", {"confirmed": False}, "workspace-test"))
    assert blocked["requires_confirmation"] is True
