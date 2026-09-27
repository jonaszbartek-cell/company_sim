"""World state + real-time tick loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from company_sim.actions import ActionError, ActionResult
from company_sim.actors import PLACEHOLDER_METHODS, Actor, ActorKind, Company
from company_sim.map_grid import Building, BuildingType, GridMap, TileKind, generate_map


@dataclass
class WorldConfig:
    map_width: int = 40
    map_height: int = 30
    tick_hz: float = 10.0
    starting_cities: int = 5
    ai_company_count: int = 5
    road_stride: int = 3
    player_starting_cash: int = 2500
    road_build_cost: int = 50  # PLACEHOLDER


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
        world._assign_starter_plot("company", player.id)

        for i in range(config.ai_company_count):
            cid = f"ai_{i+1}"
            world.companies[cid] = Company(
                id=cid,
                name=f"Rival {i+1}",
                is_player=False,
                cash=1500,
                inventory={"materials": 15, "goods": 0},
            )

        for city in grid.cities.values():
            world._assign_starter_plot("city", city.id, near=(city.center_x, city.center_y))

        return world

    def get_actor(self, kind: ActorKind | str, actor_id: str) -> Actor:
        if kind == "company":
            actor = self.companies.get(actor_id)
        elif kind == "city":
            actor = self.grid.cities.get(actor_id)
        else:
            raise ActionError("Invalid actor kind")
        if actor is None:
            raise ActionError(f"Unknown {kind}: {actor_id}")
        return actor

    def iter_ai_actors(self) -> list[Actor]:
        actors: list[Actor] = [c for c in self.companies.values() if not c.is_player]
        actors.extend(self.grid.cities.values())
        return actors

    def owned_plots(self, kind: str, actor_id: str) -> list:
        return [
            t
            for t in self.grid.tiles
            if t.kind == TileKind.PLOT
            and t.plot
            and t.plot.owner_kind == kind
            and t.plot.owner_id == actor_id
        ]

    def _assign_starter_plot(
        self,
        owner_kind: str,
        owner_id: str,
        near: tuple[int, int] | None = None,
    ) -> None:
        if near is None:
            cities = list(self.grid.cities.values())
            if not cities:
                return
            near = (cities[0].center_x, cities[0].center_y)
        nx0, ny0 = near
        candidates = []
        for tile in self.grid.tiles:
            if tile.kind != TileKind.PLOT or not tile.plot:
                continue
            if tile.plot.owner_id is not None:
                continue
            if not self.grid.is_road_access(tile.x, tile.y):
                continue
            if owner_kind == "city" and tile.city_id != owner_id:
                continue
            dist = abs(tile.x - nx0) + abs(tile.y - ny0)
            candidates.append((dist, tile))
        if not candidates:
            return
        candidates.sort(key=lambda t: t[0])
        tile = candidates[0][1]
        tile.plot.owner_kind = owner_kind
        tile.plot.owner_id = owner_id
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
            try:
                actor = self.get_actor(b.owner_kind, b.owner_id)
            except ActionError:
                continue
            bonus = self.grid.production_bonus_for_plot(tile.plot)
            b.progress += (dt / duration) * bonus
            while b.progress >= 1.0:
                b.progress -= 1.0
                self._try_complete_batch(actor.inventory, method)

    def _try_complete_batch(self, inventory: dict[str, int], method: dict) -> None:
        for good, qty in method["inputs"].items():
            if inventory.get(good, 0) < qty:
                return
        for good, qty in method["inputs"].items():
            inventory[good] = inventory.get(good, 0) - qty
        for good, qty in method["outputs"].items():
            inventory[good] = inventory.get(good, 0) + qty

    def buy_plot(self, owner_kind: str, owner_id: str, x: int, y: int) -> ActionResult:
        actor = self.get_actor(owner_kind, owner_id)
        if not self.grid.in_bounds(x, y):
            raise ActionError("Out of bounds")
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or tile.plot is None:
            raise ActionError("Not a buyable plot")
        if tile.plot.owner_id is not None:
            raise ActionError("Plot already owned")
        if not self.grid.is_road_access(x, y):
            raise ActionError("Plot has no road access")
        price = tile.plot.price
        if actor.cash < price:
            raise ActionError("Not enough cash")
        actor.cash -= price
        tile.plot.owner_kind = owner_kind
        tile.plot.owner_id = owner_id
        self.grid.register_single_parcel(x, y)
        return ActionResult(True, f"Bought plot ({x},{y}) for {price}", {"x": x, "y": y, "price": price})

    def build_building(
        self,
        owner_kind: str,
        owner_id: str,
        x: int,
        y: int,
        building_type: BuildingType = BuildingType.WORKSHOP,
    ) -> ActionResult:
        actor = self.get_actor(owner_kind, owner_id)
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or not tile.plot:
            raise ActionError("Not a plot")
        if tile.plot.owner_kind != owner_kind or tile.plot.owner_id != owner_id:
            raise ActionError("You do not own this plot")
        if tile.plot.building is not None:
            raise ActionError("Plot already has a building")
        cost = 200  # PLACEHOLDER
        if actor.cash < cost:
            raise ActionError("Not enough cash")
        actor.cash -= cost
        tile.plot.building = Building(
            building_type=building_type,
            owner_kind=owner_kind,
            owner_id=owner_id,
            production_method_id="basic_goods",
        )
        return ActionResult(True, f"Built {building_type.value} at ({x},{y})", {"cost": cost})

    def build_road(self, actor_kind: str, actor_id: str, x: int, y: int) -> ActionResult:
        actor = self.get_actor(actor_kind, actor_id)
        cost = self.config.road_build_cost
        if actor.cash < cost:
            raise ActionError("Not enough cash")
        if not self.grid.build_road(x, y):
            raise ActionError("Cannot build road there")
        actor.cash -= cost
        self.grid.rebuild_territories()
        return ActionResult(
            True,
            f"{actor_kind} {actor_id} built road at ({x},{y})",
            {"cost": cost},
        )

    def city_build_road(self, city_id: str, x: int, y: int) -> ActionResult:
        return self.build_road("city", city_id, x, y)

    def company_build_road(self, company_id: str, x: int, y: int) -> ActionResult:
        return self.build_road("company", company_id, x, y)

    def merge_plots(self, owner_kind: str, owner_id: str, x1: int, y1: int, x2: int, y2: int) -> ActionResult:
        self.get_actor(owner_kind, owner_id)
        for x, y in ((x1, y1), (x2, y2)):
            tile = self.grid.get(x, y)
            if (
                tile.plot
                and tile.plot.owner_kind == owner_kind
                and tile.plot.owner_id == owner_id
                and not tile.plot.parcel_id
            ):
                self.grid.register_single_parcel(x, y)
        try:
            parcel_id = self.grid.merge_plots(owner_kind, owner_id, x1, y1, x2, y2)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        size = self.grid.parcel_size(parcel_id)
        return ActionResult(True, f"Merged plots into parcel ({size} cells)", {"parcel_id": parcel_id, "size": size})

    def set_paused(self, paused: bool) -> ActionResult:
        self.paused = paused
        return ActionResult(True, "paused" if paused else "resumed")

    def to_public_dict(self) -> dict:
        return {
            "time_sec": round(self.time_sec, 2),
            "tick_index": self.tick_index,
            "paused": self.paused,
            "player_company_id": self.player_company_id,
            "companies": [c.to_public_dict() for c in self.companies.values()],
            "map": self.grid.to_public_dict(),
        }
