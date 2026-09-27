"""Core world / action API tests."""

from __future__ import annotations

import pytest

from company_sim.actions import ActionError
from company_sim.ai.tools import ToolExecutor, build_actor_context
from company_sim.map_grid import TileKind
from company_sim.world import World, WorldConfig


def _unowned_plot(world: World):
    for t in world.grid.tiles:
        if t.kind == TileKind.PLOT and t.plot and not t.plot.is_owned:
            return t
    raise AssertionError("no unowned plot")


def _adjacent_unowned_pair(world: World, owner_kind: str, owner_id: str):
    """Find an owned plot with an adjacent unowned plot."""
    for t in world.owned_plots(owner_kind, owner_id):
        for nx, ny in world.grid.neighbors4(t.x, t.y):
            n = world.grid.get(nx, ny)
            if n.kind == TileKind.PLOT and n.plot and not n.plot.is_owned:
                return t, n
    return None


class TestNewGame:
    def test_player_starts_with_cash_inventory_and_plot(self, world: World):
        player = world.companies["player"]
        assert player.cash == 2500
        assert player.inventory.get("iron") == 20
        assert player.inventory.get("coal") == 20
        assert player.inventory.get("energy") == 20
        assert player.inventory.get("steel") == 0
        owned = world.owned_plots("company", "player")
        assert len(owned) == 1
        assert owned[0].plot.price == 0
        assert owned[0].plot.parcel_id is not None

    def test_map_invariants(self, world: World):
        world.grid.assert_plot_road_access()
        assert len(world.grid.cities) == 5
        assert len(world.companies) == 6  # player + 5 AI
        for city in world.grid.cities.values():
            assert len(city.territory) > 0
            assert len(world.owned_plots("city", city.id)) == 1

    def test_content_loaded(self, world: World):
        assert world.buildings.has("foundry")
        assert world.production.get("make_steel").building_id == "foundry"
        ids = {i.id for i in world.items.all()}
        assert ids == {"iron", "coal", "energy", "steel"}


