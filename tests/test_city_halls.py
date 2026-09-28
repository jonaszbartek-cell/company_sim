"""City Hall: every city starts with one near its territory center."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.content import GameContent
from company_sim.world import World, WorldConfig


def _world(
    td: Path,
    *,
    size: int,
    cities: int = 1,
    ai: int = 0,
) -> World:
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


def _city_halls(world: World) -> list[tuple[str, int, int]]:
    """Unique city_hall instances as (city_id, anchor_x, anchor_y)."""
    seen: dict[str, tuple[str, int, int]] = {}
    for tile in world.grid.tiles:
        plot = tile.plot
        if not plot or not plot.building:
            continue
        b = plot.building
        if b.building_id != "city_hall":
            continue
        if b.id in seen:
            continue
        seen[b.id] = (b.owner_id, b.anchor_x or tile.x, b.anchor_y or tile.y)
    return list(seen.values())


def test_city_hall_in_catalog_and_inert():
    c = GameContent.load()
    hall = c.buildings.get("city_hall")
    assert hall.name == "City Hall"
    assert hall.buildable is False
    assert c.methods_for_building("city_hall") == []
    assert c.storage_capacity_for_building("city_hall") == {}


def test_city_halls_placed_by_engine_at_new_game_not_buildable():
    """Halls exist immediately after World.new_game; build_building cannot create them."""
    from company_sim.actions import ActionError

    with tempfile.TemporaryDirectory() as td:
        # Zero AI companies — no agent turns; halls must still exist right after boot
        w = _world(Path(td), size=12, cities=2, ai=0)
        assert w.started
        halls = _city_halls(w)
        assert len(halls) == 2
        for city_id, hx, hy in halls:
            b = w.grid.get(hx, hy).plot.building
            assert b is not None
            assert b.building_id == "city_hall"
            assert b.owner_kind == "city"
            assert b.owner_id == city_id

        # Agents / players / cities cannot construct City Hall via build_building
        city = next(iter(w.grid.cities.values()))
        empty = next(
            t
            for t in w.grid.tiles
            if t.plot
            and t.plot.owned_by("city", city.id)
            and t.plot.building is None
        )
        cash_before = city.cash
        with pytest.raises(ActionError, match="engine at game start"):
            w.build_building("city", city.id, empty.x, empty.y, "city_hall")
        assert city.cash == cash_before

        player = w.companies["player"]
        empty.plot.claim("company", "player")
        player.cash = 10_000
        player.inventory.set("construction_materials", 50)
        with pytest.raises(ActionError, match="engine at game start"):
            w.build_building("company", "player", empty.x, empty.y, "city_hall")


@pytest.mark.parametrize("size", [2, 8, 12, 24, 40, 64, 100])
@pytest.mark.parametrize("ai", [0, 1, 2, 5])
def test_one_hall_per_city_across_map_sizes_and_companies(size: int, ai: int):
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=size, cities=1, ai=ai)
        assert len(w.companies) == 1 + ai  # player + AI rivals
        halls = _city_halls(w)
        assert len(halls) == 1
        city_id, hx, hy = halls[0]
        city = w.grid.cities[city_id]
        assert city_id == city.id
        # Roughly at territory center (seed is map midpoint for one city)
        assert abs(hx - city.center_x) + abs(hy - city.center_y) <= max(2, size // 8)
        tile = w.grid.get(hx, hy)
        assert tile.plot and tile.plot.building
        b = tile.plot.building
        assert b.owner_kind == "city"
        assert b.owner_id == city_id
        assert b.production_method_id is None
        assert b.status == "idle"
        # Inert: produce must fail
        from company_sim.actions import ActionError

        with pytest.raises(ActionError):
            w.produce("city", city_id, hx, hy)


@pytest.mark.parametrize(
    "size,cities,ai",
    [
        (12, 2, 0),
        (12, 2, 3),
        (16, 3, 1),
        (20, 4, 2),
        (24, 4, 5),
        (40, 3, 8),
        (64, 2, 4),
        (8, 2, 0),
        (100, 4, 2),
    ],
)
def test_multiple_cities_and_companies_each_get_one_hall(
    size: int, cities: int, ai: int
):
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=size, cities=cities, ai=ai)
        assert len(w.grid.cities) == cities
        assert len(w.companies) == 1 + ai
        halls = _city_halls(w)
        assert len(halls) == cities
        by_city = {cid: (x, y) for cid, x, y in halls}
        assert set(by_city) == set(w.grid.cities)
        for cid, (hx, hy) in by_city.items():
            city = w.grid.cities[cid]
            # Hall sits on a city-owned plot in that city's territory
            tile = w.grid.get(hx, hy)
            assert tile.city_id == cid
            assert tile.plot and tile.plot.owned_by("city", cid)
            # Near the city's seed center
            assert abs(hx - city.center_x) + abs(hy - city.center_y) <= max(
                3, size // 6
            )


def test_city_hall_free_at_start_does_not_charge_city():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), size=12, cities=1, ai=0)
        city = next(iter(w.grid.cities.values()))
        # Starting cash untouched by free placement (cities start at seed cash)
        assert city.cash >= 1000
        halls = _city_halls(w)
        assert len(halls) == 1
