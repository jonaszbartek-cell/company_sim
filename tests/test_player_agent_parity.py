"""Player UI/API parity with company agent tools."""

from __future__ import annotations

from fastapi.testclient import TestClient

from company_sim.ai.tools import TOOL_DEFINITIONS, player_tool_catalog, tool_name
from company_sim.server import create_app


CITY_ONLY = {
    "post_government_contract",
    "award_government_contract",
    "cancel_government_contract",
}


def test_player_tool_catalog_covers_company_agent_tools():
    all_names = {tool_name(d) for d in TOOL_DEFINITIONS}
    player_names = {t["name"] for t in player_tool_catalog()}
    assert "done" not in player_names
    assert CITY_ONLY.isdisjoint(player_names)
    expected = all_names - CITY_ONLY - {"done"}
    assert player_names == expected
    assert "set_production_method" in player_names
    assert "list_plots_for_sale" in player_names
    assert "bid_government_contract" in player_names
    assert "propose_sell" in player_names


def test_player_action_api_runs_same_tools(monkeypatch, tmp_path):
    import company_sim.world as world_mod

    monkeypatch.setattr(world_mod, "default_save_dir", lambda: tmp_path)
    app = create_app()
    client = TestClient(app)
    started = client.post(
        "/api/setup",
        json={"ai_companies": 1, "cities": 1, "map_size": 6, "llm_debug": False},
    ).json()
    assert started["ok"] is True

    tools = client.get("/api/player/tools").json()
    assert tools["ok"] is True
    names = {t["name"] for t in tools["tools"]}
    assert "get_status" in names
    assert "post_sell" in names
    assert "done" not in names

    status = client.post(
        "/api/player/action",
        json={"name": "get_status", "arguments": {}},
    ).json()
    assert status["ok"] is True
    assert status["data"]["id"] == "player"
    assert "cash" in status["data"]

    market = client.post(
        "/api/player/action",
        json={"name": "get_market", "arguments": {}},
    ).json()
    assert market["ok"] is True

    plots = client.get("/api/plots_for_sale").json()
    assert plots["ok"] is True
    assert "plots" in plots["data"]

    # Market buy via unified action path
    buy = client.post(
        "/api/player/action",
        json={"name": "buy_from_market", "arguments": {"item_id": "iron", "quantity": 1}},
    ).json()
    assert buy["ok"] is True

    # Reject city-only tool
    blocked = client.post(
        "/api/player/action",
        json={"name": "post_government_contract", "arguments": {"requirements": {"iron": 1}}},
    ).json()
    assert blocked["ok"] is False

    # set_production_method REST exists
    method = client.post(
        "/api/player/set_production_method",
        json={"x": 0, "y": 0, "method_id": "make_steel"},
    ).json()
    # May fail for ownership — but endpoint must exist and return structured response
    assert "ok" in method
    assert "message" in method

    # pass_turn via action
    passed = client.post(
        "/api/player/action",
        json={"name": "pass_turn", "arguments": {}},
    ).json()
    assert passed["ok"] is True


def test_player_can_use_every_catalog_tool_at_least_as_callable(monkeypatch, tmp_path):
    """Every catalog tool is accepted by /api/player/action (may fail for game rules)."""
    import company_sim.world as world_mod

    monkeypatch.setattr(world_mod, "default_save_dir", lambda: tmp_path)
    app = create_app()
    client = TestClient(app)
    client.post("/api/setup", json={"ai_companies": 0, "cities": 1, "map_size": 4}).json()

    for tool in player_tool_catalog():
        # Minimal/empty args — should not 404 or reject as unknown tool
        res = client.post(
            "/api/player/action",
            json={"name": tool["name"], "arguments": {}},
        )
        assert res.status_code == 200, tool["name"]
        body = res.json()
        assert "ok" in body, tool["name"]
        # Unknown-tool message must not appear
        assert "Unknown or unavailable tool" not in (body.get("message") or "")
