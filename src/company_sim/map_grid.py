"""Grid map: roads, plots, buildings, parcels; cities are territories (not tiles)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

from company_sim.actors import City
from company_sim.buildings import Building
from company_sim.items import Inventory
from company_sim.plots import Parcel, Plot, PlotType


class TileKind(str, Enum):
    EMPTY = "empty"
    ROAD = "road"
    PLOT = "plot"


@dataclass
class Tile:
    x: int
    y: int
    kind: TileKind = TileKind.EMPTY
    city_id: str | None = None  # which city administers this cell
    plot: Plot | None = None


@dataclass
class GridMap:
    width: int
    height: int
    tiles: list[Tile] = field(default_factory=list)
    cities: dict[str, City] = field(default_factory=dict)
    parcels: dict[str, Parcel] = field(default_factory=dict)

    @classmethod
    def create(cls, width: int, height: int) -> GridMap:
        tiles = [Tile(x=x, y=y) for y in range(height) for x in range(width)]
        return cls(width=width, height=height, tiles=tiles)

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get(self, x: int, y: int) -> Tile:
        if not self.in_bounds(x, y):
            raise IndexError(f"Out of bounds: ({x}, {y})")
        return self.tiles[self.index(x, y)]

    def neighbors4(self, x: int, y: int) -> Iterator[tuple[int, int]]:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                yield nx, ny

    def is_road_access(self, x: int, y: int) -> bool:
        for nx, ny in self.neighbors4(x, y):
            if self.get(nx, ny).kind == TileKind.ROAD:
                return True
        return False

    def set_road(self, x: int, y: int) -> bool:
        tile = self.get(x, y)
        if tile.kind == TileKind.PLOT and tile.plot and tile.plot.parcel_id:
            self._remove_cell_from_parcel(tile.plot.parcel_id, x, y)
        city_id = tile.city_id
        tile.kind = TileKind.ROAD
        tile.plot = None
        tile.city_id = city_id
        return True

    def build_road(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        tile = self.get(x, y)
        if tile.kind == TileKind.ROAD:
            return False
        if tile.kind == TileKind.PLOT and tile.plot and tile.plot.owner_id is not None:
            return False
        if not self.set_road(x, y):
            return False
        self._fill_plots_adjacent_to_road(x, y)
        return True

    def _fill_plots_adjacent_to_road(self, road_x: int, road_y: int) -> None:
        for nx, ny in self.neighbors4(road_x, road_y):
            n = self.get(nx, ny)
            if n.kind != TileKind.EMPTY:
                continue
            n.kind = TileKind.PLOT
            n.plot = Plot(plot_type=self._choose_plot_type(nx, ny), price=self._plot_price(nx, ny))
            if n.city_id is None:
                n.city_id = self._nearest_city_id(nx, ny)

    def _nearest_city_id(self, x: int, y: int) -> str | None:
        best_id = None
        best_d = 10**9
        for c in self.cities.values():
            d = abs(x - c.center_x) + abs(y - c.center_y)
            if d < best_d:
                best_d = d
                best_id = c.id
        return best_id

    def _choose_plot_type(self, x: int, y: int) -> PlotType:
        nearest = min(
            (abs(x - c.center_x) + abs(y - c.center_y) for c in self.cities.values()),
            default=99,
        )
        if nearest <= 4 or ((x * 17 + y * 31) % 7 == 0):
            return PlotType.SPECIALIZED
        return PlotType.STANDARD

    def _plot_price(self, x: int, y: int) -> int:
        ptype = self._choose_plot_type(x, y)
        base = 150 if ptype == PlotType.SPECIALIZED else 100
        nearest = min(
            (abs(x - c.center_x) + abs(y - c.center_y) for c in self.cities.values()),
            default=10,
        )
        return base + max(0, 12 - nearest) * 10

    def ensure_all_plots_have_road_access(self) -> None:
        for tile in list(self.tiles):
            if tile.kind != TileKind.PLOT:
                continue
            if self.is_road_access(tile.x, tile.y):
                continue
            self._spur_road_to_network(tile.x, tile.y)

    def _spur_road_to_network(self, x: int, y: int) -> None:
        target = self._nearest_road_cell(x, y)
        if target is None:
            for nx, ny in self.neighbors4(x, y):
                self.set_road(nx, ny)
                return
            return
        tx, ty = target
        if x < tx:
            self.set_road(x + 1, y)
        elif x > tx:
            self.set_road(x - 1, y)
        elif y < ty:
            self.set_road(x, y + 1)
        elif y > ty:
            self.set_road(x, y - 1)

    def _nearest_road_cell(self, x: int, y: int) -> tuple[int, int] | None:
        best = None
        best_d = 10**9
        for t in self.tiles:
            if t.kind != TileKind.ROAD:
                continue
            d = abs(t.x - x) + abs(t.y - y)
            if d < best_d:
                best_d = d
                best = (t.x, t.y)
        return best

    def rebuild_territories(self) -> None:
        for city in self.cities.values():
            city.territory = []
        for tile in self.tiles:
            if tile.city_id and tile.city_id in self.cities:
                self.cities[tile.city_id].territory.append((tile.x, tile.y))

    def parcel_size(self, parcel_id: str | None) -> int:
        if not parcel_id or parcel_id not in self.parcels:
            return 1
        return self.parcels[parcel_id].size

    def production_bonus_for_plot(self, plot: Plot) -> float:
        if not plot.parcel_id or plot.parcel_id not in self.parcels:
            return 1.0
        return self.parcels[plot.parcel_id].production_bonus()

    def merge_plots(self, owner_kind: str, owner_id: str, x1: int, y1: int, x2: int, y2: int) -> str:
        a = self.get(x1, y1)
        b = self.get(x2, y2)
        if a.kind != TileKind.PLOT or b.kind != TileKind.PLOT or not a.plot or not b.plot:
            raise ValueError("Both cells must be plots")
        if not a.plot.owned_by(owner_kind, owner_id) or not b.plot.owned_by(owner_kind, owner_id):
            raise ValueError("You must own both plots")
        if abs(x1 - x2) + abs(y1 - y2) != 1:
            raise ValueError("Plots must be adjacent")
        if a.plot.parcel_id and a.plot.parcel_id == b.plot.parcel_id:
            return a.plot.parcel_id

        cells_a = (
            list(self.parcels[a.plot.parcel_id].cells)
            if a.plot.parcel_id and a.plot.parcel_id in self.parcels
            else [(x1, y1)]
        )
        cells_b = (
            list(self.parcels[b.plot.parcel_id].cells)
            if b.plot.parcel_id and b.plot.parcel_id in self.parcels
            else [(x2, y2)]
        )
        for pid in {a.plot.parcel_id, b.plot.parcel_id}:
            if pid and pid in self.parcels:
                del self.parcels[pid]

        parcel = Parcel.create(owner_kind, owner_id, list({*cells_a, *cells_b}))
        self.parcels[parcel.id] = parcel
        for x, y in parcel.cells:
            p = self.get(x, y).plot
            if p:
                p.parcel_id = parcel.id
        return parcel.id

    def register_single_parcel(self, x: int, y: int) -> str:
        tile = self.get(x, y)
        if not tile.plot:
            raise ValueError("Not a plot")
        if tile.plot.parcel_id and tile.plot.parcel_id in self.parcels:
            return tile.plot.parcel_id
        if not tile.plot.owner_kind or not tile.plot.owner_id:
            raise ValueError("Plot must be owned before parcel registration")
        parcel = Parcel.create(tile.plot.owner_kind, tile.plot.owner_id, [(x, y)])
        tile.plot.parcel_id = parcel.id
        self.parcels[parcel.id] = parcel
        return parcel.id

    def _remove_cell_from_parcel(self, parcel_id: str, x: int, y: int) -> None:
        parcel = self.parcels.get(parcel_id)
        if not parcel:
            return
        parcel.cells = [(cx, cy) for cx, cy in parcel.cells if (cx, cy) != (x, y)]
        if not parcel.cells:
            del self.parcels[parcel_id]

    def assert_plot_road_access(self) -> None:
        bad = [
            (t.x, t.y)
            for t in self.tiles
            if t.kind == TileKind.PLOT and not self.is_road_access(t.x, t.y)
        ]
        if bad:
            raise RuntimeError(f"Plots without road access: {bad[:20]} (total {len(bad)})")

    def to_public_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "cities": [c.to_public_dict() for c in self.cities.values()],
            "tiles": [
                {
                    "x": t.x,
                    "y": t.y,
                    "kind": t.kind.value,
                    "city_id": t.city_id,
                    "plot": None
                    if t.plot is None
                    else t.plot.to_public_dict(
                        parcel_size=self.parcel_size(t.plot.parcel_id),
                        production_bonus=round(self.production_bonus_for_plot(t.plot), 3),
                    ),
                }
                for t in self.tiles
                if t.kind != TileKind.EMPTY
            ],
        }


def generate_map(
    width: int,
    height: int,
    city_seeds: list[tuple[str, str, int, int, int]],
    road_stride: int = 3,
) -> GridMap:
    """
    Determine the full grid at game start.

    Cities are NOT special tiles. Each city gets a voronoi territory of normal
    road/plot cells around an anchor point.
    """
    grid = GridMap.create(width, height)

    for cid, name, x, y, pop in city_seeds:
        if not grid.in_bounds(x, y):
            raise ValueError(f"City anchor out of bounds: {x},{y}")
        grid.cities[cid] = City(
            id=cid,
            name=name,
            cash=2000,
            center_x=x,
            center_y=y,
            population=pop,
            inventory=Inventory({"iron": 20, "coal": 20, "energy": 20}),
        )

    for tile in grid.tiles:
        tile.city_id = grid._nearest_city_id(tile.x, tile.y)

    for y in range(height):
        for x in range(width):
            if x % road_stride == 0 or y % road_stride == 0:
                grid.set_road(x, y)

    cities = list(grid.cities.values())
    if cities:
        for i in range(1, len(cities)):
            _carve_manhattan_road(
                grid, cities[0].center_x, cities[0].center_y, cities[i].center_x, cities[i].center_y
            )
        for i in range(len(cities) - 1):
            a, b = cities[i], cities[i + 1]
            _carve_manhattan_road(grid, a.center_x, a.center_y, b.center_x, b.center_y)

    for tile in grid.tiles:
        if tile.kind != TileKind.EMPTY:
            continue
        tile.kind = TileKind.PLOT
        tile.plot = Plot(
            plot_type=grid._choose_plot_type(tile.x, tile.y),
            price=grid._plot_price(tile.x, tile.y),
        )

    grid.ensure_all_plots_have_road_access()
    for tile in grid.tiles:
        if tile.kind == TileKind.EMPTY:
            if grid.is_road_access(tile.x, tile.y):
                tile.kind = TileKind.PLOT
                tile.plot = Plot(
                    plot_type=grid._choose_plot_type(tile.x, tile.y),
                    price=grid._plot_price(tile.x, tile.y),
                )
            else:
                grid.set_road(tile.x, tile.y)

    grid.ensure_all_plots_have_road_access()
    grid.assert_plot_road_access()
    grid.rebuild_territories()
    return grid


def _carve_manhattan_road(grid: GridMap, x0: int, y0: int, x1: int, y1: int) -> None:
    x, y = x0, y0
    while x != x1:
        x += 1 if x1 > x else -1
        grid.set_road(x, y)
    while y != y1:
        y += 1 if y1 > y else -1
        grid.set_road(x, y)


# Re-export plot types used by other modules
__all__ = [
    "TileKind",
    "Tile",
    "GridMap",
    "generate_map",
    "Plot",
    "PlotType",
    "Parcel",
]
