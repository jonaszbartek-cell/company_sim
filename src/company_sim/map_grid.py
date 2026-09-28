"""Grid of square plots only. Roads are edges on plot sides."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from company_sim.actors import City
from company_sim.items import Inventory
from company_sim.plots import (
    OPPOSITE,
    SIDES,
    Plot,
    PlotType,
    side_between,
)


@dataclass
class Tile:
    x: int
    y: int
    city_id: str | None = None  # administrative territory / starting owner city
    plot: Plot | None = None


@dataclass
class GridMap:
    width: int
    height: int
    tiles: list[Tile] = field(default_factory=list)
    cities: dict[str, City] = field(default_factory=dict)
    _plot_index: dict[str, tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def create(cls, width: int, height: int) -> GridMap:
        tiles = [Tile(x=x, y=y) for y in range(height) for x in range(width)]
        return cls(width=width, height=height, tiles=tiles)

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get(self, x: int, y: int) -> Tile:
        return self.tiles[self.index(x, y)]

    def neighbors4(self, x: int, y: int) -> Iterator[tuple[int, int]]:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                yield nx, ny

    def rebuild_plot_index(self) -> None:
        self._plot_index = {}
        for t in self.tiles:
            if t.plot:
                self._plot_index[t.plot.id] = (t.x, t.y)

    def coords_for_plot_id(self, plot_id: str) -> tuple[int, int] | None:
        return self._plot_index.get(plot_id)

    def find_plot(self, plot_id: str) -> Plot | None:
        coords = self.coords_for_plot_id(plot_id)
        if coords is None:
            return None
        tile = self.get(*coords)
        return tile.plot

    def has_road_on_side(self, x: int, y: int, side: str) -> bool:
        tile = self.get(x, y)
        if not tile.plot:
            return False
        return bool(tile.plot.roads.get(side))

    def shared_edge_has_road(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """True if either plot has a road on the shared edge (roads are plot-local)."""
        side = side_between(x1, y1, x2, y2)
        if side is None:
            return False
        if self.has_road_on_side(x1, y1, side):
            return True
        return self.has_road_on_side(x2, y2, OPPOSITE[side])

    def build_edge_road(self, x: int, y: int, side: str) -> None:
        """Build a road on one side of this plot only — does not affect the neighbor."""
        if side not in SIDES:
            raise ValueError(f"Invalid side: {side}")
        tile = self.get(x, y)
        if not tile.plot:
            raise ValueError("No plot there")
        if tile.plot.combined.get(side):
            raise ValueError("Cannot build a road on a combined side")
        if tile.plot.roads.get(side):
            raise ValueError("Road already exists on that side")
        tile.plot.roads[side] = True

    def combine_plots(self, x1: int, y1: int, x2: int, y2: int, owner_kind: str, owner_id: str) -> None:
        """Flag two adjacent plots as combined across their shared edge. Plots stay."""
        a = self.get(x1, y1)
        b = self.get(x2, y2)
        if not a.plot or not b.plot:
            raise ValueError("Both cells must be plots")
        if not a.plot.owned_by(owner_kind, owner_id) or not b.plot.owned_by(owner_kind, owner_id):
            raise ValueError("You must own both plots")
        side_a = side_between(x1, y1, x2, y2)
        if side_a is None:
            raise ValueError("Plots must be adjacent")
        side_b = OPPOSITE[side_a]
        if a.plot.roads.get(side_a) or b.plot.roads.get(side_b):
            raise ValueError("Cannot combine across a road")
        if a.plot.combined.get(side_a) or b.plot.combined.get(side_b):
            raise ValueError("Already combined on that side")
        if a.plot.reserved_proposal_id or b.plot.reserved_proposal_id:
            raise ValueError("Plot is reserved by a pending proposal")
        a.plot.combined[side_a] = b.plot.id
        b.plot.combined[side_b] = a.plot.id

    def clear_combines_at(self, x: int, y: int) -> None:
        """Break all combine flags involving this plot (e.g. after ownership transfer)."""
        tile = self.get(x, y)
        if not tile.plot:
            return
        for side in list(SIDES):
            other_id = tile.plot.combined.get(side)
            if not other_id:
                continue
            tile.plot.combined[side] = None
            coords = self.coords_for_plot_id(other_id)
            if coords is None:
                continue
            other = self.get(*coords).plot
            if other:
                opp = OPPOSITE[side]
                if other.combined.get(opp) == tile.plot.id:
                    other.combined[opp] = None

    def combined_group(self, x: int, y: int) -> list[tuple[int, int]]:
        """Connected component via combine flags."""
        start = self.get(x, y)
        if not start.plot:
            return []
        seen: set[tuple[int, int]] = set()
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            plot = self.get(cx, cy).plot
            if not plot:
                continue
            for side, other_id in plot.combined.items():
                if not other_id:
                    continue
                coords = self.coords_for_plot_id(other_id)
                if coords and coords not in seen:
                    stack.append(coords)
        return list(seen)

    def group_size(self, x: int, y: int) -> int:
        return max(1, len(self.combined_group(x, y)))

    def production_bonus_at(self, x: int, y: int, per_extra_cell: float = 0.05) -> float:
        size = self.group_size(x, y)
        return 1.0 + per_extra_cell * (size - 1)

    def rebuild_territories(self) -> None:
        for city in self.cities.values():
            city.territory = []
        for tile in self.tiles:
            if tile.city_id and tile.city_id in self.cities:
                self.cities[tile.city_id].territory.append((tile.x, tile.y))

    def to_public_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "cities": [c.to_public_dict() for c in self.cities.values()],
            "tiles": [
                {
                    "x": t.x,
                    "y": t.y,
                    "kind": "plot",
                    "city_id": t.city_id,
                    "plot": None
                    if t.plot is None
                    else t.plot.to_public_dict(
                        group_size=self.group_size(t.x, t.y),
                        production_bonus=round(self.production_bonus_at(t.x, t.y), 3),
                    ),
                }
                for t in self.tiles
            ],
        }


def generate_map(
    size: int,
    city_seeds: list[tuple[str, str, int, int, int]],
) -> GridMap:
    """
    Build an NxN grid of square plots only.

    city_seeds: (id, name, center_x, center_y, population)
    Territory is assigned by nearest city center; ownership is applied by World.
    """
    if size < 2:
        raise ValueError("Map size must be at least 2")
    grid = GridMap.create(size, size)

    for cid, name, x, y, pop in city_seeds:
        if not grid.in_bounds(x, y):
            x = min(max(0, x), size - 1)
            y = min(max(0, y), size - 1)
        grid.cities[cid] = City(
            id=cid,
            name=name,
            cash=3000,
            center_x=x,
            center_y=y,
            population=pop,
            inventory=Inventory(
                {
                    "iron_ore": 20,
                    "coal": 20,
                    "energy": 20,
                    "steel": 0,
                    "construction_materials": 50,
                }
            ),
        )

    # Equal-ish division: assign every cell to nearest city seed
    for tile in grid.tiles:
        tile.city_id = _nearest_city_id(grid, tile.x, tile.y)
        ptype = PlotType.SPECIALIZED if ((tile.x * 17 + tile.y * 31) % 7 == 0) else PlotType.STANDARD
        value = 150 if ptype == PlotType.SPECIALIZED else 100
        tile.plot = Plot(plot_type=ptype, value=value)

    grid.rebuild_plot_index()
    grid.rebuild_territories()
    return grid


def _nearest_city_id(grid: GridMap, x: int, y: int) -> str | None:
    best_id = None
    best_d = 10**9
    for c in grid.cities.values():
        d = abs(x - c.center_x) + abs(y - c.center_y)
        if d < best_d:
            best_d = d
            best_id = c.id
    return best_id


def place_city_seeds(size: int, count: int) -> list[tuple[int, int]]:
    """Spread city centers across the map."""
    if count <= 0:
        return []
    if count == 1:
        return [(size // 2, size // 2)]
    # Place on a rough grid
    cols = int(count**0.5 + 0.999)
    rows = (count + cols - 1) // cols
    points: list[tuple[int, int]] = []
    i = 0
    for r in range(rows):
        for c in range(cols):
            if i >= count:
                break
            x = int((c + 0.5) * size / cols)
            y = int((r + 0.5) * size / rows)
            x = min(max(0, x), size - 1)
            y = min(max(0, y), size - 1)
            points.append((x, y))
            i += 1
    return points


__all__ = [
    "Tile",
    "GridMap",
    "generate_map",
    "place_city_seeds",
    "Plot",
    "PlotType",
    "SIDES",
    "OPPOSITE",
    "side_between",
]
