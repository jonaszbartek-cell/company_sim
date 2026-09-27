"""World state + real-time tick loop."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from company_sim.actions import ActionError, ActionResult
from company_sim.company import PLACEHOLDER_METHODS, Company
from company_sim.map_grid import Building, BuildingType, GridMap, TileKind


@dataclass
class WorldConfig:
    map_width: int = 40
    map_height: int = 30
    tick_hz: float = 10.0
    starting_cities: int = 5
    ai_company_count: int = 5  # start smaller; design allows up to ~20


@dataclass
class World:
    config: WorldConfig
    grid: GridMap
    companies: dict[str, Company] = field(default_factory=dict)
    player_company_id: str = "player"
    time_sec: float = 0.0
    paused: bool = False
    tick_index: int = 0

    @classmethod
    def new_game(cls, config: WorldConfig | None = None) -> World:
        config = config or WorldConfig()
        grid = GridMap.create(config.map_width, config.map_height)
        world = cls(config=config, grid=grid)

        # PLACEHOLDER city layout — 5 cities spread on the map
        seeds = [
            ("city_a", "Northport", 8, 6),
            ("city_b", "Millhaven", 30, 7),
            ("city_c", "Riverbend", 20, 15),
            ("city_d", "Oakridge", 10, 24),
            ("city_e", "Southgate", 32, 22),
        ]
        for i, (cid, name, x, y) in enumerate(seeds[: config.starting_cities]):
            from company_sim.map_grid import City

            grid.place_city(City(id=cid, name=name, x=x, y=y, population=800 + i * 150))

        player = Company(id="player", name="Player Co", is_player=True, cash=2500)
        world.companies[player.id] = player
        world.player_company_id = player.id

        for i in range(config.ai_company_count):
            cid = f"ai_{i+1}"
            world.companies[cid] = Company(
                id=cid,
                name=f"Rival {i+1}",
                is_player=False,
                cash=1500,
            )

        return world

    def tick(self, dt: float) -> None:
        if self.paused:
            return
        self.time_sec += dt
        self.tick_index += 1
        self._tick_production(dt)

    def _tick_production(self, dt: float) -> None:
        method = PLACEHOLDER_METHODS["basic_goods"]
        duration = float(method["duration_sec"])
        for tile in self.grid.tiles:
            if tile.kind != TileKind.PLOT or not tile.plot or not tile.plot.building:
                continue
            b = tile.plot.building
            if not b.production_method_id:
                continue
            company = self.companies.get(b.owner_company_id)
            if not company:
                continue
            b.progress += dt / duration
            while b.progress >= 1.0:
                b.progress -= 1.0
                self._try_complete_batch(company, method)

    def _try_complete_batch(self, company: Company, method: dict) -> None:
        for good, qty in method["inputs"].items():
            if company.inventory.get(good, 0) < qty:
                return  # stall until inputs available
        for good, qty in method["inputs"].items():
            company.inventory[good] = company.inventory.get(good, 0) - qty
        for good, qty in method["outputs"].items():
            company.inventory[good] = company.inventory.get(good, 0) + qty

    # --- Actions ---

    def buy_plot(self, company_id: str, x: int, y: int) -> ActionResult:
        company = self._require_company(company_id)
        if not self.grid.in_bounds(x, y):
            raise ActionError("Out of bounds")
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or tile.plot is None:
            raise ActionError("Not a buyable plot")
        if tile.plot.owner_company_id is not None:
            raise ActionError("Plot already owned")
        price = tile.plot.price
        if company.cash < price:
            raise ActionError("Not enough cash")
        company.cash -= price
        tile.plot.owner_company_id = company_id
        return ActionResult(True, f"Bought plot ({x},{y}) for {price}", {"x": x, "y": y, "price": price})

    def build_building(
        self,
        company_id: str,
        x: int,
        y: int,
        building_type: BuildingType = BuildingType.WORKSHOP,
    ) -> ActionResult:
        company = self._require_company(company_id)
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or not tile.plot:
            raise ActionError("Not a plot")
        if tile.plot.owner_company_id != company_id:
            raise ActionError("You do not own this plot")
        if tile.plot.building is not None:
            raise ActionError("Plot already has a building")
        cost = 200  # PLACEHOLDER
        if company.cash < cost:
            raise ActionError("Not enough cash")
        company.cash -= cost
        tile.plot.building = Building(
            building_type=building_type,
            owner_company_id=company_id,
            production_method_id="basic_goods",
        )
        return ActionResult(True, f"Built {building_type.value} at ({x},{y})", {"cost": cost})

    def city_build_road(self, city_id: str, x: int, y: int) -> ActionResult:
        if city_id not in self.grid.cities:
            raise ActionError("Unknown city")
        if not self.grid.build_road(x, y, expand_plots=True):
            raise ActionError("Cannot build road there")
        return ActionResult(True, f"City {city_id} built road at ({x},{y})")

    def set_paused(self, paused: bool) -> ActionResult:
        self.paused = paused
        return ActionResult(True, "paused" if paused else "resumed")

    def _require_company(self, company_id: str) -> Company:
        company = self.companies.get(company_id)
        if not company:
            raise ActionError("Unknown company")
        return company

    def to_public_dict(self) -> dict:
        return {
            "time_sec": round(self.time_sec, 2),
            "tick_index": self.tick_index,
            "paused": self.paused,
            "player_company_id": self.player_company_id,
            "companies": [c.to_public_dict() for c in self.companies.values()],
            "map": self.grid.to_public_dict(),
        }
