"""Full production loop tests (player + agent) and building storage."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.ai.tools import ToolExecutor
from company_sim.content import GameContent
from company_sim.world import World, WorldConfig


def _loop_world(tmp: Path, *, actor: str = "player") -> World:
    """Rich market + cash for end-to-end produce loops on standard plots."""
    return World.new_game(
        WorldConfig(
            map_size=6,
            starting_cities=1,
            ai_company_count=1 if actor != "player" else 0,
            save_dir=str(tmp),
            min_seconds_between_turns=0.0,
            player_starting_cash=50_000,
            market_seed_qty=100,
            market_seed_price=1,
        )
    )


def _standard_city_plot(w: World):
    city = next(iter(w.grid.cities.values()))
    return next(
        t
        for t in w.grid.tiles
        if t.plot
        and t.plot.owned_by("city", city.id)
        and t.plot.plot_type.value == "standard"
        and t.plot.building is None
    )


def _buy_plot(w: World, company_id: str, tile) -> None:
    city_id = tile.plot.owner_id
    price = 50
    company = w.companies[company_id]
    company.cash = max(company.cash, price + 10_000)
    company.inventory.set("construction_materials", max(company.inventory.get("construction_materials"), 20))
    prop = w.propose_plot_buy("company", company_id, f"city:{city_id}", tile.x, tile.y, price)
    w.accept_proposal("city", city_id, prop.data["id"])
    assert tile.plot.owned_by("company", company_id)


def _foundry_loop(w: World, company_id: str) -> dict:
    """buy plot → build foundry → set method → buy inputs → deposit → produce → withdraw → sell."""
    tile = _standard_city_plot(w)
    _buy_plot(w, company_id, tile)
    x, y = tile.x, tile.y
    company = w.companies[company_id]

    # Ensure build materials
    company.inventory.set("construction_materials", max(20, company.inventory.get("construction_materials")))
    r = w.build_building("company", company_id, x, y, "foundry")
    assert r.ok, r.message
    assert tile.plot.building is not None
    # Hard slots materialized at build (zeros kept)
    assert "iron_ore" in tile.plot.building.storage.as_dict()
    assert tile.plot.building.storage.get("iron_ore") == 0
    assert tile.plot.building.storage_capacity["iron_ore"] == 10
    assert tile.plot.building.storage_capacity["steel"] == 10
    cap = w.content.storage_capacity_for_building("foundry")
    assert set(tile.plot.building.storage_capacity) == set(cap)

    r = w.set_production_method("company", company_id, x, y, "make_steel")
    assert r.ok, r.message

    # Buy inputs from seeded market @1
    for item_id in ("iron_ore", "coal", "energy"):
        before = company.inventory.get(item_id)
        buy = w.buy_from_market("company", company_id, item_id, 1)
        assert buy.ok, buy.message
        assert company.inventory.get(item_id) == before + 1

    for item_id in ("iron_ore", "coal", "energy"):
        dep = w.deposit_to_building("company", company_id, x, y, item_id, 1)
        assert dep.ok, dep.message

    steel_before_inv = company.inventory.get("steel")
    prod = w.produce("company", company_id, x, y)
    assert prod.ok, prod.message
    assert tile.plot.building.storage.get("steel") >= 1
    assert company.inventory.get("steel") == steel_before_inv  # still in building

    out_qty = tile.plot.building.storage.get("steel")
    wd = w.withdraw_from_building("company", company_id, x, y, "steel", out_qty)
    assert wd.ok, wd.message
    assert company.inventory.get("steel") == steel_before_inv + out_qty

    sell = w.post_sell("company", company_id, "steel", out_qty, 5)
    assert sell.ok, sell.message
    assert company.inventory.get("steel") == steel_before_inv
    return {"x": x, "y": y, "sold": out_qty, "listing_id": sell.data["listing_id"]}


def test_storage_slots_follow_methods():
    c = GameContent.load()
    foundry_slots = set(c.storage_items_for_building("foundry"))
    assert {"iron_ore", "coal", "energy", "steel", "copper_ore", "copper", "bauxite", "aluminum"} <= foundry_slots
    mine_slots = set(c.storage_items_for_building("mine"))
    assert "iron_ore" in mine_slots and "steel" not in mine_slots
    for item_id, cap in c.storage_capacity_for_building("foundry").items():
        assert cap == 10


def test_agents_can_read_full_catalogs():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        for path_name in (
            "goods_index.txt",
            "buildings_catalog.txt",
            "production_methods_catalog.txt",
        ):
            assert (Path(td) / path_name).is_file()
        # Compact LLM pack points at get_catalog; full pack still embeds catalogs
        compact = w.file_store.pack_for_agent(w, w.companies["player"], compact=True)
        assert "get_catalog" in compact.prompt_text
        full = w.file_store.pack_for_agent(w, w.companies["player"], compact=False)
        text = full.prompt_text
        assert "GOODS INDEX" in text
        assert "BUILDINGS CATALOG" in text
        assert "PRODUCTION METHODS CATALOG" in text
        assert "make_steel" in text
        assert "foundry" in text
        # Tool path
        ex = ToolExecutor(w, w.companies["player"])
        g = ex.execute("get_catalog", {"section": "good", "id": "steel"})
        assert g["ok"] and g["data"]["made_in_buildings"] == ["foundry"]
        b = ex.execute("get_catalog", {"section": "buildings"})
        assert b["ok"] and len(b["data"]["buildings"]) >= 13
        m = ex.execute("get_catalog", {"section": "methods", "id": "make_steel"})
        assert m["ok"] and m["data"]["inputs"]["iron_ore"] == 1


def test_destroy_building_refunds_ten_percent_floored():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        tile = _standard_city_plot(w)
        _buy_plot(w, "player", tile)
        player = w.companies["player"]
        player.inventory.set("construction_materials", 20)
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        # Put something in storage
        player.inventory.set("coal", 2)
        w.deposit_to_building("company", "player", tile.x, tile.y, "coal", 2)
        cm_before = player.inventory.get("construction_materials")
        coal_before = player.inventory.get("coal")
        r = w.destroy_building("company", "player", tile.x, tile.y)
        assert r.ok
        assert tile.plot.building is None
        # 10 of construction_materials → 10% floored = 1
        assert r.data["refund_items"] == {"construction_materials": 1}
        assert player.inventory.get("construction_materials") == cm_before + 1
        assert player.inventory.get("coal") == coal_before + 2


def test_deposit_rejects_non_slot_and_over_capacity():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        tile = _standard_city_plot(w)
        _buy_plot(w, "player", tile)
        player = w.companies["player"]
        player.inventory.set("construction_materials", 20)
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        player.inventory.set("smartphone", 1)
        with pytest.raises(ActionError, match="cannot be stored"):
            w.deposit_to_building("company", "player", tile.x, tile.y, "smartphone", 1)
        player.inventory.set("iron_ore", 20)
        w.deposit_to_building("company", "player", tile.x, tile.y, "iron_ore", 10)
        with pytest.raises(ActionError, match="storage room"):
            w.deposit_to_building("company", "player", tile.x, tile.y, "iron_ore", 1)


def test_full_loop_player():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        # Market has 100 of each @1
        assert w.market.inventory.get("iron_ore") == 100
        result = _foundry_loop(w, "player")
        assert result["sold"] >= 1


def test_full_loop_agent_via_tools():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_size=6,
                starting_cities=1,
                ai_company_count=1,
                save_dir=str(td),
                min_seconds_between_turns=0.0,
                player_starting_cash=50_000,
                market_seed_qty=100,
                market_seed_price=1,
            )
        )
        agent = w.companies["ai_1"]
        agent.cash = 50_000
        agent.inventory.set("construction_materials", 30)
        ex = ToolExecutor(w, agent)

        tile = _standard_city_plot(w)
        city_id = tile.plot.owner_id
        prop = ex.execute(
            "propose_plot_buy",
            {"to": f"city:{city_id}", "x": tile.x, "y": tile.y, "price": 50},
        )
        assert prop["ok"], prop
        w.accept_proposal("city", city_id, prop["data"]["id"])

        assert ex.execute("build_building", {"x": tile.x, "y": tile.y, "building_id": "foundry"})["ok"]
        assert ex.execute(
            "set_production_method",
            {"x": tile.x, "y": tile.y, "method_id": "make_steel"},
        )["ok"]

        for item_id in ("iron_ore", "coal", "energy"):
            assert ex.execute("buy_from_market", {"item_id": item_id, "quantity": 1})["ok"]
            assert ex.execute(
                "deposit_to_building",
                {"x": tile.x, "y": tile.y, "item_id": item_id, "quantity": 1},
            )["ok"]

        prod = ex.execute("produce", {"x": tile.x, "y": tile.y})
        assert prod["ok"], prod
        steel_qty = tile.plot.building.storage.get("steel")
        assert steel_qty >= 1
        assert ex.execute(
            "withdraw_from_building",
            {"x": tile.x, "y": tile.y, "item_id": "steel", "quantity": steel_qty},
        )["ok"]
        sell = ex.execute("post_sell", {"item_id": "steel", "quantity": steel_qty, "price": 5})
        assert sell["ok"], sell


def test_produce_without_building_storage_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        tile = _standard_city_plot(w)
        _buy_plot(w, "player", tile)
        player = w.companies["player"]
        player.inventory.set("construction_materials", 20)
        player.inventory.set("iron_ore", 5)
        player.inventory.set("coal", 5)
        player.inventory.set("energy", 5)
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        w.set_production_method("company", "player", tile.x, tile.y, "make_steel")
        with pytest.raises(ActionError, match="building storage"):
            w.produce("company", "player", tile.x, tile.y)


def test_market_seed_lists_every_item():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        items = {i.id for i in w.content.items.all()}
        for item_id in items:
            assert w.market.inventory.get(item_id) == 100
        # Buy one random finished good cheaply
        r = w.buy_from_market("company", "player", "steel", 3)
        assert r.ok
        assert r.data["spent"] == 3


def test_reconcile_adds_slots_and_keeps_orphan_stock():
    """Catalog updates must not wipe stock; empty obsolete slots are dropped."""
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        tile = _standard_city_plot(w)
        _buy_plot(w, "player", tile)
        player = w.companies["player"]
        player.inventory.set("construction_materials", 20)
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        b = tile.plot.building
        assert "steel" in b.storage_capacity
        # Simulate an old save missing a slot + carrying obsolete stock
        b.storage_capacity.pop("steel", None)
        b.storage.unreserve_slot("steel")
        b.storage.reserve_slots(["legacy_scrap"])
        b.storage_capacity["legacy_scrap"] = 10
        b.storage.set("legacy_scrap", 3)
        report = w.reconcile_all_building_storage()
        assert "steel" in b.storage_capacity
        assert b.storage.get("steel") == 0
        assert "legacy_scrap" not in b.storage_capacity
        assert b.storage.get("legacy_scrap") == 3  # orphan kept until withdrawn
        assert any("steel" in (r.get("added") or []) for r in report)


def test_legacy_building_without_capacity_materializes_on_ensure():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        tile = _standard_city_plot(w)
        _buy_plot(w, "player", tile)
        player = w.companies["player"]
        player.inventory.set("construction_materials", 20)
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        b = tile.plot.building
        b.storage_capacity.clear()
        b.storage.reserved.clear()
        b.storage.quantities.clear()
        w.ensure_building_storage(b)
        assert b.storage_capacity
        assert all(b.storage.get(i) == 0 for i in b.storage_capacity)


def test_placeholder_arts_exist_for_catalog():
    root = Path(__file__).resolve().parents[1] / "web" / "assets"
    c = GameContent.load()
    for item in c.items.all():
        assert (root / "goods" / f"{item.id}.svg").is_file(), item.id
        assert item.to_public_dict()["art"].endswith(f"/goods/{item.id}.svg")
    for b in c.buildings.all():
        assert (root / "buildings" / "ui" / f"{b.id}.svg").is_file(), b.id
        for w, h in ((1, 1), (3, 1), (2, 2), (9, 9)):
            assert (root / "buildings" / "map" / b.id / f"{w}x{h}.svg").is_file(), f"{b.id}/{w}x{h}"
        art = b.to_public_dict()["art"]
        assert art["ui"].endswith(f"/ui/{b.id}.svg")
        assert art["map"].endswith(f"/map/{b.id}/1x1.svg")
    assert (root / "terrain" / "grass.svg").is_file()
    assert (root / "terrain" / "grass_specialized.svg").is_file()
    for mask in range(16):
        assert (root / "roads" / f"mask_{mask}.svg").is_file()


def test_combine_empty_and_same_building_expands_footprint():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        # Claim a 1x2 strip
        for x, y in ((1, 1), (2, 1)):
            w.grid.get(x, y).plot.claim("company", "player")
        player = w.companies["player"]
        player.inventory.set("construction_materials", 30)
        player.cash = 5000
        # Empty combine OK
        r = w.merge_plots("company", "player", 1, 1, 2, 1)
        assert r.ok
        assert w.grid.group_size(1, 1) == 2
        # Build spans both
        built = w.build_building("company", "player", 1, 1, "foundry")
        assert built.ok, built.message
        b = w.grid.get(1, 1).plot.building
        assert b.footprint_w == 2 and b.footprint_h == 1
        assert w.grid.get(2, 1).plot.building is b
        assert b.map_art_path().endswith("foundry/2x1.svg")


def test_combine_rejects_different_buildings():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        for x, y in ((1, 1), (2, 1)):
            w.grid.get(x, y).plot.claim("company", "player")
        player = w.companies["player"]
        player.inventory.set("construction_materials", 40)
        player.cash = 5000
        w.build_building("company", "player", 1, 1, "foundry")
        w.build_building("company", "player", 2, 1, "refinery")
        with pytest.raises(ActionError, match="same building"):
            w.merge_plots("company", "player", 1, 1, 2, 1)


def test_combine_same_building_merges_storage_and_size():
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        for x, y in ((1, 1), (2, 1)):
            w.grid.get(x, y).plot.claim("company", "player")
        player = w.companies["player"]
        player.inventory.set("construction_materials", 40)
        player.cash = 5000
        w.build_building("company", "player", 1, 1, "foundry")
        w.build_building("company", "player", 2, 1, "foundry")
        player.inventory.set("coal", 2)
        w.deposit_to_building("company", "player", 1, 1, "coal", 1)
        player.acted_this_day = False
        w.deposit_to_building("company", "player", 2, 1, "coal", 1)
        player.acted_this_day = False
        r = w.merge_plots("company", "player", 1, 1, 2, 1)
        assert r.ok, r.message
        b = w.grid.get(1, 1).plot.building
        assert b is w.grid.get(2, 1).plot.building
        assert b.footprint_w == 2 and b.footprint_h == 1
        assert b.storage.get("coal") == 2


def test_build_and_combine_art_paths_and_roads_coexist():
    """Build/combine pick sized map art; roads work with buildings on outer edges."""
    with tempfile.TemporaryDirectory() as td:
        w = _loop_world(Path(td))
        for x, y in ((1, 1), (2, 1)):
            w.grid.get(x, y).plot.claim("company", "player")
        player = w.companies["player"]
        player.inventory.set("construction_materials", 40)
        player.inventory.set("steel", 5)
        player.cash = 5000

        # Road first, then build — both remain
        w.build_road("company", "player", 1, 1, "N")
        player.acted_this_day = False
        built = w.build_building("company", "player", 1, 1, "foundry")
        assert built.ok
        b = w.grid.get(1, 1).plot.building
        assert b.map_art_path().endswith("/foundry/1x1.svg")
        assert w.grid.get(1, 1).plot.roads["N"] is True
        assert w.grid.road_mask_at(1, 1) == 1  # N bit

        # Expand onto empty neighbor → art becomes 2x1; outer road kept
        player.acted_this_day = False
        merged = w.merge_plots("company", "player", 1, 1, 2, 1)
        assert merged.ok
        b = w.grid.get(1, 1).plot.building
        assert b.footprint_w == 2 and b.footprint_h == 1
        assert b.map_art_path().endswith("/foundry/2x1.svg")
        assert Path(__file__).resolve().parents[1].joinpath(
            "web/assets/buildings/map/foundry/2x1.svg"
        ).is_file()
        assert w.grid.get(1, 1).plot.roads["N"] is True

        # Road still allowed on non-combined outer edge of building plot
        player.acted_this_day = False
        road2 = w.build_road("company", "player", 2, 1, "S")
        assert road2.ok
        assert w.grid.get(2, 1).plot.building is b
