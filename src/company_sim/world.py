"""World state + day-based agent turn loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from company_sim.actions import ActionError, ActionResult
from company_sim.actors import Actor, ActorKind, Company
from company_sim.buildings import Building
from company_sim.content import GameContent
from company_sim.items import Inventory
from company_sim.map_grid import GridMap, TileKind, generate_map
from company_sim.market import Listing, Market
from company_sim.persistence import GamePersistence, default_save_dir


@dataclass
class WorldConfig:
    map_width: int = 24
    map_height: int = 18
    tick_hz: float = 4.0  # UI refresh / delay pacing only
    starting_cities: int = 1
    ai_company_count: int = 2
    road_stride: int = 3
    player_starting_cash: int = 2500
    road_build_cost: int = 50  # PLACEHOLDER
    # Seconds of wall time between AI agent turns (slow-down only; never speeds sim)
    min_seconds_between_turns: float = 1.5
    save_dir: str | None = None


def _starter_inventory() -> Inventory:
    return Inventory({"iron": 20, "coal": 20, "energy": 20, "steel": 0})


@dataclass
class World:
    config: WorldConfig
    grid: GridMap
    content: GameContent
    market: Market = field(default_factory=Market)
    companies: dict[str, Company] = field(default_factory=dict)
    player_company_id: str = "player"
    day: int = 1
    time_sec: float = 0.0
    paused: bool = False
    tick_index: int = 0
    # Round-robin index into turn_queue (AI companies + cities; player acts via UI)
    turn_index: int = 0
    persistence: GamePersistence = field(default_factory=GamePersistence)

    @property
    def items(self):
        return self.content.items

    @property
    def buildings(self):
        return self.content.buildings

    @property
    def production(self):
        return self.content.production

    @classmethod
    def new_game(cls, config: WorldConfig | None = None) -> World:
        config = config or WorldConfig()
        content = GameContent.load()

        # Scoped seed: one city for now
        seeds = [
            ("city_a", "Millhaven", config.map_width // 2, config.map_height // 2, 1100),
        ][: config.starting_cities]

        grid = generate_map(
            config.map_width,
            config.map_height,
            city_seeds=seeds,
            road_stride=config.road_stride,
        )
        save_root = Path(config.save_dir) if config.save_dir else default_save_dir()
        world = cls(
            config=config,
            grid=grid,
            content=content,
            market=Market(),
            persistence=GamePersistence(save_root),
        )

        player = Company(
            id="player",
            name="Player Co",
            is_player=True,
            cash=config.player_starting_cash,
            inventory=_starter_inventory(),
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
                inventory=Inventory({"iron": 10, "coal": 10, "energy": 10, "steel": 0}),
            )
            world._assign_starter_plot("company", cid)

        for city in grid.cities.values():
            city.inventory = Inventory({"iron": 15, "coal": 15, "energy": 15, "steel": 0})
            world._assign_starter_plot("city", city.id, near=(city.center_x, city.center_y))

        # Seed a few market sell listings from nowhere (starter liquidity)
        world._seed_market()
        world.persistence.save_all(world)
        return world

    def _seed_market(self) -> None:
        """Place a small city-backed sell board so buyers have something to hit."""
        for city in self.grid.cities.values():
            for item_id, qty, price in (("iron", 5, 8), ("coal", 5, 6), ("energy", 5, 10)):
                if city.inventory.get(item_id) < qty:
                    continue
                city.inventory.add(item_id, -qty)
                self.market.inventory.add(item_id, qty)
                lid = self.market.next_id()
                self.market.add_listing(
                    Listing(
                        id=lid,
                        side="sell",
                        item_id=item_id,
                        quantity=qty,
                        price=price,
                        owner_kind="city",
                        owner_id=city.id,
                    )
                )

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
        """AI turn order: rival companies first, then cities."""
        actors: list[Actor] = [c for c in self.companies.values() if not c.is_player]
        actors.extend(self.grid.cities.values())
        return actors

    def iter_all_actors(self) -> list[Actor]:
        actors: list[Actor] = list(self.companies.values())
        actors.extend(self.grid.cities.values())
        return actors

    def iter_companies(self) -> list[Company]:
        return list(self.companies.values())

    def turn_queue_ids(self) -> list[str]:
        return [f"{a.kind}:{a.id}" for a in self.iter_ai_actors()]

    def current_turn_token(self) -> str | None:
        queue = self.turn_queue_ids()
        if not queue:
            return None
        return queue[self.turn_index % len(queue)]

    def current_turn_actor(self) -> Actor | None:
        token = self.current_turn_token()
        if not token:
            return None
        kind, aid = token.split(":", 1)
        return self.get_actor(kind, aid)

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
        tile.plot.claim(owner_kind, owner_id)
        tile.plot.price = 0
        tile.plot.value = tile.plot.value or 100
        self.grid.register_single_parcel(tile.x, tile.y)

    # --- Day scheduling -------------------------------------------------

    def tick(self, dt: float) -> None:
        """Wall-clock pacing only (UI). Game days advance via agent actions."""
        if self.paused:
            return
        self.time_sec += dt
        self.tick_index += 1

    def note_actor_action(self, kind: str, actor_id: str) -> None:
        """Mark that this actor took an action this day; maybe advance the day."""
        actor = self.get_actor(kind, actor_id)
        actor.mark_acted()
        self._maybe_advance_day()

    def _maybe_advance_day(self) -> None:
        """One game day passes when ALL companies have made an action."""
        companies = self.iter_companies()
        if not companies:
            return
        if all(c.acted_this_day for c in companies):
            self.day += 1
            for actor in self.iter_all_actors():
                actor.reset_day()
            self._idle_all_buildings()
            self.persistence.save_all(self)

    def _idle_all_buildings(self) -> None:
        for t in self.grid.tiles:
            if t.plot and t.plot.building and t.plot.building.status == "working":
                t.plot.building.status = "idle"

    def advance_ai_turn(self) -> None:
        queue = self.turn_queue_ids()
        if queue:
            self.turn_index = (self.turn_index + 1) % len(queue)

    # --- Core actions ---------------------------------------------------

    def buy_plot(self, owner_kind: str, owner_id: str, x: int, y: int) -> ActionResult:
        actor = self.get_actor(owner_kind, owner_id)
        if not self.grid.in_bounds(x, y):
            raise ActionError("Out of bounds")
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or tile.plot is None:
            raise ActionError("Not a buyable plot")
        if tile.plot.is_owned:
            raise ActionError("Plot already owned")
        if not self.grid.is_road_access(x, y):
            raise ActionError("Plot has no road access")
        price = tile.plot.price
        if actor.cash < price:
            raise ActionError("Not enough cash")
        actor.cash -= price
        tile.plot.claim(owner_kind, owner_id)
        tile.plot.value = max(tile.plot.value, price)
        self.grid.register_single_parcel(x, y)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, f"Bought plot ({x},{y}) for {price}", {"x": x, "y": y, "price": price})

    def build_building(
        self,
        owner_kind: str,
        owner_id: str,
        x: int,
        y: int,
        building_id: str = "foundry",
    ) -> ActionResult:
        actor = self.get_actor(owner_kind, owner_id)
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or not tile.plot:
            raise ActionError("Not a plot")
        if not tile.plot.owned_by(owner_kind, owner_id):
            raise ActionError("You do not own this plot")
        if tile.plot.building is not None:
            raise ActionError("Plot already has a building")
        try:
            bdef = self.buildings.get(building_id)
        except KeyError as exc:
            raise ActionError(f"Unknown building: {building_id}") from exc
        if not bdef.allows_plot_type(tile.plot.plot_type):
            raise ActionError(f"{bdef.name} cannot be built on {tile.plot.plot_type.value} plots")
        if actor.cash < bdef.build_cost:
            raise ActionError("Not enough cash")

        methods = self.content.methods_for_building(building_id)
        method_id = methods[0].id if methods else None

        actor.cash -= bdef.build_cost
        tile.plot.building = Building(
            building_id=building_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            production_method_id=method_id,
            status="idle",
        )
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Built {bdef.name} at ({x},{y})",
            {"cost": bdef.build_cost, "building_id": building_id, "production_method_id": method_id},
        )

    def set_production_method(
        self,
        owner_kind: str,
        owner_id: str,
        x: int,
        y: int,
        method_id: str,
    ) -> ActionResult:
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or not tile.plot or not tile.plot.building:
            raise ActionError("No building there")
        b = tile.plot.building
        if not tile.plot.owned_by(owner_kind, owner_id):
            raise ActionError("You do not own this plot")
        try:
            method = self.production.get(method_id)
        except KeyError as exc:
            raise ActionError(f"Unknown method: {method_id}") from exc
        if method.building_id != b.building_id:
            raise ActionError(f"{method_id} cannot run in {b.building_id}")
        b.production_method_id = method_id
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, f"Set method {method_id}", {"method_id": method_id})

    def produce(self, owner_kind: str, owner_id: str, x: int, y: int) -> ActionResult:
        """Run one production batch on a building (explicit day action)."""
        actor = self.get_actor(owner_kind, owner_id)
        tile = self.grid.get(x, y)
        if tile.kind != TileKind.PLOT or not tile.plot or not tile.plot.building:
            raise ActionError("No building there")
        if not tile.plot.owned_by(owner_kind, owner_id):
            raise ActionError("You do not own this plot")
        b = tile.plot.building
        if not b.production_method_id:
            raise ActionError("No production method selected")
        try:
            method = self.production.get(b.production_method_id)
        except KeyError as exc:
            raise ActionError(f"Unknown method: {b.production_method_id}") from exc
        if method.building_id != b.building_id:
            raise ActionError("Method does not match building")
        if not actor.inventory.has(method.inputs):
            raise ActionError(f"Missing inputs: need {method.inputs}, have {actor.inventory.as_dict()}")

        b.status = "working"
        actor.inventory.consume(method.inputs)
        # Parcel bonus: chance of extra output unit (simple floor of bonus)
        bonus = self.grid.production_bonus_for_plot(tile.plot)
        actor.inventory.produce(method.outputs)
        if bonus > 1.0 and int(bonus) > 1:
            # PLACEHOLDER: grant floor(bonus)-1 extra full output sets rarely skipped
            for _ in range(int(bonus) - 1):
                actor.inventory.produce(method.outputs)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Produced via {method.id} at ({x},{y})",
            {"inputs": method.inputs, "outputs": method.outputs, "bonus": bonus},
        )

    def build_road(self, actor_kind: str, actor_id: str, x: int, y: int) -> ActionResult:
        actor = self.get_actor(actor_kind, actor_id)
        cost = self.config.road_build_cost
        if actor.cash < cost:
            raise ActionError("Not enough cash")
        if not self.grid.build_road(x, y):
            raise ActionError("Cannot build road there")
        actor.cash -= cost
        self.grid.rebuild_territories()
        self.note_actor_action(actor_kind, actor_id)
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
            if tile.plot and tile.plot.owned_by(owner_kind, owner_id) and not tile.plot.parcel_id:
                self.grid.register_single_parcel(x, y)
        try:
            parcel_id = self.grid.merge_plots(owner_kind, owner_id, x1, y1, x2, y2)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        size = self.grid.parcel_size(parcel_id)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, f"Merged plots into parcel ({size} cells)", {"parcel_id": parcel_id, "size": size})

    # --- Market ---------------------------------------------------------

    def post_sell(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
        actor = self.get_actor(owner_kind, owner_id)
        if actor.inventory.get(item_id) < quantity:
            raise ActionError("Not enough goods to sell")
        actor.inventory.add(item_id, -quantity)
        self.market.inventory.add(item_id, quantity)
        lid = self.market.next_id()
        listing = Listing(
            id=lid,
            side="sell",
            item_id=item_id,
            quantity=quantity,
            price=price,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )
        self.market.add_listing(listing)
        matched = self._match_buys_against_sell(listing)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Posted sell #{lid}: {quantity}x {item_id} @ {price}",
            {"listing_id": lid, "matched": matched},
        )

    def post_buy(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
        actor = self.get_actor(owner_kind, owner_id)
        total = price * quantity
        if actor.cash < total:
            raise ActionError("Not enough cash to post buy order")
        actor.cash -= total
        self.market.escrow_add(owner_kind, owner_id, total)
        lid = self.market.next_id()
        listing = Listing(
            id=lid,
            side="buy",
            item_id=item_id,
            quantity=quantity,
            price=price,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )
        self.market.add_listing(listing)
        filled = self._fill_buy_listing(listing)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Posted buy #{lid}: {quantity}x {item_id} @ {price}",
            {"listing_id": lid, "filled": filled},
        )

    def buy_from_market(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
    ) -> ActionResult:
        """Buy up to `quantity` from lowest-price sell listings."""
        if quantity <= 0:
            raise ActionError("Invalid quantity")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
        buyer = self.get_actor(owner_kind, owner_id)
        remaining = quantity
        spent = 0
        got = 0
        fills: list[dict] = []
        while remaining > 0:
            sells = [
                s
                for s in self.market.sell_listings_for(item_id)
                if not (s.owner_kind == owner_kind and s.owner_id == owner_id)
            ]
            if not sells:
                break
            listing = sells[0]
            take = min(remaining, listing.quantity)
            cost = take * listing.price
            if buyer.cash < cost:
                # Afford partial?
                afford = buyer.cash // listing.price
                if afford <= 0:
                    break
                take = min(take, afford)
                cost = take * listing.price
            self._transfer_sell_to_buyer(listing, take, buyer)
            spent += cost
            got += take
            remaining -= take
            fills.append({"listing_id": listing.id, "qty": take, "price": listing.price})
        if got == 0:
            raise ActionError("No matching sell listings (or cannot afford)")
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Bought {got}x {item_id} for {spent}",
            {"got": got, "spent": spent, "fills": fills},
        )

    def _transfer_sell_to_buyer(self, listing: Listing, qty: int, buyer: Actor) -> None:
        cost = qty * listing.price
        if buyer.cash < cost:
            raise ActionError("Not enough cash")
        if self.market.inventory.get(listing.item_id) < qty:
            raise ActionError("Market inventory mismatch")
        buyer.cash -= cost
        self.market.inventory.add(listing.item_id, -qty)
        buyer.inventory.add(listing.item_id, qty)
        seller = self.get_actor(listing.owner_kind, listing.owner_id)
        seller.cash += cost
        listing.quantity -= qty
        if listing.quantity <= 0:
            self.market.remove_listing(listing.id)

    def _fill_buy_listing(self, buy: Listing) -> list[dict]:
        buyer = self.get_actor(buy.owner_kind, buy.owner_id)
        fills: list[dict] = []
        while buy.quantity > 0 and buy.id in self.market.listings:
            sells = [s for s in self.market.sell_listings_for(buy.item_id) if s.price <= buy.price]
            if not sells:
                break
            sell = sells[0]
            if sell.owner_kind == buy.owner_kind and sell.owner_id == buy.owner_id:
                break
            take = min(buy.quantity, sell.quantity)
            cost = take * sell.price
            # Release escrow at buy.price, pay seller sell.price, refund difference
            reserved = take * buy.price
            if not self.market.escrow_take(buy.owner_kind, buy.owner_id, reserved):
                break
            if self.market.inventory.get(sell.item_id) < take:
                self.market.escrow_add(buy.owner_kind, buy.owner_id, reserved)
                break
            self.market.inventory.add(sell.item_id, -take)
            buyer.inventory.add(buy.item_id, take)
            seller = self.get_actor(sell.owner_kind, sell.owner_id)
            seller.cash += cost
            refund = reserved - cost
            if refund:
                buyer.cash += refund
            sell.quantity -= take
            buy.quantity -= take
            fills.append({"sell_id": sell.id, "qty": take, "price": sell.price})
            if sell.quantity <= 0:
                self.market.remove_listing(sell.id)
        if buy.quantity <= 0 and buy.id in self.market.listings:
            self.market.remove_listing(buy.id)
        return fills

    def _match_buys_against_sell(self, sell: Listing) -> list[dict]:
        matched: list[dict] = []
        while sell.quantity > 0 and sell.id in self.market.listings:
            buys = [b for b in self.market.buy_listings_for(sell.item_id) if b.price >= sell.price]
            if not buys:
                break
            buy = buys[0]
            if buy.owner_kind == sell.owner_kind and buy.owner_id == sell.owner_id:
                break
            before = buy.quantity
            fills = self._fill_buy_listing(buy)
            if not fills:
                break
            matched.extend(fills)
            if buy.quantity == before:
                break
        return matched

    def set_paused(self, paused: bool) -> ActionResult:
        self.paused = paused
        return ActionResult(True, "paused" if paused else "resumed")

    def pass_turn(self, owner_kind: str, owner_id: str) -> ActionResult:
        """Explicit no-op action so an agent can finish the day."""
        self.get_actor(owner_kind, owner_id)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, "Passed")

    def to_public_dict(self) -> dict:
        return {
            "day": self.day,
            "time_sec": round(self.time_sec, 2),
            "tick_index": self.tick_index,
            "paused": self.paused,
            "player_company_id": self.player_company_id,
            "current_turn": self.current_turn_token(),
            "companies": [c.to_public_dict() for c in self.companies.values()],
            "market": self.market.to_public_dict(),
            "content": self.content.to_public_dict(),
            "map": self.grid.to_public_dict(),
        }
