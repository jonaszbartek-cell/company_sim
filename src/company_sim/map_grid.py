"""Grid map: cities, roads, plots, buildings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class TileKind(str, Enum):
    EMPTY = "empty"
    CITY = "city"
    ROAD = "road"
    PLOT = "plot"


class PlotType(str, Enum):
    # PLACEHOLDER types — replace with real data later
    STANDARD = "standard"
    INDUSTRIAL = "industrial"
    COMMERCIAL = "commercial"


class BuildingType(str, Enum):
    # PLACEHOLDER
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


@dataclass
class City:
    id: str
    name: str
    x: int
    y: int
    population: int = 1000
    # Expansion: city core occupies a cell; roads grow outward later


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

    def place_city(self, city: City) -> None:
        if not self.in_bounds(city.x, city.y):
            raise ValueError(f"City out of bounds: {city.x},{city.y}")
        tile = self.get(city.x, city.y)
        tile.kind = TileKind.CITY
        tile.city_id = city.id
        self.cities[city.id] = city
        # Seed a ring of roads + plots so the map is immediately interactive
        self._seed_city_roads(city)

    def _seed_city_roads(self, city: City) -> None:
        """PLACEHOLDER bootstrap: cross of roads and adjacent buyable plots."""
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rx, ry = city.x + dx, city.y + dy
            if self.in_bounds(rx, ry):
                self.build_road(rx, ry, expand_plots=True)

    def build_road(self, x: int, y: int, expand_plots: bool = True) -> bool:
        """Build a road cell. Returns False if cell cannot become a road."""
        tile = self.get(x, y)
        if tile.kind in (TileKind.CITY, TileKind.ROAD):
            return False
        if tile.kind == TileKind.PLOT and tile.plot and tile.plot.owner_company_id:
            return False
        tile.kind = TileKind.ROAD
        tile.plot = None
        tile.city_id = None
        if expand_plots:
            self._spawn_plots_adjacent_to_road(x, y)
        return True

    def _spawn_plots_adjacent_to_road(self, road_x: int, road_y: int) -> None:
        for nx, ny in self.neighbors4(road_x, road_y):
            n = self.get(nx, ny)
            if n.kind != TileKind.EMPTY:
                continue
            # PLACEHOLDER typing heuristic
            plot_type = PlotType.STANDARD
            if (nx + ny) % 3 == 0:
                plot_type = PlotType.INDUSTRIAL
            elif (nx + ny) % 3 == 1:
                plot_type = PlotType.COMMERCIAL
            n.kind = TileKind.PLOT
            n.plot = Plot(plot_type=plot_type)

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
