"""Road pathfinding and free engine placement.

Roads are never tiles. Each plot has four optional edge flags (N/E/S/W).
Building a road means setting ``plot.roads[side] = True`` on that plot only
(player builds) — or, for engine startup wiring, optionally marking *both*
plots' sides of the shared edge (double-sided). Double-sided is allowed and
intentional: either side alone is enough for ``shared_edge_has_road``.

Startup wiring uses Dijkstra over adjacent plots:
  - cost 0 to step across an edge that already has a road (either side)
  - cost 1 to step across a free edge (will lay a new side road)
  - impassable when the edge is blocked by plot combines on both sides
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import TYPE_CHECKING

from company_sim.plots import OPPOSITE, SIDE_DELTA, SIDES, side_between

if TYPE_CHECKING:
    from company_sim.map_grid import GridMap

Coord = tuple[int, int]


def ensure_edge_road(grid: GridMap, x: int, y: int, side: str) -> bool:
    """Idempotently set a road on one plot side. Returns True if the side has a road.

    Fails (False) when out of bounds, missing plot, or the side is combined.
    """
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
    """Ensure the shared *side* between two adjacent plots has a road.

    Marks the edge on both plots when possible (double-sided — allowed).
    Connectivity only needs one side; see ``GridMap.shared_edge_has_road``.
    """
    side = side_between(x1, y1, x2, y2)
    if side is None:
        return False
    if grid.shared_edge_has_road(x1, y1, x2, y2):
        # Still try to fill the missing opposite side (double-sided is fine)
        ensure_edge_road(grid, x1, y1, side)
        ensure_edge_road(grid, x2, y2, OPPOSITE[side])
        return True
    a_ok = ensure_edge_road(grid, x1, y1, side)
    b_ok = ensure_edge_road(grid, x2, y2, OPPOSITE[side])
    return a_ok or b_ok or grid.shared_edge_has_road(x1, y1, x2, y2)


def edge_step_cost(grid: GridMap, x1: int, y1: int, x2: int, y2: int) -> float | None:
    """Traversal cost between adjacent cells, or None if impassable for roads."""
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
    # Can we lay a road on at least one side of this edge?
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


def shortest_path(
    grid: GridMap,
    start: Coord,
    goal: Coord,
) -> list[Coord] | None:
    """Lowest-cost path from start to goal (prefer existing roads).

    Returns the coordinate list including both endpoints, or None if unreachable.
    Same-cell start==goal returns [start].
    """
    if start == goal:
        return [start]
    if not grid.in_bounds(*start) or not grid.in_bounds(*goal):
        return None
    if grid.get(*start).plot is None or grid.get(*goal).plot is None:
        return None

    # Dijkstra: (cost, steps, x, y)
    pq: list[tuple[float, int, int, int]] = [(0.0, 0, start[0], start[1])]
    best: dict[Coord, float] = {start: 0.0}
    prev: dict[Coord, Coord | None] = {start: None}

    while pq:
        cost, steps, x, y = heapq.heappop(pq)
        if (x, y) == goal:
            break
        if cost > best.get((x, y), float("inf")):
            continue
        for nx, ny in neighbors4(grid, x, y):
            step = edge_step_cost(grid, x, y, nx, ny)
            if step is None:
                continue
            ncost = cost + step
            key = (nx, ny)
            if ncost < best.get(key, float("inf")):
                best[key] = ncost
                prev[key] = (x, y)
                heapq.heappush(pq, (ncost, steps + 1, nx, ny))

    if goal not in prev and start != goal:
        return None
    if goal not in prev:
        return None

    path: list[Coord] = []
    cur: Coord | None = goal
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    if path[0] != start:
        return None
    return path


def lay_roads_along_path(grid: GridMap, path: list[Coord]) -> int:
    """Lay roads on every consecutive pair in path. Returns number of new edges ensured."""
    if len(path) < 2:
        return 0
    laid = 0
    for (x1, y1), (x2, y2) in zip(path, path[1:]):
        before = grid.shared_edge_has_road(x1, y1, x2, y2)
        if ensure_shared_road(grid, x1, y1, x2, y2) and not before:
            laid += 1
    return laid


def connect_points(grid: GridMap, start: Coord, goal: Coord) -> list[Coord] | None:
    """Find a path and lay roads so start and goal are road-connected."""
    path = shortest_path(grid, start, goal)
    if path is None:
        return None
    lay_roads_along_path(grid, path)
    return path


def plots_road_connected(grid: GridMap, start: Coord, goal: Coord) -> bool:
    """BFS connectivity over existing roads only."""
    if start == goal:
        return True
    if not grid.in_bounds(*start) or not grid.in_bounds(*goal):
        return False
    seen = {start}
    q: deque[Coord] = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in neighbors4(grid, x, y):
            if (nx, ny) in seen:
                continue
            if not grid.shared_edge_has_road(x, y, nx, ny):
                continue
            if (nx, ny) == goal:
                return True
            seen.add((nx, ny))
            q.append((nx, ny))
    return False


def connected_component(grid: GridMap, start: Coord) -> set[Coord]:
    """All plots reachable from start via existing roads."""
    if not grid.in_bounds(*start) or grid.get(*start).plot is None:
        return set()
    seen = {start}
    q: deque[Coord] = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in neighbors4(grid, x, y):
            if (nx, ny) in seen:
                continue
            if not grid.shared_edge_has_road(x, y, nx, ny):
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
    return seen


def manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def mst_edges(points: list[Coord]) -> list[tuple[Coord, Coord]]:
    """Manhattan MST via Prim. Empty / single point → no edges."""
    if len(points) < 2:
        return []
    # Deduplicate while preserving order
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
    """Connect all points into one road network via Manhattan MST + path laying."""
    paths: list[list[Coord]] = []
    for a, b in mst_edges(points):
        path = connect_points(grid, a, b)
        if path is not None:
            paths.append(path)
    return paths


def connect_star(grid: GridMap, hub: Coord, spokes: list[Coord]) -> list[list[Coord]]:
    """Connect each spoke to hub (reuses roads via Dijkstra cost-0 edges)."""
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
    "edge_step_cost",
    "neighbors4",
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
