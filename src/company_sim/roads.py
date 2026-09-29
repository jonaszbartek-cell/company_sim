"""Road pathfinding on plot **edges** (street graph), not tile centers.

Roads are plot-side flags only: each plot has ``roads = {N,E,S,W}`` booleans.
Graphics use the per-plot bitmask (N=1 E=2 S=4 W=8) so asphalt sits on those
sides. A shared boundary may be marked on one or both adjacent plots
(double-sided is allowed).

Street model
------------
Each roaded side is a **grid edge** (a segment of the lattice between cells):

* Plot ``(x,y).N`` / ``(x,y-1).S`` → horizontal edge ``('H', x, y)``
* Plot ``(x,y).W`` / ``(x-1,y).E`` → vertical edge ``('V', x, y)``

Two grid edges are adjacent when they share a vertex (colinear street
continuation or a corner turn). Buildings access the network through any of
their four incident edges. Pathfinding routes along this street graph and lays
roads on the chosen edges so every small company can reach City Hall.

Startup order (see ``small_companies.wire_startup_roads``):
  1. City Hall plot gets roads on all four sides (double-sided stubs)
  2. Edge-street paths from each hall → its small companies
  3. Edge-street paths linking halls (Manhattan MST)
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import TYPE_CHECKING, Literal

from company_sim.plots import OPPOSITE, SIDE_DELTA, SIDES, side_between

if TYPE_CHECKING:
    from company_sim.map_grid import GridMap

Coord = tuple[int, int]
# ('H', x, y) = horizontal lattice edge north of cell row y (south of y-1), col x
# ('V', x, y) = vertical lattice edge west of cell col x (east of x-1), row y
GridEdge = tuple[Literal["H", "V"], int, int]


def ensure_edge_road(grid: GridMap, x: int, y: int, side: str) -> bool:
    """Idempotently set a road on one plot side. Returns True if that side has a road."""
    side = side.upper()
    if side not in SIDES:
        return False
    if not grid.in_bounds(x, y):
        return False
    tile = grid.get(x, y)
    if not tile.plot:
        return False
    if tile.plot.combined.get(side):
        return False
    if tile.plot.roads.get(side):
        return True
    tile.plot.roads[side] = True
    return True


def ensure_shared_road(grid: GridMap, x1: int, y1: int, x2: int, y2: int) -> bool:
    """Mark the shared boundary on both plots when possible (double-sided OK)."""
    side = side_between(x1, y1, x2, y2)
    if side is None:
        return False
    a_ok = ensure_edge_road(grid, x1, y1, side)
    b_ok = ensure_edge_road(grid, x2, y2, OPPOSITE[side])
    return a_ok or b_ok or grid.shared_edge_has_road(x1, y1, x2, y2)


def seed_all_side_roads(
    grid: GridMap, x: int, y: int, *, double_sided: bool = True
) -> bool:
    """Put a road on every side (N/E/S/W) of this plot (City Hall at start).

    When ``double_sided`` is True (default), also mark the matching opposite
    side on each neighboring plot so the shared edge is roaded from both tiles.
    """
    if not grid.in_bounds(x, y) or grid.get(x, y).plot is None:
        return False
    ok = True
    for side in SIDES:
        if not ensure_edge_road(grid, x, y, side):
            ok = False
            continue
        if not double_sided:
            continue
        dx, dy = SIDE_DELTA[side]
        nx, ny = x + dx, y + dy
        ensure_edge_road(grid, nx, ny, OPPOSITE[side])
    return ok


def active_road_sides(grid: GridMap, x: int, y: int) -> list[str]:
    tile = grid.get(x, y)
    if not tile.plot:
        return []
    return [s for s in SIDES if tile.plot.roads.get(s)]


# ---------------------------------------------------------------------------
# Grid-edge street graph
# ---------------------------------------------------------------------------


def plot_side_to_edge(x: int, y: int, side: str) -> GridEdge:
    side = side.upper()
    if side == "N":
        return ("H", x, y)
    if side == "S":
        return ("H", x, y + 1)
    if side == "W":
        return ("V", x, y)
    if side == "E":
        return ("V", x + 1, y)
    raise ValueError(f"Invalid side {side}")


def plot_incident_edges(x: int, y: int) -> list[tuple[str, GridEdge]]:
    """(side, grid-edge) for each of the four borders of plot (x,y)."""
    return [(s, plot_side_to_edge(x, y, s)) for s in SIDES]


def edge_touching_plots(edge: GridEdge) -> list[tuple[int, int, str]]:
    """Plots that can mark this grid edge, as (x, y, side)."""
    kind, a, b = edge
    out: list[tuple[int, int, str]] = []
    if kind == "H":
        # ('H', x, y): north of (x,y) and south of (x, y-1)
        x, y = a, b
        out.append((x, y, "N"))
        out.append((x, y - 1, "S"))
    else:
        # ('V', x, y): west of (x,y) and east of (x-1, y)
        x, y = a, b
        out.append((x, y, "W"))
        out.append((x - 1, y, "E"))
    return out


def grid_edge_has_road(grid: GridMap, edge: GridEdge) -> bool:
    for x, y, side in edge_touching_plots(edge):
        if grid.in_bounds(x, y) and grid.has_road_on_side(x, y, side):
            return True
    return False


def grid_edge_can_build(grid: GridMap, edge: GridEdge) -> bool:
    """True if at least one touching plot can accept a road on that side."""
    if grid_edge_has_road(grid, edge):
        return True
    for x, y, side in edge_touching_plots(edge):
        if not grid.in_bounds(x, y):
            continue
        tile = grid.get(x, y)
        if not tile.plot:
            continue
        if tile.plot.combined.get(side):
            continue
        return True
    return False


def mark_grid_edge(grid: GridMap, edge: GridEdge, *, double_sided: bool = True) -> bool:
    """Lay asphalt on a lattice edge (one or both touching plot sides)."""
    marked = False
    touches = edge_touching_plots(edge)
    if double_sided:
        for x, y, side in touches:
            if ensure_edge_road(grid, x, y, side):
                marked = True
    else:
        # Prefer an in-bounds plot that can take the road
        for x, y, side in touches:
            if ensure_edge_road(grid, x, y, side):
                marked = True
                break
    return marked or grid_edge_has_road(grid, edge)


def grid_edge_neighbors(edge: GridEdge) -> list[GridEdge]:
    """Lattice edges that share a vertex with ``edge`` (street continuation / turn)."""
    kind, a, b = edge
    out: list[GridEdge] = []
    if kind == "H":
        x, y = a, b
        # Colinear east/west along the same horizontal street
        out.append(("H", x - 1, y))
        out.append(("H", x + 1, y))
        # Corner turns onto vertical streets at both endpoints
        out.append(("V", x, y - 1))
        out.append(("V", x, y))
        out.append(("V", x + 1, y - 1))
        out.append(("V", x + 1, y))
    else:
        x, y = a, b
        out.append(("V", x, y - 1))
        out.append(("V", x, y + 1))
        out.append(("H", x - 1, y))
        out.append(("H", x, y))
        out.append(("H", x - 1, y + 1))
        out.append(("H", x, y + 1))
    return out


def _edge_in_map(grid: GridMap, edge: GridEdge) -> bool:
    """True if the edge touches at least one in-bounds plot cell."""
    for x, y, _side in edge_touching_plots(edge):
        if grid.in_bounds(x, y) and grid.get(x, y).plot is not None:
            return True
    return False


def edge_step_cost(grid: GridMap, x1: int, y1: int, x2: int, y2: int) -> float | None:
    """Cost to cross the shared side between adjacent plots (0 if already roaded)."""
    side = side_between(x1, y1, x2, y2)
    if side is None:
        return None
    if not grid.in_bounds(x1, y1) or not grid.in_bounds(x2, y2):
        return None
    a = grid.get(x1, y1).plot
    b = grid.get(x2, y2).plot
    if not a or not b:
        return None
    if grid.shared_edge_has_road(x1, y1, x2, y2):
        return 0.0
    a_free = not a.combined.get(side)
    b_free = not b.combined.get(OPPOSITE[side])
    if not a_free and not b_free:
        return None
    return 1.0


def neighbors4(grid: GridMap, x: int, y: int) -> list[Coord]:
    out: list[Coord] = []
    for dx, dy in SIDE_DELTA.values():
        nx, ny = x + dx, y + dy
        if grid.in_bounds(nx, ny) and grid.get(nx, ny).plot is not None:
            out.append((nx, ny))
    return out


def street_edge_cost(grid: GridMap, edge: GridEdge) -> float | None:
    """0 if roaded, 1 if buildable, None if blocked / off-map."""
    if not _edge_in_map(grid, edge):
        return None
    if grid_edge_has_road(grid, edge):
        return 0.0
    if grid_edge_can_build(grid, edge):
        return 1.0
    return None


def shortest_street_path(
    grid: GridMap,
    start: Coord,
    goal: Coord,
) -> list[GridEdge] | None:
    """Lowest-cost path along the street (grid-edge) graph between two plots.

    Returns the list of lattice edges to road (may already be roaded). Empty
    list means start==goal (same plot already has access to itself).
    """
    if start == goal:
        return []
    if not grid.in_bounds(*start) or not grid.in_bounds(*goal):
        return None
    if grid.get(*start).plot is None or grid.get(*goal).plot is None:
        return None

    goal_edges = {e for _, e in plot_incident_edges(*goal)}
    # Multi-source Dijkstra from all four sides of start
    pq: list[tuple[float, int, GridEdge]] = []
    best: dict[GridEdge, float] = {}
    prev: dict[GridEdge, GridEdge | None] = {}
    seq = 0
    for _side, edge in plot_incident_edges(*start):
        cost = street_edge_cost(grid, edge)
        if cost is None:
            continue
        best[edge] = cost
        prev[edge] = None
        heapq.heappush(pq, (cost, seq, edge))
        seq += 1

    found: GridEdge | None = None
    found_cost = float("inf")
    while pq:
        cost, _, edge = heapq.heappop(pq)
        if cost > best.get(edge, float("inf")):
            continue
        if edge in goal_edges and cost < found_cost:
            found = edge
            found_cost = cost
            # Still search: a cheaper goal edge may appear, but with
            # non-negative weights we can stop when we first pop a goal edge.
            break
        for nxt in grid_edge_neighbors(edge):
            step = street_edge_cost(grid, nxt)
            if step is None:
                continue
            ncost = cost + step
            if ncost < best.get(nxt, float("inf")):
                best[nxt] = ncost
                prev[nxt] = edge
                heapq.heappush(pq, (ncost, seq, nxt))
                seq += 1

    if found is None:
        return None

    path: list[GridEdge] = []
    cur: GridEdge | None = found
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    return path


def lay_roads_along_edges(grid: GridMap, edges: list[GridEdge]) -> int:
    """Mark each lattice edge (double-sided when possible). Returns newly laid count."""
    laid = 0
    for edge in edges:
        before = grid_edge_has_road(grid, edge)
        if mark_grid_edge(grid, edge, double_sided=True) and not before:
            laid += 1
    return laid


def lay_roads_along_path(grid: GridMap, path: list[Coord]) -> int:
    """Legacy helper: for each plot-step, mark the shared side (both plots)."""
    if len(path) < 2:
        return 0
    laid = 0
    for (x1, y1), (x2, y2) in zip(path, path[1:]):
        before = grid.shared_edge_has_road(x1, y1, x2, y2)
        if ensure_shared_road(grid, x1, y1, x2, y2) and not before:
            laid += 1
    return laid


def shortest_path(
    grid: GridMap,
    start: Coord,
    goal: Coord,
) -> list[Coord] | None:
    """Plot cells touched by the street path from start to goal (for tests/UI)."""
    if start == goal:
        return [start]
    edges = shortest_street_path(grid, start, goal)
    if edges is None:
        return None
    # Reconstruct an ordered list of plots that touch the street path, starting
    # at ``start`` and ending at ``goal``.
    plots: list[Coord] = [start]
    seen = {start}
    for edge in edges:
        for x, y, _side in edge_touching_plots(edge):
            if not grid.in_bounds(x, y) or grid.get(x, y).plot is None:
                continue
            if (x, y) not in seen:
                seen.add((x, y))
                plots.append((x, y))
    if goal not in seen:
        plots.append(goal)
    elif plots[-1] != goal:
        # Move goal to the end for a clean start→goal listing
        plots = [p for p in plots if p != goal] + [goal]
    return plots


def connect_points(grid: GridMap, start: Coord, goal: Coord) -> list[Coord] | None:
    """Pathfind on the street graph then lay edge roads so start↔goal connect."""
    if start == goal:
        return [start]
    edges = shortest_street_path(grid, start, goal)
    if edges is None:
        return None
    lay_roads_along_edges(grid, edges)
    return shortest_path(grid, start, goal) or [start, goal]


def plots_road_connected(grid: GridMap, start: Coord, goal: Coord) -> bool:
    """True if start and goal share a connected street (edge) network."""
    if start == goal:
        return True
    if not grid.in_bounds(*start) or not grid.in_bounds(*goal):
        return False
    if grid.get(*start).plot is None or grid.get(*goal).plot is None:
        return False

    start_edges = [
        e
        for _, e in plot_incident_edges(*start)
        if grid_edge_has_road(grid, e)
    ]
    if not start_edges:
        return False
    goal_edges = {
        e for _, e in plot_incident_edges(*goal) if grid_edge_has_road(grid, e)
    }
    if not goal_edges:
        return False

    seen: set[GridEdge] = set()
    q: deque[GridEdge] = deque()
    for e in start_edges:
        seen.add(e)
        q.append(e)
    while q:
        edge = q.popleft()
        if edge in goal_edges:
            return True
        for nxt in grid_edge_neighbors(edge):
            if nxt in seen:
                continue
            if not grid_edge_has_road(grid, nxt):
                continue
            seen.add(nxt)
            q.append(nxt)
    return False


def connected_component(grid: GridMap, start: Coord) -> set[Coord]:
    """All plots that have road access on the same street network as ``start``."""
    if not grid.in_bounds(*start) or grid.get(*start).plot is None:
        return set()
    start_edges = [
        e for _, e in plot_incident_edges(*start) if grid_edge_has_road(grid, e)
    ]
    if not start_edges:
        return {start}

    seen_edges: set[GridEdge] = set()
    q: deque[GridEdge] = deque()
    for e in start_edges:
        seen_edges.add(e)
        q.append(e)
    while q:
        edge = q.popleft()
        for nxt in grid_edge_neighbors(edge):
            if nxt in seen_edges:
                continue
            if not grid_edge_has_road(grid, nxt):
                continue
            seen_edges.add(nxt)
            q.append(nxt)

    plots: set[Coord] = set()
    for edge in seen_edges:
        for x, y, _side in edge_touching_plots(edge):
            if grid.in_bounds(x, y) and grid.get(x, y).plot is not None:
                plots.add((x, y))
    plots.add(start)
    return plots


def manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def mst_edges(points: list[Coord]) -> list[tuple[Coord, Coord]]:
    if len(points) < 2:
        return []
    uniq: list[Coord] = []
    seen: set[Coord] = set()
    for p in points:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    if len(uniq) < 2:
        return []

    in_tree = {uniq[0]}
    edges: list[tuple[Coord, Coord]] = []
    while len(in_tree) < len(uniq):
        best: tuple[int, Coord, Coord] | None = None
        for a in in_tree:
            for b in uniq:
                if b in in_tree:
                    continue
                d = manhattan(a, b)
                if best is None or d < best[0]:
                    best = (d, a, b)
        assert best is not None
        _, a, b = best
        edges.append((a, b))
        in_tree.add(b)
    return edges


def connect_points_mst(grid: GridMap, points: list[Coord]) -> list[list[Coord]]:
    paths: list[list[Coord]] = []
    for a, b in mst_edges(points):
        path = connect_points(grid, a, b)
        if path is not None:
            paths.append(path)
    return paths


def connect_star(grid: GridMap, hub: Coord, spokes: list[Coord]) -> list[list[Coord]]:
    paths: list[list[Coord]] = []
    for spoke in spokes:
        if spoke == hub:
            continue
        path = connect_points(grid, spoke, hub)
        if path is not None:
            paths.append(path)
    return paths


__all__ = [
    "ensure_edge_road",
    "ensure_shared_road",
    "seed_all_side_roads",
    "active_road_sides",
    "edge_step_cost",
    "neighbors4",
    "plot_side_to_edge",
    "plot_incident_edges",
    "grid_edge_has_road",
    "mark_grid_edge",
    "shortest_street_path",
    "lay_roads_along_edges",
    "shortest_path",
    "lay_roads_along_path",
    "connect_points",
    "plots_road_connected",
    "connected_component",
    "manhattan",
    "mst_edges",
    "connect_points_mst",
    "connect_star",
]
