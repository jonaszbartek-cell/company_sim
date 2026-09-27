"""Grid map: cities, roads, plots, buildings, parcels."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator
import uuid


class TileKind(str, Enum):
    EMPTY = "empty"  # hinterland / unused (rare after generation)
    CITY = "city"
    ROAD = "road"
    PLOT = "plot"


class PlotType(str, Enum):
    STANDARD = "standard"
    SPECIALIZED = "specialized"


class BuildingType(str, Enum):
    # PLACEHOLDER — real building catalog later
    WORKSHOP = "workshop"
    WAREHOUSE = "warehouse"


@dataclass
class Building:
    building_type: BuildingType
    owner_company_id: str
    production_method_id: str | None = None
    progress: float = 0.0  # 0..1 toward next batch


@dataclass
class Plot:
    plot_type: PlotType
    owner_company_id: str | None = None
    building: Building | None = None
    price: int = 100  # PLACEHOLDER
    parcel_id: str | None = None  # merged adjacent owned plots share one parcel


@dataclass
class City:
    id: str
    name: str
    x: int
    y: int
    population: int = 1000


@dataclass
class Tile:
    x: int
    y: int
    kind: TileKind = TileKind.EMPTY
    city_id: str | None = None
    plot: Plot | None = None


@dataclass
class GridMap:
    width: int
    height: int
    tiles: list[Tile] = field(default_factory=list)
    cities: dict[str, City] = field(default_factory=dict)
    # parcel_id -> list of (x, y)
    parcels: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

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

    def is_road_access(self, x: int, y: int) -> bool:
        """Plot has road access if adjacent to road or city core."""
        for nx, ny in self.neighbors4(x, y):
            kind = self.get(nx, ny).kind
            if kind in (TileKind.ROAD, TileKind.CITY):
                return True
        return False

    def place_city(self, city: City) -> None:
        if not self.in_bounds(city.x, city.y):
            raise ValueError(f"City out of bounds: {city.x},{city.y}")
        tile = self.get(city.x, city.y)
        tile.kind = TileKind.CITY
        tile.city_id = city.id
        tile.plot = None
        self.cities[city.id] = city

    def set_road(self, x: int, y: int) -> bool:
        """Force a cell to road (generation / build). Clears plots."""
        tile = self.get(x, y)
        if tile.kind == TileKind.CITY:
            return False
        # Remove from parcel bookkeeping if converting an owned plot
        if tile.kind == TileKind.PLOT and tile.plot and tile.plot.parcel_id:
            self._remove_cell_from_parcel(tile.plot.parcel_id, x, y)
        tile.kind = TileKind.ROAD
        tile.plot = None
        tile.city_id = None
        return True

    def build_road(self, x: int, y: int) -> bool:
        """
        Build a road on an empty cell or unowned plot.
        After build, convert any newly road-adjacent EMPTY hinterland into plots.
        """
        if not self.in_bounds(x, y):
            return False
        tile = self.get(x, y)
        if tile.kind == TileKind.CITY or tile.kind == TileKind.ROAD:
            return False
        if tile.kind == TileKind.PLOT and tile.plot and tile.plot.owner_company_id:
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

    def _choose_plot_type(self, x: int, y: int) -> PlotType:
        # PLACEHOLDER zoning: specialized clusters near cities / hash bands
        nearest = min(
            (abs(x - c.x) + abs(y - c.y) for c in self.cities.values()),
            default=99,
        )
        if nearest <= 4 or ((x * 17 + y * 31) % 7 == 0):
            return PlotType.SPECIALIZED
        return PlotType.STANDARD

    def _plot_price(self, x: int, y: int) -> int:
        ptype = self._choose_plot_type(x, y)
        base = 150 if ptype == PlotType.SPECIALIZED else 100
        nearest = min(
            (abs(x - c.x) + abs(y - c.y) for c in self.cities.values()),
            default=10,
        )
        return base + max(0, 12 - nearest) * 10

    def ensure_all_plots_have_road_access(self) -> None:
        """Repair pass: any plot without access gets a spur road to nearest road/city."""
        for tile in list(self.tiles):
            if tile.kind != TileKind.PLOT:
                continue
            if self.is_road_access(tile.x, tile.y):
                continue
            self._spur_road_to_network(tile.x, tile.y)

    def _spur_road_to_network(self, x: int, y: int) -> None:
        """Carve a short Manhattan spur from (x,y) toward nearest road/city, converting this cell's neighbor path."""
        target = self._nearest_access_cell(x, y)
        if target is None:
            # Absolute fallback: make one neighbor a road if possible
            for nx, ny in self.neighbors4(x, y):
                if self.get(nx, ny).kind != TileKind.CITY:
                    self.set_road(nx, ny)
                    return
            return
        cx, cy = x, y
        tx, ty = target
        # Move one step from the landlocked plot toward target by converting a neighbor to road
        # (keep the plot itself; give it an adjacent road)
        if cx < tx:
            self.set_road(cx + 1, cy)
        elif cx > tx:
            self.set_road(cx - 1, cy)
        elif cy < ty:
            self.set_road(cx, cy + 1)
        elif cy > ty:
            self.set_road(cx, cy - 1)

    def _nearest_access_cell(self, x: int, y: int) -> tuple[int, int] | None:
        best = None
        best_d = 10**9
        for t in self.tiles:
            if t.kind not in (TileKind.ROAD, TileKind.CITY):
                continue
            d = abs(t.x - x) + abs(t.y - y)
            if d < best_d:
                best_d = d
                best = (t.x, t.y)
        return best

    # --- Parcels (merged plots) ---

    def parcel_size(self, parcel_id: str | None) -> int:
        if not parcel_id:
            return 1
        return max(1, len(self.parcels.get(parcel_id, [])))

    def production_bonus_for_plot(self, plot: Plot) -> float:
        """PLACEHOLDER: +5% throughput per extra cell in the parcel."""
        size = self.parcel_size(plot.parcel_id)
        return 1.0 + 0.05 * (size - 1)

    def merge_plots(self, company_id: str, x1: int, y1: int, x2: int, y2: int) -> str:
        """Merge two adjacent owned plots (and their parcels) into one parcel. Returns parcel_id."""
        a = self.get(x1, y1)
        b = self.get(x2, y2)
        if a.kind != TileKind.PLOT or b.kind != TileKind.PLOT or not a.plot or not b.plot:
            raise ValueError("Both cells must be plots")
        if a.plot.owner_company_id != company_id or b.plot.owner_company_id != company_id:
            raise ValueError("You must own both plots")
        if abs(x1 - x2) + abs(y1 - y2) != 1:
            raise ValueError("Plots must be adjacent")
        if a.plot.parcel_id and a.plot.parcel_id == b.plot.parcel_id:
            return a.plot.parcel_id

        cells_a = self._parcel_cells(a.plot)
        cells_b = self._parcel_cells(b.plot)
        # Prefer keeping an existing parcel id
        parcel_id = a.plot.parcel_id or b.plot.parcel_id or str(uuid.uuid4())
        # Clear old parcel entries
        for pid in {a.plot.parcel_id, b.plot.parcel_id}:
            if pid and pid in self.parcels:
                del self.parcels[pid]
        merged = list({*cells_a, *cells_b})
        self.parcels[parcel_id] = merged
        for x, y in merged:
            p = self.get(x, y).plot
            if p:
                p.parcel_id = parcel_id
        return parcel_id

    def _parcel_cells(self, plot: Plot) -> list[tuple[int, int]]:
        if plot.parcel_id and plot.parcel_id in self.parcels:
            return list(self.parcels[plot.parcel_id])
        # Single-cell parcel not registered yet — find by identity scan is avoided; caller passes coords
        return []

    def register_single_parcel(self, x: int, y: int) -> str:
        tile = self.get(x, y)
        if not tile.plot:
            raise ValueError("Not a plot")
        if tile.plot.parcel_id:
            return tile.plot.parcel_id
        pid = str(uuid.uuid4())
        tile.plot.parcel_id = pid
        self.parcels[pid] = [(x, y)]
        return pid

    def _remove_cell_from_parcel(self, parcel_id: str, x: int, y: int) -> None:
        cells = self.parcels.get(parcel_id)
        if not cells:
            return
        self.parcels[parcel_id] = [(cx, cy) for cx, cy in cells if (cx, cy) != (x, y)]
        if not self.parcels[parcel_id]:
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
            "cities": [
                {
                    "id": c.id,
                    "name": c.name,
                    "x": c.x,
                    "y": c.y,
                    "population": c.population,
                }
                for c in self.cities.values()
            ],
            "tiles": [
                {
                    "x": t.x,
                    "y": t.y,
                    "kind": t.kind.value,
                    "city_id": t.city_id,
                    "plot": None
                    if t.plot is None
                    else {
                        "plot_type": t.plot.plot_type.value,
                        "owner_company_id": t.plot.owner_company_id,
                        "price": t.plot.price,
                        "parcel_id": t.plot.parcel_id,
                        "parcel_size": self.parcel_size(t.plot.parcel_id),
                        "production_bonus": round(self.production_bonus_for_plot(t.plot), 3),
                        "building": None
                        if t.plot.building is None
                        else {
                            "building_type": t.plot.building.building_type.value,
                            "owner_company_id": t.plot.building.owner_company_id,
                            "production_method_id": t.plot.building.production_method_id,
                            "progress": t.plot.building.progress,
                        },
                    },
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

    - Place cities
    - Lay a road lattice (every `road_stride` rows/cols) so plots can touch roads
    - Connect cities with Manhattan corridors
    - Fill remaining cells as standard/specialized plots
    - Repair any plot lacking road access
    """
    grid = GridMap.create(width, height)

    for cid, name, x, y, pop in city_seeds:
        grid.place_city(City(id=cid, name=name, x=x, y=y, population=pop))

    # Lattice roads (cities stay cities)
    for y in range(height):
        for x in range(width):
            if grid.get(x, y).kind == TileKind.CITY:
                continue
            if x % road_stride == 0 or y % road_stride == 0:
                grid.set_road(x, y)

    # Connect cities with corridors (ensure network even if lattice misses)
    cities = list(grid.cities.values())
    for i in range(1, len(cities)):
        _carve_manhattan_road(grid, cities[0].x, cities[0].y, cities[i].x, cities[i].y)

    # Also lightly connect sequential cities
    for i in range(len(cities) - 1):
        a, b = cities[i], cities[i + 1]
        _carve_manhattan_road(grid, a.x, a.y, b.x, b.y)

    # Remaining non-city, non-road → plots
    for tile in grid.tiles:
        if tile.kind != TileKind.EMPTY:
            continue
        tile.kind = TileKind.PLOT
        tile.plot = Plot(
            plot_type=grid._choose_plot_type(tile.x, tile.y),
            price=grid._plot_price(tile.x, tile.y),
        )

    grid.ensure_all_plots_have_road_access()
    # Re-fill: spur roads may have overwritten plots; ensure no EMPTY left unwanted
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
    return grid


def _carve_manhattan_road(grid: GridMap, x0: int, y0: int, x1: int, y1: int) -> None:
    x, y = x0, y0
    while x != x1:
        x += 1 if x1 > x else -1
        if grid.get(x, y).kind != TileKind.CITY:
            grid.set_road(x, y)
    while y != y1:
        y += 1 if y1 > y else -1
        if grid.get(x, y).kind != TileKind.CITY:
            grid.set_road(x, y)
