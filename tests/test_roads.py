"""Road pathfinding edge cases + startup network wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.map_grid import GridMap, generate_map, place_city_seeds
from company_sim.plots import OPPOSITE, Plot, PlotType, side_between
from company_sim.roads import (
    connect_points,
    connect_points_mst,
    connect_star,
    connected_component,
    ensure_edge_road,
    ensure_shared_road,
    edge_step_cost,
    lay_roads_along_path,
    manhattan,
    mst_edges,
    plots_road_connected,
    shortest_path,
)
from company_sim.world import World, WorldConfig


def _empty_grid(size: int) -> GridMap:
    g = GridMap.create(size, size)
    for t in g.tiles:
        t.plot = Plot(plot_type=PlotType.STANDARD, value=100)
        t.city_id = "city_a"
    g.rebuild_plot_index()
    return g


def test_ensure_edge_road_idempotent_and_rejects_bad_side():
    g = _empty_grid(4)
    assert ensure_edge_road(g, 1, 1, "E") is True
    assert g.has_road_on_side(1, 1, "E")
    # Second call is a no-op success
    assert ensure_edge_road(g, 1, 1, "E") is True
    assert ensure_edge_road(g, 1, 1, "X") is False
    assert ensure_edge_road(g, -1, 0, "N") is False


def test_ensure_shared_road_either_side_connects():
    g = _empty_grid(4)
    assert ensure_shared_road(g, 1, 1, 2, 1) is True
    assert g.shared_edge_has_road(1, 1, 2, 1)
    # Double-sided is allowed: both plots may mark the shared edge
    assert g.has_road_on_side(1, 1, "E")
    assert g.has_road_on_side(2, 1, "W")
    assert plots_road_connected(g, (1, 1), (2, 1))


def test_double_sided_completes_missing_opposite():
    """If only one plot has the shared side, ensure_shared_road fills the other."""
    g = _empty_grid(3)
    assert ensure_edge_road(g, 0, 1, "E") is True
    assert g.has_road_on_side(0, 1, "E")
    assert g.has_road_on_side(1, 1, "W") is False
    assert ensure_shared_road(g, 0, 1, 1, 1) is True
    assert g.has_road_on_side(1, 1, "W") is True


def test_same_cell_path_and_connectivity():
    g = _empty_grid(3)
    assert shortest_path(g, (1, 1), (1, 1)) == [(1, 1)]
    assert plots_road_connected(g, (1, 1), (1, 1))
    assert connect_points(g, (1, 1), (1, 1)) == [(1, 1)]


def test_adjacent_cells_lay_one_edge():
    g = _empty_grid(3)
    path = connect_points(g, (0, 0), (1, 0))
    assert path == [(0, 0), (1, 0)]
    assert plots_road_connected(g, (0, 0), (1, 0))
    # Exact sides — not a "road tile", just the shared E/W edge
    assert g.get(0, 0).plot.roads == {"N": False, "E": True, "S": False, "W": False}
    assert g.get(1, 0).plot.roads == {"N": False, "E": False, "S": False, "W": True}


def test_straight_horizontal_marks_only_crossing_sides():
    """Horizontal corridor sets E/W on path plots — never N/S flanks."""
    g = _empty_grid(6)
    path = connect_points(g, (0, 2), (5, 2))
    assert path is not None
    assert path[0] == (0, 2) and path[-1] == (5, 2)
    assert len(path) == 6
    assert plots_road_connected(g, (0, 2), (5, 2))
    for i, (x, y) in enumerate(path):
        r = g.get(x, y).plot.roads
        assert r["N"] is False and r["S"] is False
        if i == 0:
            assert r["E"] is True and r["W"] is False
        elif i == len(path) - 1:
            assert r["W"] is True and r["E"] is False
        else:
            assert r["E"] is True and r["W"] is True  # through + double-sided


def test_straight_vertical_marks_only_crossing_sides():
    g = _empty_grid(6)
    path = connect_points(g, (3, 0), (3, 5))
    assert path is not None and len(path) == 6
    assert plots_road_connected(g, (3, 0), (3, 5))
    for i, (x, y) in enumerate(path):
        r = g.get(x, y).plot.roads
        assert r["E"] is False and r["W"] is False
        if i == 0:
            assert r["S"] is True and r["N"] is False
        elif i == len(path) - 1:
            assert r["N"] is True and r["S"] is False
        else:
            assert r["N"] is True and r["S"] is True


def test_straight_horizontal_and_vertical():
    g = _empty_grid(6)
    path = connect_points(g, (0, 2), (5, 2))
    assert path is not None
    assert path[0] == (0, 2) and path[-1] == (5, 2)
    assert plots_road_connected(g, (0, 2), (5, 2))
    # All y==2 for a pure horizontal preference (cost-equal; any shortest ok)
    assert len(path) == 6

    g2 = _empty_grid(6)
    path2 = connect_points(g2, (3, 0), (3, 5))
    assert path2 is not None and len(path2) == 6
    assert plots_road_connected(g2, (3, 0), (3, 5))


def test_l_shaped_path():
    g = _empty_grid(5)
    path = connect_points(g, (0, 0), (4, 3))
    assert path is not None
    assert manhattan(path[0], path[-1]) <= len(path) - 1
    assert len(path) - 1 == manhattan((0, 0), (4, 3))
    assert plots_road_connected(g, (0, 0), (4, 3))


def test_prefers_existing_roads_over_new_parallel():
    g = _empty_grid(5)
    # Pre-build a long east-west corridor on y=0
    connect_points(g, (0, 0), (4, 0))
    path = connect_points(g, (0, 1), (4, 1))
    assert path is not None
    assert plots_road_connected(g, (0, 1), (4, 1))
    # Optimal cost: drop to y=0 (1) + ride corridor (0) + climb (1) = 2 new edges
    # Direct along y=1 costs 4. Path must therefore visit y=0.
    assert any(y == 0 for _, y in path)


def test_combined_edge_blocks_new_road():
    g = _empty_grid(3)
    a = g.get(0, 0).plot
    b = g.get(1, 0).plot
    assert a and b
    a.combined["E"] = b.id
    b.combined["W"] = a.id
    assert edge_step_cost(g, 0, 0, 1, 0) is None
    assert ensure_shared_road(g, 0, 0, 1, 0) is False
    # Path must go around
    path = connect_points(g, (0, 0), (1, 0))
    assert path is not None
    assert len(path) > 2
    assert plots_road_connected(g, (0, 0), (1, 0))


def test_mst_single_and_duplicate_points():
    assert mst_edges([]) == []
    assert mst_edges([(1, 1)]) == []
    assert mst_edges([(1, 1), (1, 1)]) == []
    edges = mst_edges([(0, 0), (2, 0), (0, 2)])
    assert len(edges) == 2


def test_mst_connects_all_halls():
    g = _empty_grid(12)
    halls = [(1, 1), (10, 1), (1, 10), (10, 10)]
    connect_points_mst(g, halls)
    # All halls in one connected component
    comp = connected_component(g, halls[0])
    for h in halls:
        assert h in comp
        assert plots_road_connected(g, halls[0], h)


def test_star_connects_spokes_to_hub_reusing_roads():
    g = _empty_grid(8)
    hub = (4, 4)
    spokes = [(4, 1), (1, 4), (7, 4), (4, 7)]
    connect_star(g, hub, spokes)
    for s in spokes:
        assert plots_road_connected(g, hub, s)
    # Shared hub means spokes may reach each other via hub
    assert plots_road_connected(g, spokes[0], spokes[1])


def test_tiny_2x2_map_connect():
    g = _empty_grid(2)
    path = connect_points(g, (0, 0), (1, 1))
    assert path is not None
    assert plots_road_connected(g, (0, 0), (1, 1))


def test_lay_roads_along_empty_or_singleton_path():
    g = _empty_grid(3)
    assert lay_roads_along_path(g, []) == 0
    assert lay_roads_along_path(g, [(1, 1)]) == 0


def test_unreachable_when_isolated_by_combines_ring():
    """If every edge out of start is combined both ways, path fails."""
    g = _empty_grid(3)
    # Block all four exits from (1,1)
    for side, (dx, dy) in [("N", (0, -1)), ("E", (1, 0)), ("S", (0, 1)), ("W", (-1, 0))]:
        a = g.get(1, 1).plot
        b = g.get(1 + dx, 1 + dy).plot
        assert a and b
        a.combined[side] = b.id
        b.combined[OPPOSITE[side]] = a.id
    assert shortest_path(g, (1, 1), (0, 0)) is None
    assert connect_points(g, (1, 1), (0, 0)) is None


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
    )
    cfg.update(kwargs)
    return World.new_game(WorldConfig(**cfg))


def test_startup_roads_small_cos_to_hall_and_halls_together():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=20, starting_cities=3, small_companies_per_city=3)
        from company_sim.small_companies import city_hall_coord

        halls = []
        for city in w.grid.cities.values():
            h = city_hall_coord(w, city.id)
            assert h is not None
            halls.append(h)

        # Halls interconnected
        assert plots_road_connected(w.grid, halls[0], halls[1])
        assert plots_road_connected(w.grid, halls[0], halls[2])

        smalls = [c for c in w.companies.values() if c.is_small]
        assert len(smalls) == 9  # 3 cities × 3
        for co in smalls:
            owned = w.owned_plots("company", co.id)
            assert len(owned) == 1
            site = (owned[0].x, owned[0].y)
            hall = city_hall_coord(w, co.home_city_id)  # type: ignore[arg-type]
            assert hall is not None
            assert plots_road_connected(w.grid, site, hall)


def test_side_between_consistency_with_road_lay():
    g = _empty_grid(4)
    connect_points(g, (0, 1), (3, 1))
    for x in range(3):
        side = side_between(x, 1, x + 1, 1)
        assert side == "E"
        assert g.shared_edge_has_road(x, 1, x + 1, 1)