class TestBuyBuildRoadMerge:
    def test_buy_plot_success_and_cash(self, world: World):
        player = world.companies["player"]
        before = player.cash
        plot = _unowned_plot(world)
        price = plot.plot.price
        result = world.buy_plot("company", "player", plot.x, plot.y)
        assert result.ok
        assert player.cash == before - price
        assert plot.plot.owned_by("company", "player")

    def test_buy_already_owned(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        with pytest.raises(ActionError, match="already owned"):
            world.buy_plot("company", "player", owned.x, owned.y)

    def test_buy_road_cell(self, world: World):
        road = next(t for t in world.grid.tiles if t.kind == TileKind.ROAD)
        with pytest.raises(ActionError, match="Not a buyable plot"):
            world.buy_plot("company", "player", road.x, road.y)

    def test_buy_out_of_bounds(self, world: World):
        with pytest.raises(ActionError, match="Out of bounds"):
            world.buy_plot("company", "player", 9999, 9999)
        with pytest.raises(ActionError, match="Out of bounds"):
            world.buy_plot("company", "player", -1, -1)

    def test_buy_insufficient_cash(self, world: World):
        world.companies["player"].cash = 0
        plot = _unowned_plot(world)
        with pytest.raises(ActionError, match="Not enough cash"):
            world.buy_plot("company", "player", plot.x, plot.y)

    def test_build_foundry_and_reject_duplicate(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        player = world.companies["player"]
        before = player.cash
        result = world.build_building("company", "player", owned.x, owned.y)
        assert result.ok
        assert player.cash == before - 200
        assert owned.plot.building.building_id == "foundry"
        assert owned.plot.building.production_method_id == "make_steel"
        with pytest.raises(ActionError, match="already has a building"):
            world.build_building("company", "player", owned.x, owned.y)

    def test_build_unknown_and_unowned(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        with pytest.raises(ActionError, match="Unknown building"):
            world.build_building("company", "player", owned.x, owned.y, "warehouse")
        plot = _unowned_plot(world)
        with pytest.raises(ActionError, match="do not own"):
            world.build_building("company", "player", plot.x, plot.y)

    def test_build_out_of_bounds_rejected(self, world: World):
        with pytest.raises(ActionError, match="Out of bounds"):
            world.build_building("company", "player", 9999, 9999)
        # Former silent alias into an in-bounds owned cell
        with pytest.raises(ActionError, match="Out of bounds"):
            world.build_building("company", "player", 48, 4)

    def test_build_road_on_unowned_plot(self, world: World):
        player = world.companies["player"]
        plot = _unowned_plot(world)
        before = player.cash
        result = world.company_build_road("player", plot.x, plot.y)
        assert result.ok
        assert player.cash == before - world.config.road_build_cost
        assert world.grid.get(plot.x, plot.y).kind == TileKind.ROAD

    def test_cannot_build_road_on_owned_or_existing(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        with pytest.raises(ActionError, match="Cannot build road"):
            world.company_build_road("player", owned.x, owned.y)
        road = next(t for t in world.grid.tiles if t.kind == TileKind.ROAD)
        with pytest.raises(ActionError, match="Cannot build road"):
            world.company_build_road("player", road.x, road.y)

    def test_merge_adjacent_owned_plots(self, world: World):
        pair = _adjacent_unowned_pair(world, "company", "player")
        assert pair is not None, "need adjacent unowned plot for merge test"
        a, b = pair
        world.buy_plot("company", "player", b.x, b.y)
        result = world.merge_plots("company", "player", a.x, a.y, b.x, b.y)
        assert result.ok
        assert result.data["size"] == 2
        assert a.plot.parcel_id == b.plot.parcel_id
        bonus = world.grid.production_bonus_for_plot(a.plot)
        assert bonus == pytest.approx(1.05)

    def test_merge_rejects_non_adjacent_and_oob(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        far = _unowned_plot(world)
        # buy a non-adjacent plot if needed
        if abs(owned.x - far.x) + abs(owned.y - far.y) == 1:
            far = next(
                t
                for t in world.grid.tiles
                if t.kind == TileKind.PLOT
                and t.plot
                and not t.plot.is_owned
                and abs(t.x - owned.x) + abs(t.y - owned.y) > 1
            )
        world.buy_plot("company", "player", far.x, far.y)
        with pytest.raises(ActionError, match="adjacent"):
            world.merge_plots("company", "player", owned.x, owned.y, far.x, far.y)
        with pytest.raises(ActionError, match="Out of bounds"):
            world.merge_plots("company", "player", owned.x, owned.y, 9999, 9999)


class TestProductionAndPause:
    def test_pause_stops_time_and_production(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        world.build_building("company", "player", owned.x, owned.y)
        world.set_paused(True)
        t0, steel0 = world.time_sec, world.companies["player"].inventory.get("steel")
        for _ in range(100):
            world.tick(0.1)
        assert world.time_sec == t0
        assert world.companies["player"].inventory.get("steel") == steel0

    def test_foundry_produces_steel(self, world: World):
        player = world.companies["player"]
        owned = world.owned_plots("company", "player")[0]
        world.build_building("company", "player", owned.x, owned.y)
        steel0 = player.inventory.get("steel")
        iron0 = player.inventory.get("iron")
        for _ in range(60):  # 6s at 0.1; recipe is 5s
            world.tick(0.1)
        assert player.inventory.get("steel") == steel0 + 1
        assert player.inventory.get("iron") == iron0 - 1
        assert player.inventory.get("coal") == 19
        assert player.inventory.get("energy") == 19

    def test_production_waits_when_inputs_missing(self, world: World):
        player = world.companies["player"]
        owned = world.owned_plots("company", "player")[0]
        world.build_building("company", "player", owned.x, owned.y)
        player.inventory.quantities.clear()
        for _ in range(100):
            world.tick(0.1)
        assert player.inventory.get("steel") == 0
        assert owned.plot.building.progress == pytest.approx(1.0)

    def test_parcel_bonus_speeds_production(self, world: World):
        pair = _adjacent_unowned_pair(world, "company", "player")
        assert pair is not None
        a, b = pair
        world.buy_plot("company", "player", b.x, b.y)
        world.merge_plots("company", "player", a.x, a.y, b.x, b.y)
        world.build_building("company", "player", a.x, a.y)
        player = world.companies["player"]
        # With 1.05 bonus, 5s recipe completes in ~4.76s
        for _ in range(48):
            world.tick(0.1)
        assert player.inventory.get("steel") >= 1


class TestGridBounds:
    def test_get_rejects_oob_and_aliases(self, world: World):
        with pytest.raises(IndexError):
            world.grid.get(9999, 9999)
        with pytest.raises(IndexError):
            world.grid.get(-1, 0)
        with pytest.raises(IndexError):
            world.grid.get(world.grid.width, 0)


class TestLLMTools:
    def test_build_actor_context_with_building(self, world: World):
        owned = world.owned_plots("company", "player")[0]
        world.build_building("company", "player", owned.x, owned.y)
        ctx = build_actor_context(world, world.companies["player"])
        assert "foundry" in ctx
        assert "Cash:" in ctx

    def test_tool_executor_actions(self, world: World):
        player = world.companies["player"]
        ex = ToolExecutor(world, player)
        status = ex.execute("get_status", {})
        assert status["ok"]
        assert status["data"]["cash"] == player.cash
        market = ex.execute("get_market_overview", {"limit": 3})
        assert market["ok"]
        assert len(market["data"]["unowned_plots"]) <= 3
        plot = market["data"]["unowned_plots"][0]
        bought = ex.execute("buy_plot", {"x": plot["x"], "y": plot["y"]})
        assert bought["ok"]
        bad = ex.execute("buy_plot", {"x": plot["x"], "y": plot["y"]})
        assert bad["ok"] is False
        done = ex.execute("done", {"note": "finished"})
        assert done["ok"]
        assert ex.done_note == "finished"
        unknown = ex.execute("nope", {})
        assert unknown["ok"] is False


class TestContentValidation:
    def test_broken_building_ref_fails(self, tmp_path):
        (tmp_path / "items.yaml").write_text(
            "items:\n  - id: iron\n    name: Iron\n  - id: steel\n    name: Steel\n",
            encoding="utf-8",
        )
        (tmp_path / "buildings.yaml").write_text(
            "buildings:\n  - id: foundry\n    name: Foundry\n    build_cost: 100\n",
            encoding="utf-8",
        )
        (tmp_path / "production_methods.yaml").write_text(
            "production_methods:\n  - id: bad\n    building_id: missing\n"
            "    inputs: {iron: 1}\n    outputs: {steel: 1}\n    duration_sec: 1\n",
            encoding="utf-8",
        )
        from company_sim.content import GameContent

        with pytest.raises(ValueError, match="unknown building"):
            GameContent.load(tmp_path)
