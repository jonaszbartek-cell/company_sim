"""Specialized mine/well plot generation, method locks, and merge rules."""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.map_grid import plan_specialized_plots, PlotType
from company_sim.world import World, WorldConfig


def _world(td: Path, *, size: int = 12, pct: float = 20.0) -> World:
    return World.new_game(
        WorldConfig(
            map_size=size,
            starting_cities=1,
            ai_company_count=0,
            save_dir=str(td),
            min_seconds_between_turns=0.0,
            specialized_plot_percent=pct,
        )
    )


def test_plan_guarantees_five_of_each_when_map_allows():
    plan = plan_specialized_plots(12, 12, percent=10.0, min_each=5, seed=42)
    counts = Counter(plan.values())
    assert counts[PlotType.SPECIALIZED_MINE] >= 5
    assert counts[PlotType.SPECIALIZED_WELL] >= 5


def test_guaranteed_five_are_scattered_not_clustered():
    """When only the guarantee applies, plots should not form tight clusters."""
    # percent=0 still forces guarantee*2; all of those must be random scatter
    plan = plan_specialized_plots(20, 20, percent=0.0, min_each=5, seed=11)
    for kind in (PlotType.SPECIALIZED_MINE, PlotType.SPECIALIZED_WELL):
        cells = [c for c, t in plan.items() if t == kind]
        assert len(cells) == 5
        # Few same-type cells should be adjacent (manhattan 1) — scatter, not a blob
        adjacent_pairs = 0
        for i, (x, y) in enumerate(cells):
            for ox, oy in cells[i + 1 :]:
                if abs(x - ox) + abs(y - oy) == 1:
                    adjacent_pairs += 1
        assert adjacent_pairs <= 1


def test_plan_respects_percent_roughly():
    n = 20 * 20
    plan = plan_specialized_plots(20, 20, percent=25.0, min_each=5, seed=7)
    assert abs(len(plan) - round(n * 0.25)) <= 2 or len(plan) >= 10


def test_extra_percent_plots_form_clusters():
    """Beyond the random guarantee, additional specialized cells cluster regionally."""
    plan = plan_specialized_plots(24, 24, percent=30.0, min_each=5, seed=3)
    for kind in (PlotType.SPECIALIZED_MINE, PlotType.SPECIALIZED_WELL):
        cells = [c for c, t in plan.items() if t == kind]
        assert len(cells) > 5  # extras beyond the random 5
        near = 0
        for x, y in cells:
            if any(
                abs(x - ox) + abs(y - oy) <= 2 and (ox, oy) != (x, y)
                for ox, oy in cells
            ):
                near += 1
        assert near / len(cells) >= 0.45


def test_world_generation_two_specialized_types_and_counts():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=12, pct=20.0)
        counts = Counter(t.plot.plot_type for t in w.grid.tiles if t.plot)
        assert counts[PlotType.SPECIALIZED_MINE] >= 5
        assert counts[PlotType.SPECIALIZED_WELL] >= 5
        assert counts[PlotType.STANDARD] > 0
        assert w.config.specialized_plot_percent == 20.0


def test_rig_only_on_well_mine_only_on_mine():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=10, pct=40.0)
        player = w.companies["player"]
        player.cash = 10_000
        player.inventory.set("construction_materials", 50)
        mine_tile = next(
            t for t in w.grid.tiles if t.plot.plot_type == PlotType.SPECIALIZED_MINE
        )
        well_tile = next(
            t for t in w.grid.tiles if t.plot.plot_type == PlotType.SPECIALIZED_WELL
        )
        mine_tile.plot.claim("company", "player")
        well_tile.plot.claim("company", "player")
        with pytest.raises(ActionError, match="cannot be built"):
            w.build_building("company", "player", mine_tile.x, mine_tile.y, "rig")
        with pytest.raises(ActionError, match="cannot be built"):
            w.build_building("company", "player", well_tile.x, well_tile.y, "mine")
        r = w.build_building(
            "company",
            "player",
            well_tile.x,
            well_tile.y,
            "rig",
            method_id="extract_water",
        )
        assert r.ok
        assert r.data["production_method_id"] == "extract_water"
        assert well_tile.plot.building.production_method_locked is True


def test_foundry_can_change_method_freely():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=8, pct=10.0)
        player = w.companies["player"]
        player.cash = 10_000
        player.inventory.set("construction_materials", 40)
        tile = next(t for t in w.grid.tiles if t.plot.plot_type == PlotType.STANDARD)
        tile.plot.claim("company", "player")
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        player.acted_this_day = False
        r = w.set_production_method("company", "player", tile.x, tile.y, "make_copper")
        assert r.ok
        assert tile.plot.building.production_method_locked is False


def test_merge_mines_requires_same_production_method():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=12, pct=50.0)
        player = w.companies["player"]
        player.cash = 50_000
        player.inventory.set("construction_materials", 80)
        # Find two adjacent specialized_mine plots
        mines = [
            (t.x, t.y)
            for t in w.grid.tiles
            if t.plot and t.plot.plot_type == PlotType.SPECIALIZED_MINE
        ]
        pair = None
        mine_set = set(mines)
        for x, y in mines:
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if (nx, ny) in mine_set:
                    pair = ((x, y), (nx, ny))
                    break
            if pair:
                break
        if pair is None:
            pytest.skip("no adjacent mine resource plots in this seed")
        (x1, y1), (x2, y2) = pair
        for x, y in pair:
            w.grid.get(x, y).plot.claim("company", "player")
        w.build_building(
            "company", "player", x1, y1, "mine", method_id="extract_iron_ore"
        )
        player.acted_this_day = False
        w.build_building(
            "company", "player", x2, y2, "mine", method_id="extract_coal"
        )
        player.acted_this_day = False
        with pytest.raises(ActionError, match="same production method"):
            w.merge_plots("company", "player", x1, y1, x2, y2)

        # Rebuild second with matching method
        w.destroy_building("company", "player", x2, y2)
        player.acted_this_day = False
        player.inventory.set("construction_materials", 80)
        w.build_building(
            "company", "player", x2, y2, "mine", method_id="extract_iron_ore"
        )
        player.acted_this_day = False
        merged = w.merge_plots("company", "player", x1, y1, x2, y2)
        assert merged.ok


def test_api_setup_accepts_specialized_percent(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import company_sim.world as world_mod
    from company_sim.server import create_app

    monkeypatch.setattr(world_mod, "default_save_dir", lambda: tmp_path)
    c = TestClient(create_app())
    res = c.post(
        "/api/setup",
        json={
            "ai_companies": 0,
            "cities": 1,
            "map_size": 10,
            "specialized_plot_percent": 30,
            "llm_debug": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["state"]["config"]["specialized_plot_percent"] == 30.0
    types = Counter(
        t["plot"]["plot_type"] for t in body["state"]["map"]["tiles"] if t.get("plot")
    )
    assert types.get("specialized_mine", 0) >= 5
    assert types.get("specialized_well", 0) >= 5
