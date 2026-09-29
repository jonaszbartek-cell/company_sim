"""One-city 1..30 small cos + two-city random-site road wiring tests."""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

import pytest

from company_sim.roads import active_road_sides, manhattan, plots_road_connected
from company_sim.small_companies import (
    city_hall_coord,
    spawn_small_companies,
    wire_startup_roads,
)
from company_sim.world import World, WorldConfig


def _base_world(td: Path, **kwargs) -> World:
    cfg = dict(
        map_size=24,
        starting_cities=1,
        ai_company_count=0,
        small_companies_per_city=0,
        save_dir=str(td),
        min_seconds_between_turns=0.0,
        market_seed_qty=5,
        market_seed_price=1,
        specialized_plot_percent=10.0,
    )
    cfg.update(kwargs)
    return World.new_game(WorldConfig(**cfg))


def _assert_all_small_connected(world: World) -> int:
    halls = {
        city.id: city_hall_coord(world, city.id) for city in world.grid.cities.values()
    }
    for h in halls.values():
        assert h is not None
        assert active_road_sides(world.grid, *h) == ["N", "E", "S", "W"]
    hall_list = [h for h in halls.values() if h is not None]
    if len(hall_list) >= 2:
        for h in hall_list[1:]:
            assert plots_road_connected(world.grid, hall_list[0], h)

    n = 0
    for co in world.companies.values():
        if not co.is_small:
            continue
        tile = next(
            t
            for t in world.owned_plots("company", co.id)
            if t.plot and t.plot.building
        )
        hall = halls.get(co.home_city_id or "")
        assert hall is not None
        assert active_road_sides(world.grid, tile.x, tile.y), (co.id, tile.x, tile.y)
        assert plots_road_connected(world.grid, (tile.x, tile.y), hall), (
            co.id,
            (tile.x, tile.y),
            hall,
        )
        n += 1
    return n


@pytest.mark.parametrize("small_n", list(range(1, 31)))
def test_one_city_small_companies_1_to_30(small_n: int) -> None:
    """Single city with N small companies (1..30) — every building reaches the hall."""
    # Grow map with company count so nearest-hall placement always has room
    map_size = max(16, 8 + small_n)
    with tempfile.TemporaryDirectory() as td:
        w = _base_world(
            Path(td),
            map_size=map_size,
            starting_cities=1,
            small_companies_per_city=small_n,
        )
        spawned = _assert_all_small_connected(w)
        assert spawned == small_n, (spawned, small_n)


@pytest.mark.parametrize("seed", [1, 7, 42, 99])
@pytest.mark.parametrize("per_city", [5, 10, 15])
def test_two_cities_companies_placed_randomly_not_near_hall(
    seed: int, per_city: int
) -> None:
    """Two cities; companies on random city plots (not hall-adjacent rings).

    Stresses street pathfinding when spokes are long and scattered.
    """
    with tempfile.TemporaryDirectory() as td:
        w = _base_world(
            Path(td),
            map_size=36,
            starting_cities=2,
            small_companies_per_city=0,  # spawn ourselves with random_sites
            city_placement_seed=seed,
        )
        # No small cos yet; halls already have all-side seeds from wire at start
        # (wire ran with zero spokes). Re-spawn randomly then re-wire.
        w.config.small_companies_per_city = per_city
        rng = random.Random(seed + per_city)
        created = spawn_small_companies(w, rng=rng, random_sites=True)
        assert len(created) == 2 * per_city

        # Confirm most companies are NOT adjacent to their hall
        far = 0
        for co in created:
            tile = next(
                t
                for t in w.owned_plots("company", co.id)
                if t.plot and t.plot.building
            )
            hall = city_hall_coord(w, co.home_city_id)  # type: ignore[arg-type]
            assert hall is not None
            if manhattan((tile.x, tile.y), hall) >= 3:
                far += 1
        assert far >= len(created) // 2, (far, len(created))

        wire_startup_roads(w)
        spawned = _assert_all_small_connected(w)
        assert spawned == 2 * per_city


def test_two_cities_random_sites_twenty_each() -> None:
    """Heavier random-site case: 2 cities × 20 scattered companies."""
    with tempfile.TemporaryDirectory() as td:
        w = _base_world(
            Path(td),
            map_size=48,
            starting_cities=2,
            small_companies_per_city=0,
            city_placement_seed=123,
        )
        w.config.small_companies_per_city = 20
        created = spawn_small_companies(w, rng=random.Random(123), random_sites=True)
        assert len(created) == 40
        dists = []
        for co in created:
            tile = next(
                t
                for t in w.owned_plots("company", co.id)
                if t.plot and t.plot.building
            )
            hall = city_hall_coord(w, co.home_city_id)  # type: ignore[arg-type]
            assert hall is not None
            dists.append(manhattan((tile.x, tile.y), hall))
        assert sum(1 for d in dists if d >= 3) >= 20
        assert max(dists) >= 5
        wire_startup_roads(w)
        assert _assert_all_small_connected(w) == 40
