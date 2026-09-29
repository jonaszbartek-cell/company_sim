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
    assert path is not None
    assert path[0] == (0, 0) and path[-1] == (1, 0)
    assert plots_road_connected(g, (0, 0), (1, 0))
    # Adjacent plots share one lattice edge — roaded on that shared side
    assert g.shared_edge_has_road(0, 0, 1, 0)


def test_straight_horizontal_lays_continuous_edge_street():
    """Horizontal connection lays a continuous street on plot edges (not tile centers)."""
    from company_sim.roads import grid_edge_has_road, plot_side_to_edge

    g = _empty_grid(6)
    path = connect_points(g, (0, 2), (5, 2))
    assert path is not None
    assert path[0] == (0, 2) and path[-1] == (5, 2)
    assert plots_road_connected(g, (0, 2), (5, 2))
    # Continuous horizontal street along the row: every column has the N (or S) edge roaded
    n_street = all(grid_edge_has_road(g, plot_side_to_edge(x, 2, "N")) for x in range(6))
    s_street = all(grid_edge_has_road(g, plot_side_to_edge(x, 2, "S")) for x in range(6))
    ew_crossings = all(g.shared_edge_has_road(x, 2, x + 1, 2) for x in range(5))
    assert n_street or s_street or ew_crossings
    # Asphalt is on edges — at least one side flag set on endpoints
    from company_sim.roads import active_road_sides

    assert active_road_sides(g, 0, 2)
    assert active_road_sides(g, 5, 2)


def test_straight_vertical_lays_continuous_edge_street():
    from company_sim.roads import grid_edge_has_road, plot_side_to_edge

    g = _empty_grid(6)
    path = connect_points(g, (3, 0), (3, 5))
    assert path is not None
    assert path[0] == (3, 0) and path[-1] == (3, 5)
    assert plots_road_connected(g, (3, 0), (3, 5))
    w_street = all(grid_edge_has_road(g, plot_side_to_edge(3, y, "W")) for y in range(6))
    e_street = all(grid_edge_has_road(g, plot_side_to_edge(3, y, "E")) for y in range(6))
    ns_crossings = all(g.shared_edge_has_road(3, y, 3, y + 1) for y in range(5))
    assert w_street or e_street or ns_crossings


def test_straight_horizontal_and_vertical():
    g = _empty_grid(6)
    path = connect_points(g, (0, 2), (5, 2))
    assert path is not None
    assert path[0] == (0, 2) and path[-1] == (5, 2)
    assert plots_road_connected(g, (0, 2), (5, 2))

    g2 = _empty_grid(6)
    path2 = connect_points(g2, (3, 0), (3, 5))
    assert path2 is not None
    assert path2[0] == (3, 0) and path2[-1] == (3, 5)
    assert plots_road_connected(g2, (3, 0), (3, 5))


def test_l_shaped_path():
    g = _empty_grid(5)
    path = connect_points(g, (0, 0), (4, 3))
    assert path is not None
    assert path[0] == (0, 0) and path[-1] == (4, 3)
    assert plots_road_connected(g, (0, 0), (4, 3))
    # Street path length in edges is at least Manhattan (one edge per step)
    from company_sim.roads import shortest_street_path

    edges = shortest_street_path(g, (0, 0), (4, 3))
    assert edges is not None
    assert len(edges) >= manhattan((0, 0), (4, 3))


def test_prefers_existing_roads_over_new_parallel():
    g = _empty_grid(5)
    # Pre-build a long east-west street on y=0
    connect_points(g, (0, 0), (4, 0))
    assert plots_road_connected(g, (0, 0), (4, 0))
    # Second connection on y=1 should reuse the existing street (via short stubs)
    path = connect_points(g, (0, 1), (4, 1))
    assert path is not None
    assert plots_road_connected(g, (0, 1), (4, 1))
    # Both rows end up on the same connected street component
    assert plots_road_connected(g, (0, 0), (4, 1))


def test_combined_edge_blocks_shared_crossing_but_street_can_flank():
    """Combined shared side cannot be roaded; pathfinding flanks via other edges."""
    g = _empty_grid(3)
    a = g.get(0, 0).plot
    b = g.get(1, 0).plot
    assert a and b
    a.combined["E"] = b.id
    b.combined["W"] = a.id
    assert edge_step_cost(g, 0, 0, 1, 0) is None
    assert ensure_shared_road(g, 0, 0, 1, 0) is False
    # Still connect via a flank street (N or S), without roading the combined side
    path = connect_points(g, (0, 0), (1, 0))
    assert path is not None
    assert plots_road_connected(g, (0, 0), (1, 0))
    assert g.has_road_on_side(0, 0, "E") is False
    assert g.has_road_on_side(1, 0, "W") is False


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


