"""World state + real-time tick loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from company_sim.actions import ActionError, ActionResult
from company_sim.company import PLACEHOLDER_METHODS, Company
from company_sim.map_grid import Building, BuildingType, TileKind, generate_map


@dataclass
class WorldConfig:
    map_width: int = 40
    map_height: int = 30
    tick_hz: float = 10.0
    starting_cities: int = 5
    ai_company_count: int = 5  # start smaller; design allows up to ~20
    road_stride: int = 3
    player_starting_cash: int = 2500
    road_build_cost: int = 50  # PLACEHOLDER


@dataclass
class World:
    config: WorldConfig
    grid: object  # GridMap
    companies: dict[str, Company] = field(default_factory=dict)
    player_company_id: str = "player"
    time_sec: float = 0.0
    paused: bool = False
    tick_index: int = 0

    @classmethod
    def new_game(cls, config: WorldConfig | None = None) -> World:
        config = config or WorldConfig()
        seeds = [
            ("city_a", "Northport", 8, 6, 800),
            ("city_b", "Millhaven", 30, 7, 950),
            ("city_c", "Riverbend", 20, 15, 1100),
            ("city_d", "Oakridge", 10, 24, 900),
            ("city_e", "Southgate", 32, 22, 1050),
        ][: config.starting_cities]

        grid = generate_map(
            config.map_width,
            config.map_height,
            city_seeds=seeds,
            road_stride=config.road_stride,
        )
        world = cls(config=config, grid=grid)

        player = Company(
            id="player",
            name="Player Co",
            is_player=True,
            cash=config.player_starting_cash,
            inventory={"materials": 40, "goods": 5},
        )
        world.companies[player.id] = player
        world.player_company_id = player.id
        world._assign_starter_plot(player.id)

        for i in range(config.ai_company_count):
            cid = f"ai_{i+1}"
            world.companies[cid] = Company(
                id=cid,
                name=f"Rival {i+1}",
                is_player=False,
                cash=1500,
                inventory={"materials": 15, "goods": 0},
            )

        return world

    def _assign_starter_plot(self, company_id: str) -> None:
        """Give the player a free owned plot adjacent to a city/road, near first city."""
        cities = list(self.grid.cities.values())
        if not cities:
            return
        city = cities[0]
        candidates = []
        for tile in self.grid.tiles:
            if tile.kind != TileKind.PLOT or not tile.plot:
                continue
            if tile.plot.owner_company_id is not None:
                continue
            if not self.grid.is_road_access(tile.x, tile.y):
                continue
            dist = abs(tile.x - city.x) + abs(tile.y - city.y)
            candidates.append((dist, tile))
        if not candidates:
            return
        candidates.sort(key=lambda t: t[0])
        tile = candidates[0][1]
        tile.plot.owner_company_id = company_id
        tile.plot.price = 0
        self.grid.register_single_parcel(tile.x, tile.y)

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
            bonus = self.grid.production_bonus_for_plot(tile.plot)
            b.progress += (dt / duration) * bonus
            while b.progress >= 1.0:
                b.progress -= 1.0
                self._try_complete_batch(company, method)

    def _try_complete_batch(self, company: Company, method: dict) -> None:
        for good, qty in method["inputs"].items():
            if company.inventory.get(good, 0) < qty:
                return
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
        if not self.grid.is_road_access(x, y):
            raise ActionError("Plot has no road access")
        price = tile.plot.price
        if company.cash < price:
            raise ActionError("Not enough cash")
        company.cash -= price
        tile.plot.owner_company_id = company_id
        self.grid.register_single_parcel(x, y)
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

    def build_road(self, actor_kind: str, actor_id: str, x: int, y: int) -> ActionResult:
        """Cities or companies can build roads on empty/unowned plot cells."""
        if actor_kind == "city":
            if actor_id not in self.grid.cities:
                raise ActionError("Unknown city")
        elif actor_kind == "company":
            company = self._require_company(actor_id)
            cost = self.config.road_build_cost
            if company.cash < cost:
                raise ActionError("Not enough cash")
        else:
            raise ActionError("Invalid actor")

        if not self.grid.build_road(x, y):
            raise ActionError("Cannot build road there")

        if actor_kind == "company":
            company = self.companies[actor_id]
            company.cash -= self.config.road_build_cost
            return ActionResult(
                True,
                f"Company {actor_id} built road at ({x},{y})",
                {"cost": self.config.road_build_cost},
            )
        return ActionResult(True, f"City {actor_id} built road at ({x},{y})")

    def city_build_road(self, city_id: str, x: int, y: int) -> ActionResult:
        return self.build_road("city", city_id, x, y)

    def company_build_road(self, company_id: str, x: int, y: int) -> ActionResult:
        return self.build_road("company", company_id, x, y)

    def merge_plots(self, company_id: str, x1: int, y1: int, x2: int, y2: int) -> ActionResult:
        self._require_company(company_id)
        try:
            # Ensure singleton parcels exist for merge bookkeeping
            for x, y in ((x1, y1), (x2, y2)):
                tile = self.grid.get(x, y)
                if tile.plot and tile.plot.owner_company_id == company_id and not tile.plot.parcel_id:
                    self.grid.register_single_parcel(x, y)
            # Fix merge helper to include coords when parcel lists empty
            parcel_id = self._merge_owned_plots(company_id, x1, y1, x2, y2)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        size = self.grid.parcel_size(parcel_id)
        return ActionResult(
            True,
            f"Merged plots into parcel ({size} cells)",
            {"parcel_id": parcel_id, "size": size},
        )

    def _merge_owned_plots(self, company_id: str, x1: int, y1: int, x2: int, y2: int) -> str:
        a = self.grid.get(x1, y1)
        b = self.grid.get(x2, y2)
        if a.kind != TileKind.PLOT or b.kind != TileKind.PLOT or not a.plot or not b.plot:
            raise ValueError("Both cells must be plots")
        if a.plot.owner_company_id != company_id or b.plot.owner_company_id != company_id:
            raise ValueError("You must own both plots")
        if abs(x1 - x2) + abs(y1 - y2) != 1:
            raise ValueError("Plots must be adjacent")

        if not a.plot.parcel_id:
            self.grid.register_single_parcel(x1, y1)
        if not b.plot.parcel_id:
            self.grid.register_single_parcel(x2, y2)

        if a.plot.parcel_id == b.plot.parcel_id:
            return a.plot.parcel_id  # type: ignore[return-value]

        return self.grid.merge_plots(company_id, x1, y1, x2, y2)

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
