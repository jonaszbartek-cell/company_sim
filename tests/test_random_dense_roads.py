"""Dense / random-city startup road connectivity tests."""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

import pytest

from company_sim.map_grid import place_city_seeds
from company_sim.roads import active_road_sides, plots_road_connected
from company_sim.small_companies import city_hall_coord
from company_sim.world import World, WorldConfig


def _world(td: Path, **kwargs) -> World:
    cfg = dict(
        map_size=48,
        starting_cities=5,
        ai_company_count=0,
        small_companies_per_city=20,
        save_dir=str(td),
        min_seconds_between_turns=0.0,
        market_seed_qty=5,
        market_seed_price=1,
        specialized_plot_percent=10.0,
        city_placement_seed=42,
    )
    cfg.update(kwargs)
    return World.new_game(WorldConfig(**cfg))


def _assert_random_not_collinear(points: list[tuple[int, int]]) -> None:
    """Centers must not all share one row or one column (not a single line)."""
    assert len(points) >= 3
    xs = {p[0] for p in points}
    ys = {p[1] for p in points}
    assert len(xs) > 1 and len(ys) > 1, points


def _assert_all_connected(world: World) -> tuple[int, int]:
    halls: dict[str, tuple[int, int]] = {}
    for city in world.grid.cities.values():
        h = city_hall_coord(world, city.id)
        assert h is not None
        assert active_road_sides(world.grid, *h) == ["N", "E", "S", "W"]
        halls[city.id] = h

    hall_list = list(halls.values())
    for h in hall_list[1:]:
        assert plots_road_connected(world.grid, hall_list[0], h), (hall_list[0], h)

    smalls = [c for c in world.companies.values() if c.is_small]
    connected = 0
    for co in smalls:
        tile = next(
            t
            for t in world.owned_plots("company", co.id)
            if t.plot and t.plot.building
        )
        hall = halls[co.home_city_id]  # type: ignore[index]
        assert active_road_sides(world.grid, tile.x, tile.y)
        assert plots_road_connected(world.grid, (tile.x, tile.y), hall), (
            co.id,
            tile.x,
            tile.y,
            hall,
        )
        connected += 1
    return len(smalls), connected


def test_place_city_seeds_random_not_in_line():
    rng = random.Random(99)
    pts = place_city_seeds(64, 5, rng=rng)
    assert len(pts) == 5
    assert len(set(pts)) == 5
    _assert_random_not_collinear(pts)
    # Deterministic for same seed
    assert place_city_seeds(64, 5, rng=random.Random(99)) == pts


def test_five_cities_twenty_small_cos_random_placement():
    """Primary ask: 5 randomly placed cities × 20 small companies each."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(
            Path(td),
            map_size=64,
            starting_cities=5,
            small_companies_per_city=20,
            city_placement_seed=20260929,
        )
        centers = [(c.center_x, c.center_y) for c in w.grid.cities.values()]
        _assert_random_not_collinear(centers)
        spawned, connected = _assert_all_connected(w)
        # Full quota when map/territory allows
        assert spawned == 100, spawned
        assert connected == 100


@pytest.mark.parametrize(
    "cities,small_n,map_size,seed",
    [
        (5, 20, 56, 7),
        (5, 12, 48, 11),
        (4, 20, 48, 13),
        (3, 20, 40, 17),
        (6, 15, 64, 19),
        (8, 10, 64, 23),
        (2, 20, 36, 29),
        (5, 8, 40, 31),
    ],
)
def test_random_city_dense_variants(
    cities: int, small_n: int, map_size: int, seed: int
) -> None:
    with tempfile.TemporaryDirectory() as td:
        w = _world(
            Path(td),
            map_size=map_size,
            starting_cities=cities,
            small_companies_per_city=small_n,
            city_placement_seed=seed,
        )
        centers = [(c.center_x, c.center_y) for c in w.grid.cities.values()]
        if cities >= 3:
            _assert_random_not_collinear(centers)
        spawned, connected = _assert_all_connected(w)
        expected = cities * small_n
        assert spawned == expected, (spawned, expected)
        assert connected == expected


def test_api_setup_accepts_city_placement_seed():
    from fastapi.testclient import TestClient

    from company_sim.server import create_app

    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/api/setup",
        json={
            "ai_companies": 0,
            "small_companies_per_city": 2,
            "cities": 3,
            "map_size": 24,
            "city_placement_seed": 55,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    st = body["state"]
    cities = st["map"]["cities"]
    centers = [(c["center_x"], c["center_y"]) for c in cities]
    assert len(centers) == 3
    _assert_random_not_collinear(centers)