def test_city_hall_starts_with_all_four_side_roads():
    """City Hall plot always has N/E/S/W roads before/after network wiring."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=14, starting_cities=2, small_companies_per_city=2)
        from company_sim.roads import active_road_sides
        from company_sim.small_companies import city_hall_coord

        for city in w.grid.cities.values():
            h = city_hall_coord(w, city.id)
            assert h is not None
            sides = active_road_sides(w.grid, *h)
            assert sides == ["N", "E", "S", "W"], sides
            assert w.grid.road_mask_at(*h) == 15  # N|E|S|W


def test_startup_roads_small_cos_to_hall_and_halls_together():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=20, starting_cities=3, small_companies_per_city=3)
        from company_sim.roads import active_road_sides
        from company_sim.small_companies import city_hall_coord

        halls = []
        for city in w.grid.cities.values():
            h = city_hall_coord(w, city.id)
            assert h is not None
            assert active_road_sides(w.grid, *h) == ["N", "E", "S", "W"]
            halls.append(h)

        # Halls interconnected via side-roads
        assert plots_road_connected(w.grid, halls[0], halls[1])
        assert plots_road_connected(w.grid, halls[0], halls[2])

        smalls = [c for c in w.companies.values() if c.is_small]
        assert len(smalls) == 9  # 3 cities × 3
        for co in smalls:
            tiles = [
                t
                for t in w.owned_plots("company", co.id)
                if t.plot and t.plot.building
            ]
            assert len(tiles) == 1
            site = (tiles[0].x, tiles[0].y)
            hall = city_hall_coord(w, co.home_city_id)  # type: ignore[arg-type]
            assert hall is not None
            assert plots_road_connected(w.grid, site, hall)
            # Company building plot has at least one side road toward the network
            assert active_road_sides(w.grid, *site)


def test_seed_all_side_roads_helper():
    from company_sim.roads import active_road_sides, seed_all_side_roads
    from company_sim.plots import OPPOSITE, SIDE_DELTA

    g = _empty_grid(4)
    assert seed_all_side_roads(g, 2, 2) is True
    assert active_road_sides(g, 2, 2) == ["N", "E", "S", "W"]
    assert g.road_mask_at(2, 2) == 15
    # Double-sided stubs on the four neighbors
    for side, (dx, dy) in SIDE_DELTA.items():
        nx, ny = 2 + dx, 2 + dy
        assert g.has_road_on_side(nx, ny, OPPOSITE[side])
        assert g.shared_edge_has_road(2, 2, nx, ny)


def test_city_hall_neighbor_stubs_are_double_sided():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=12, starting_cities=1, small_companies_per_city=0)
        from company_sim.plots import OPPOSITE, SIDE_DELTA
        from company_sim.small_companies import city_hall_coord

        h = city_hall_coord(w, "city_a")
        assert h is not None
        hx, hy = h
        assert w.grid.road_mask_at(hx, hy) == 15
        for side, (dx, dy) in SIDE_DELTA.items():
            nx, ny = hx + dx, hy + dy
            assert w.grid.has_road_on_side(nx, ny, OPPOSITE[side]), (side, nx, ny)



def test_side_between_consistency_with_road_lay():
    """Connecting along a row lays a continuous edge street between the plots."""
    from company_sim.roads import grid_edge_has_road, plot_side_to_edge

    g = _empty_grid(4)
    connect_points(g, (0, 1), (3, 1))
    assert plots_road_connected(g, (0, 1), (3, 1))
    # Either the shared E/W crossings OR a continuous N/S flank street
    ew = all(g.shared_edge_has_road(x, 1, x + 1, 1) for x in range(3))
    n_street = all(grid_edge_has_road(g, plot_side_to_edge(x, 1, "N")) for x in range(4))
    s_street = all(grid_edge_has_road(g, plot_side_to_edge(x, 1, "S")) for x in range(4))
    assert ew or n_street or s_street
    for x in range(3):
        assert side_between(x, 1, x + 1, 1) == "E"


def test_startup_roads_connect_building_edges_to_hall():
    """Every small-company **building** reaches its City Hall via the edge-street network."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=18, starting_cities=3, small_companies_per_city=4)
        from company_sim.roads import active_road_sides
        from company_sim.small_companies import city_hall_coord

        smalls = [c for c in w.companies.values() if c.is_small]
        assert len(smalls) == 12
        for co in smalls:
            # Use the building tile (not merely any owned plot)
            tiles = [
                t
                for t in w.owned_plots("company", co.id)
                if t.plot and t.plot.building
            ]
            assert len(tiles) == 1
            site = (tiles[0].x, tiles[0].y)
            hall = city_hall_coord(w, co.home_city_id)  # type: ignore[arg-type]
            assert hall is not None
            assert plots_road_connected(w.grid, site, hall), (co.id, site, hall)
            # Building sits on a plot that has at least one roaded edge
            sides = active_road_sides(w.grid, *site)
            assert sides, (co.id, site)


def test_player_build_road_still_one_sided():
    """Manual build_road marks only the owned plot's chosen side (neighbor unchanged)."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=10, starting_cities=1, small_companies_per_city=0)
        player = w.companies["player"]
        px, py = 1, 1
        tile = w.grid.get(px, py)
        assert tile.plot is not None
        tile.plot.claim("company", player.id)
        for s in ("N", "E", "S", "W"):
            tile.plot.roads[s] = False
        east = w.grid.get(px + 1, py)
        assert east.plot is not None
        east.plot.roads["W"] = False

        player.inventory.add("steel", 5)
        r = w.company_build_road(player.id, px, py, "E")
        assert r.ok
        assert w.grid.has_road_on_side(px, py, "E")
        # Neighbor's W stays False — player builds are one-sided
        assert w.grid.has_road_on_side(px + 1, py, "W") is False
