"""Matrix / random / large-map tests for edge-street startup road wiring."""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

import pytest

from company_sim.map_grid import GridMap
from company_sim.plots import Plot, PlotType
from company_sim.roads import (
    active_road_sides,
    connect_points_mst,
    connect_star,
    plots_road_connected,
    seed_all_side_roads,
)
from company_sim.small_companies import city_hall_coord
from company_sim.world import World, WorldConfig


def _empty_grid(size: int) -> GridMap:
    g = GridMap.create(size, size)
    for t in g.tiles:
        t.plot = Plot(plot_type=PlotType.STANDARD, value=100)
        t.city_id = "city_a"
    g.rebuild_plot_index()
    return g


def _world(td: Path, **kwargs) -> World:
    cfg = dict(
        map_size=16,
        starting_cities=2,
        ai_company_count=0,
        small_companies_per_city=2,
        save_dir=str(td),
        min_seconds_between_turns=0.0,
        market_seed_qty=5,
        market_seed_price=1,
        specialized_plot_percent=10.0,
    )
    cfg.update(kwargs)
    return World.new_game(WorldConfig(**cfg))


def _building_site(world: World, company_id: str) -> tuple[int, int]:
    tiles = [
        t
        for t in world.owned_plots("company", company_id)
        if t.plot and t.plot.building
    ]
    assert tiles, f"no building for {company_id}"
    return tiles[0].x, tiles[0].y


def _assert_all_small_cos_street_connected(world: World) -> None:
    halls: dict[str, tuple[int, int]] = {}
    for city in world.grid.cities.values():
        h = city_hall_coord(world, city.id)
        assert h is not None, city.id
        assert active_road_sides(world.grid, *h) == ["N", "E", "S", "W"], h
        halls[city.id] = h

    # Halls form one street-connected network when 2+
    hall_list = list(halls.values())
    if len(hall_list) >= 2:
        for h in hall_list[1:]:
            assert plots_road_connected(world.grid, hall_list[0], h), (hall_list[0], h)

    smalls = [c for c in world.companies.values() if c.is_small]
    assert smalls, "expected small companies"
    for co in smalls:
        site = _building_site(world, co.id)
        hall = halls.get(co.home_city_id or "")
        assert hall is not None, co.id
        assert active_road_sides(world.grid, *site), (co.id, site)
        assert plots_road_connected(world.grid, site, hall), (co.id, site, hall)


# ---------------------------------------------------------------------------
# Parametrized matrix: cities × small companies × map size
# ---------------------------------------------------------------------------

# Keep combos feasible: enough cells for cities + near-hall company plots.
STARTUP_MATRIX = [
    # (cities, small_per_city, map_size)
    (1, 1, 8),
    (1, 4, 12),
    (1, 8, 16),
    (2, 2, 12),
    (2, 4, 16),
    (2, 6, 20),
    (3, 3, 18),
    (3, 5, 24),
    (4, 2, 20),
    (4, 4, 24),
    (5, 3, 28),
    (6, 2, 32),
    (8, 2, 36),
    (2, 10, 24),
    (3, 8, 32),
]


