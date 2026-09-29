"""HTTP / player-action edge cases and weird API sequences after merge."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from company_sim.ai.tools import player_tool_catalog
from company_sim.server import create_app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import company_sim.world as world_mod

    monkeypatch.setattr(world_mod, "default_save_dir", lambda: tmp_path)
    app = create_app()
    return TestClient(app), tmp_path


def _start(client: TestClient, **overrides):
    body = {"ai_companies": 1, "cities": 1, "map_size": 6, "llm_debug": True}
    body.update(overrides)
    res = client.post("/api/setup", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True, data
    return data


def test_setup_rejects_second_start(client):
    c, _ = client
    _start(c)
    again = c.post("/api/setup", json={"ai_companies": 0, "cities": 1, "map_size": 4}).json()
    assert again["ok"] is False


def test_setup_rejects_out_of_range_values(client):
    c, _ = client
    # pydantic validation → 422
    bad = c.post("/api/setup", json={"ai_companies": -1, "cities": 1, "map_size": 6})
    assert bad.status_code == 422
    bad2 = c.post("/api/setup", json={"ai_companies": 1, "cities": 0, "map_size": 6})
    assert bad2.status_code == 422
    bad3 = c.post("/api/setup", json={"ai_companies": 1, "cities": 1, "map_size": 1})
    assert bad3.status_code == 422
    bad4 = c.post("/api/setup", json={"ai_companies": 1, "cities": 1, "map_size": 200})
    assert bad4.status_code == 422
    # Raised UI/API ceiling: 128x128 square rectangles are allowed
    ok_big = c.post(
        "/api/setup",
        json={"ai_companies": 0, "cities": 1, "map_size": 128, "llm_debug": False},
    )
    assert ok_big.status_code == 200
    assert ok_big.json()["state"]["config"]["map_size"] == 128


def test_actions_before_setup_fail(client):
    c, _ = client
    assert c.post("/api/player/pass").json()["ok"] is False
    assert c.post("/api/player/action", json={"name": "get_status", "arguments": {}}).json()[
        "ok"
    ] is False
    assert c.get("/api/llm_debug").json()["ok"] is False


def test_player_tools_lists_same_as_catalog_after_setup(client):
    c, _ = client
    _start(c, llm_debug=False)
    tools = c.get("/api/player/tools").json()
    assert tools["ok"] is True
    names = {t["name"] for t in tools["tools"]}
    assert names == {t["name"] for t in player_tool_catalog()}
    assert "done" not in names
    assert "post_government_contract" not in names


def test_player_action_rejects_unknown_and_city_tools(client):
    c, _ = client
    _start(c)
    assert c.post("/api/player/action", json={"name": "nope", "arguments": {}}).json()["ok"] is False
    assert (
        c.post(
            "/api/player/action",
            json={"name": "done", "arguments": {"note": "bye"}},
        ).json()["ok"]
        is False
    )
    assert (
        c.post(
            "/api/player/action",
            json={"name": "post_government_contract", "arguments": {"requirements": {"iron_ore": 1}}},
        ).json()["ok"]
        is False
    )


def test_player_action_fuzz_all_tools_with_empty_and_weird_args(client):
    c, _ = client
    _start(c, ai_companies=2, map_size=5)
    weird_batches = [
        {},
        {"x": "nope"},  # wrong type — pydantic not used on nested args
        {
            "to": "city:city_a",
            "x": 0,
            "y": 0,
            "price": 1,
            "item_id": "iron_ore",
            "quantity": 1,
            "side": "N",
            "building_id": "foundry",
            "method_id": "make_steel",
            "listing_id": 1,
            "proposal_id": 1,
            "contract_id": 1,
            "body": "hi",
            "limit": 3,
            "with_whom": "city:city_a",
            "requirements": {"iron_ore": 1},
        },
        {"quantity": 10**9, "price": 10**9, "item_id": "iron_ore"},
    ]
    for tool in player_tool_catalog():
        for args in weird_batches:
            res = c.post("/api/player/action", json={"name": tool["name"], "arguments": args})
            assert res.status_code == 200, f"{tool['name']} {args}"
            body = res.json()
            assert "ok" in body
            assert "Unknown or unavailable tool" not in (body.get("message") or "")


def test_market_http_edge_flows(client):
    c, _ = client
    _start(c)
    # Invalid sell
    assert c.post(
        "/api/player/market/sell",
        json={"item_id": "iron_ore", "quantity": 0, "price": 5},
    ).json()["ok"] is False
    # Valid sell then retract
    sell = c.post(
        "/api/player/market/sell",
        json={"item_id": "iron_ore", "quantity": 1, "price": 12},
    ).json()
    assert sell["ok"] is True
    lid = sell["data"]["listing_id"]
    assert c.post("/api/player/market/retract_sell", json={"listing_id": lid}).json()["ok"] is True
    assert c.post("/api/player/market/retract_sell", json={"listing_id": lid}).json()["ok"] is False
    # Buy order priced below seeded sells so it stays open, then retract
    buy = c.post(
        "/api/player/market/buy_order",
        json={"item_id": "coal", "quantity": 1, "price": 1},
    ).json()
    assert buy["ok"] is True
    blid = buy["data"]["listing_id"]
    assert c.post("/api/player/market/retract_buy", json={"listing_id": blid}).json()["ok"] is True


def test_plot_proposal_http_roundtrip_reject(client):
    c, _ = client
    state = _start(c)["state"]
    # Find a city-owned plot
    tile = next(t for t in state["map"]["tiles"] if t["plot"]["owner_kind"] == "city")
    to = f"city:{tile['plot']['owner_id']}"
    prop = c.post(
        "/api/player/propose_plot_buy",
        json={"to": to, "x": tile["x"], "y": tile["y"], "price": 40},
    ).json()
    assert prop["ok"] is True
    pid = prop["data"]["id"]
    # Player cannot accept (not recipient)
    assert c.post("/api/player/accept_proposal", json={"proposal_id": pid}).json()["ok"] is False
    # Proposer cancel / reject path
    rej = c.post("/api/player/reject_proposal", json={"proposal_id": pid}).json()
    assert "ok" in rej


def test_set_production_method_http(client):
    c, _ = client
    _start(c)
    # Without ownership → fail
    assert (
        c.post(
            "/api/player/set_production_method",
            json={"x": 0, "y": 0, "method_id": "make_steel"},
        ).json()["ok"]
        is False
    )


def test_plots_for_sale_and_status_via_action(client):
    c, _ = client
    _start(c)
    plots = c.get("/api/plots_for_sale?limit=5").json()
    assert plots["ok"] is True
    assert len(plots["data"]["plots"]) <= 5
    status = c.post("/api/player/action", json={"name": "get_status", "arguments": {}}).json()
    assert status["ok"] is True
    assert status["data"]["id"] == "player"
    market = c.post(
        "/api/player/action",
        json={"name": "get_market", "arguments": {"item_id": "iron_ore"}},
    ).json()
    assert market["ok"] is True
    for L in market["data"]["sell_listings"]:
        assert L["item_id"] == "iron_ore"


def test_llm_debug_trace_path_traversal_http(client):
    c, tmp = client
    _start(c, llm_debug=True)
    # Create a real trace via world side channel
    w = c.app.state.world
    actor = w.companies["player"]
    bundle = w.file_store.pack_for_agent(w, actor)
    path = w.llm_debug_log.write_turn(
        actor_kind="company",
        actor_id="player",
        day=1,
        system="s",
        bundle=bundle,
        rounds=[{"assistant_content": "hi", "tool_calls": [], "tool_results": []}],
        final_note="n",
    )
    rel = str(path.relative_to(w.llm_debug_log.debug_dir))
    ok = c.get("/api/llm_debug/trace", params={"path": rel}).json()
    assert ok["ok"] is True
    assert "LLM DEBUG TRACE" in ok["text"]

    evil = c.get("/api/llm_debug/trace", params={"path": "../../etc/passwd"}).json()
    assert evil["ok"] is False
    evil2 = c.get("/api/llm_debug/trace", params={"path": "/etc/passwd"}).json()
    assert evil2["ok"] is False


def test_mail_http_empty_and_ok(client):
    c, _ = client
    _start(c)
    assert c.post("/api/player/message", json={"to": "city:city_a", "body": ""}).json()["ok"] is False
    assert c.post("/api/player/message", json={"to": "city:city_a", "body": "hello"}).json()["ok"] is True
    contacts = c.get("/api/mail/contacts").json()
    assert contacts["ok"] is True
    assert any("city" in x or "ai_" in x or "company" in str(x) for x in contacts["contacts"])


def test_pause_pass_state_roundtrip(client):
    c, _ = client
    _start(c, ai_companies=0)
    assert c.post("/api/pause", json={"paused": True}).json()["ok"] is True
    st = c.get("/api/state").json()
    # Mid-day: pause is pending until the day completes
    assert st["state"]["pause_requested"] is True
    assert st["state"]["paused"] is False
    assert c.post("/api/player/pass").json()["ok"] is True
    st2 = c.get("/api/state").json()
    assert st2["state"]["day"] >= 2
    assert st2["state"]["paused"] is True
    assert c.post("/api/pause", json={"paused": False}).json()["ok"] is True
    assert c.get("/api/state").json()["state"]["paused"] is False


def test_build_produce_road_merge_http_without_ownership_fails(client):
    c, _ = client
    _start(c)
    assert c.post("/api/player/build", json={"x": 0, "y": 0, "building_id": "foundry"}).json()[
        "ok"
    ] is False
    assert c.post("/api/player/produce", json={"x": 0, "y": 0}).json()["ok"] is False
    assert c.post("/api/player/build_road", json={"x": 0, "y": 0, "side": "N"}).json()["ok"] is False
    assert c.post(
        "/api/player/merge_plots",
        json={"x1": 0, "y1": 0, "x2": 1, "y2": 0},
    ).json()["ok"] is False


def test_gov_bid_fulfill_without_contract_fails(client):
    c, _ = client
    _start(c)
    assert c.post(
        "/api/player/bid_government_contract",
        json={"contract_id": 1, "price": 10},
    ).json()["ok"] is False
    assert c.post(
        "/api/player/fulfill_government_contract",
        json={"contract_id": 1},
    ).json()["ok"] is False
    listed = c.get("/api/government_contracts").json()
    assert listed["ok"] is True


def test_setup_llm_debug_false_hides_debug_dir_until_enabled_path(client):
    c, tmp = client
    _start(c, llm_debug=False)
    dbg = c.get("/api/llm_debug").json()
    assert dbg["ok"] is True
    assert dbg["enabled"] is False
    # Instructions still exist
    assert (tmp / "instructions").is_dir()
    # Trace endpoint blocked
    assert c.get("/api/llm_debug/trace", params={"path": "x"}).json()["ok"] is False


def test_rapid_fire_pass_and_status_sequence(client):
    c, _ = client
    _start(c, ai_companies=0, map_size=4)
    for _ in range(5):
        assert c.post("/api/player/action", json={"name": "get_status", "arguments": {}}).json()[
            "ok"
        ]
        assert c.post("/api/player/pass").json()["ok"]
    st = c.get("/api/state").json()["state"]
    assert st["day"] >= 6


def test_direct_goods_propose_http(client):
    c, _ = client
    _start(c, ai_companies=1)
    # Need inventory
    sell = c.post(
        "/api/player/propose_sell",
        json={"to": "company:ai_1", "item_id": "iron_ore", "quantity": 1, "price": 7},
    ).json()
    assert sell["ok"] is True
    buy = c.post(
        "/api/player/propose_buy",
        json={"to": "company:ai_1", "item_id": "coal", "quantity": 1, "price": 6},
    ).json()
    assert buy["ok"] is True
    props = c.get("/api/proposals").json()
    assert props["ok"] is True
