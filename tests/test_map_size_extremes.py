"""Extreme rectangular (square) map sizes — boot, ops, API bounds."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from company_sim.actions import ActionError
from company_sim.server import create_app
from company_sim.world import World, WorldConfig


def _world(td: Path, *, size: int, cities: int = 1, ai: int = 0) -> World:
    return World.new_game(
        WorldConfig(
            map_size=size,
            starting_cities=cities,
            ai_company_count=ai,
            save_dir=str(td),
            min_seconds_between_turns=0.0,
            market_seed_qty=0,
        )
    )


@pytest.mark.parametrize("size", [2, 12, 40, 64, 100, 128])
def test_square_rectangle_boot_and_dimensions(size: int):
    """Maps stay NxN rectangles at every supported size."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=size)
        assert w.config.map_size == size
        assert w.config.map_w == size and w.config.map_h == size
        assert w.grid.width == size and w.grid.height == size
        assert len(w.grid.tiles) == size * size
        # Rectangle filled: every in-bounds cell exists exactly once
        coords = {(t.x, t.y) for t in w.grid.tiles}
        assert coords == {(x, y) for x in range(size) for y in range(size)}
        assert all(t.plot is not None for t in w.grid.tiles)
        pub = w.grid.to_public_dict()
        assert pub["width"] == size and pub["height"] == size
        assert len(pub["tiles"]) == size * size


def test_legacy_width_height_still_fold_to_square_rectangle():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_width=20,
                map_height=48,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(td),
                min_seconds_between_turns=0.0,
            )
        )
        # Keep square-rectangle policy: fold to max side
        assert w.config.map_size == 48
        assert w.grid.width == 48 and w.grid.height == 48


def test_extremely_big_map_build_road_produce_merge():
    """100x100 rectangle: land ops still work at corners and mid-map."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=100, cities=1, ai=0)
        player = w.companies["player"]
        player.cash = 50_000
        player.inventory.set("construction_materials", 80)
        player.inventory.set("steel", 10)
        player.inventory.set("iron_ore", 5)
        player.inventory.set("coal", 5)
        player.inventory.set("energy", 5)

        # Mid-map empty land
        x, y = 50, 50
        tile = w.grid.get(x, y)
        assert tile.plot and tile.plot.owner_kind == "city"
        tile.plot.claim("company", "player")
        built = w.build_building("company", "player", x, y, "foundry")
        assert built.ok, built.message
        player.acted_this_day = False
        road = w.build_road("company", "player", x, y, "N")
        assert road.ok, road.message
        player.acted_this_day = False
        for item in ("iron_ore", "coal", "energy"):
            w.deposit_to_building("company", "player", x, y, item, 1)
            player.acted_this_day = False
        produced = w.produce("company", "player", x, y)
        assert produced.ok, produced.message

        # Expand footprint onto neighbor (still a rectangle)
        nx, ny = x + 1, y
        w.grid.get(nx, ny).plot.claim("company", "player")
        player.acted_this_day = False
        merged = w.merge_plots("company", "player", x, y, nx, ny)
        assert merged.ok, merged.message
        b = w.grid.get(x, y).plot.building
        assert b is not None
        assert b.footprint_w == 2 and b.footprint_h == 1


def test_extremely_big_map_corners_and_far_edge():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=128, cities=1, ai=0)
        for x, y in ((0, 0), (127, 0), (0, 127), (127, 127), (64, 64)):
            t = w.grid.get(x, y)
            assert t.plot is not None
            assert t.city_id == "city_a"
        assert not w.grid.in_bounds(128, 0)
        assert not w.grid.in_bounds(0, 128)


def test_big_map_multi_city_territory_covers_all_cells():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=64, cities=4, ai=0)
        assert len(w.grid.cities) == 4
        owners = {t.plot.owner_id for t in w.grid.tiles if t.plot}
        assert owners == set(w.grid.cities.keys())
        assert all(t.city_id in w.grid.cities for t in w.grid.tiles)


def test_big_map_save_reload_roundtrip_stays_square():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root, size=64, cities=2, ai=1)
        w.persistence.save_all(w)
        # Reload via public dict shape / world.txt presence
        assert (root / "world.txt").is_file()
        text = (root / "world.txt").read_text(encoding="utf-8")
        assert "64x64" in text
        pub = w.to_public_dict()
        assert pub["config"]["map_size"] == 64
        assert pub["map"]["width"] == 64 and pub["map"]["height"] == 64


def test_api_allows_large_square_and_rejects_beyond_cap(monkeypatch, tmp_path):
    import company_sim.world as world_mod

    monkeypatch.setattr(world_mod, "default_save_dir", lambda: tmp_path)
    app = create_app()
    c = TestClient(app)
    ok = c.post(
        "/api/setup",
        json={"ai_companies": 0, "cities": 1, "map_size": 128, "llm_debug": False},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["state"]["config"]["map_size"] == 128
    assert body["state"]["map"]["width"] == 128
    assert body["state"]["map"]["height"] == 128

    too_big = c.post(
        "/api/setup",
        json={"ai_companies": 0, "cities": 1, "map_size": 129},
    )
    assert too_big.status_code == 422


def test_reject_map_size_below_two():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ActionError):
            _world(Path(td), size=1)