@pytest.mark.parametrize("cities,small_n,map_size", STARTUP_MATRIX)
def test_startup_matrix_all_small_cos_reach_hall(
    cities: int, small_n: int, map_size: int
) -> None:
    with tempfile.TemporaryDirectory() as td:
        w = _world(
            Path(td),
            map_size=map_size,
            starting_cities=cities,
            small_companies_per_city=small_n,
        )
        expected = cities * small_n
        got = len([c for c in w.companies.values() if c.is_small])
        # Spawner may place fewer if territory is tight; still require most
        assert got >= max(1, expected // 2), (got, expected)
        assert got <= expected
        _assert_all_small_cos_street_connected(w)


# ---------------------------------------------------------------------------
# Large maps
# ---------------------------------------------------------------------------

LARGE_MAPS = [
    (2, 4, 48),
    (3, 4, 64),
    (4, 3, 80),
    (2, 6, 96),
    (4, 4, 128),
]


@pytest.mark.parametrize("cities,small_n,map_size", LARGE_MAPS)
def test_startup_large_maps_street_connected(
    cities: int, small_n: int, map_size: int
) -> None:
    with tempfile.TemporaryDirectory() as td:
        w = _world(
            Path(td),
            map_size=map_size,
            starting_cities=cities,
            small_companies_per_city=small_n,
        )
        _assert_all_small_cos_street_connected(w)


# ---------------------------------------------------------------------------
# Random halls + companies on a blank grid (engine pathfinding only)
# ---------------------------------------------------------------------------


def _random_distinct_coords(
    rng: random.Random, size: int, count: int, *, min_sep: int = 1
) -> list[tuple[int, int]]:
    """Sample distinct in-bounds coords with optional Chebyshev separation."""
    coords: list[tuple[int, int]] = []
    tries = 0
    while len(coords) < count and tries < count * 200:
        tries += 1
        x = rng.randrange(size)
        y = rng.randrange(size)
        if any(max(abs(x - ox), abs(y - oy)) < min_sep for ox, oy in coords):
            continue
        coords.append((x, y))
    if len(coords) < count:
        # Fallback: pack remaining without separation
        for y in range(size):
            for x in range(size):
                if (x, y) not in coords:
                    coords.append((x, y))
                if len(coords) >= count:
                    return coords
    return coords


@pytest.mark.parametrize("seed", [1, 7, 42, 99, 12345])
@pytest.mark.parametrize("size,n_halls,n_cos_per_hall", [(16, 3, 4), (24, 4, 5), (32, 5, 3)])
def test_random_halls_and_companies_street_network(
    seed: int, size: int, n_halls: int, n_cos_per_hall: int
) -> None:
    """Seed random hall + company sites, wire edge streets, assert full connectivity."""
    rng = random.Random(seed)
    g = _empty_grid(size)
    halls = _random_distinct_coords(rng, size, n_halls, min_sep=3)
    assert len(halls) == n_halls

    # Companies: random sites not on halls
    blocked = set(halls)
    companies: list[tuple[tuple[int, int], tuple[int, int]]] = []  # (site, hall)
    for hall in halls:
        for _ in range(n_cos_per_hall):
            for _attempt in range(200):
                x = rng.randrange(size)
                y = rng.randrange(size)
                if (x, y) in blocked:
                    continue
                blocked.add((x, y))
                companies.append(((x, y), hall))
                break
            else:
                pytest.fail(f"could not place company for hall {hall}")

    # 1) Hall all-sides + double-sided stubs
    for hx, hy in halls:
        assert seed_all_side_roads(g, hx, hy) is True
        assert active_road_sides(g, hx, hy) == ["N", "E", "S", "W"]

    # 2) Hall → each company (edge-street star)
    for site, hall in companies:
        paths = connect_star(g, hall, [site])
        assert paths, (site, hall)
        assert plots_road_connected(g, site, hall), (site, hall)
        assert active_road_sides(g, *site), site

    # 3) Hall ↔ hall MST
    connect_points_mst(g, halls)
    for h in halls[1:]:
        assert plots_road_connected(g, halls[0], h), (halls[0], h)

    # Every company reaches every hall via the shared street network
    for site, _home in companies:
        assert plots_road_connected(g, site, halls[0]), site


@pytest.mark.parametrize("seed", [3, 11, 77])
def test_random_scattered_points_mst_on_big_grid(seed: int) -> None:
    """Many random points on a large grid become one street-connected component."""
    rng = random.Random(seed)
    size = 64
    n_points = 20
    g = _empty_grid(size)
    points = _random_distinct_coords(rng, size, n_points, min_sep=2)
    assert len(points) == n_points
    connect_points_mst(g, points)
    root = points[0]
    for p in points[1:]:
        assert plots_road_connected(g, root, p), (root, p, seed)


def test_tiny_and_huge_extremes() -> None:
    """Smoke: smallest useful map and max API map size."""
    with tempfile.TemporaryDirectory() as td:
        tiny = _world(
            Path(td) / "tiny",
            map_size=6,
            starting_cities=1,
            small_companies_per_city=2,
        )
        _assert_all_small_cos_street_connected(tiny)

    with tempfile.TemporaryDirectory() as td:
        huge = _world(
            Path(td) / "huge",
            map_size=128,
            starting_cities=8,
            small_companies_per_city=3,
        )
        _assert_all_small_cos_street_connected(huge)
