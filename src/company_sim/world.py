"""World state + day-based agent turn loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from company_sim.actions import ActionError, ActionResult
from company_sim.actors import Actor, ActorKind, Company
from company_sim.buildings import Building
from company_sim.content import GameContent
from company_sim.items import Inventory
from company_sim.mailboxes import MailboxStore, actor_key, parse_actor_key
from company_sim.map_grid import GridMap, TileKind, generate_map
from company_sim.market import Listing, Market
from company_sim.persistence import GamePersistence, default_save_dir
from company_sim.trades import ProposalStore, TradeProposal


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
    proposals: ProposalStore = field(default_factory=ProposalStore)
    mailboxes: MailboxStore | None = None
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
            proposals=ProposalStore(),
            mailboxes=MailboxStore(root=save_root),
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
        # Generate C(n,2) mailbox files for the full cast (player + AI cos + cities)
        assert world.mailboxes is not None
        world.mailboxes.ensure_all_pairs(world.iter_all_actors())
        world.persistence.save_all(world)
        return world

    def mail(self) -> MailboxStore:
        if self.mailboxes is None:
            raise ActionError("Mailboxes not initialized")
        return self.mailboxes

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
        """Mark that this actor took an action this day; persist; maybe advance day."""
        actor = self.get_actor(kind, actor_id)
        actor.mark_acted()
        self._maybe_advance_day()
        # Always persist after a state-changing action (day advance may have
        # already saved; saving again is cheap and keeps files current).
        self.persistence.save_all(self)

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
        """Sell order: goods leave seller → market inventory; cash only on fill."""
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
        """Buy order: cash escrowed; auto-fills sells at sell.price <= buy.price."""
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

    def retract_listing(self, owner_kind: str, owner_id: str, listing_id: int) -> ActionResult:
        """
        Retract own market order.

        Sell: return remaining goods from market inventory to this owner only.
        Buy: return remaining escrowed cash to this owner.
        """
        listing = self.market.listings.get(listing_id)
        if listing is None:
            raise ActionError(f"Unknown listing #{listing_id}")
        if listing.owner_kind != owner_kind or listing.owner_id != owner_id:
            raise ActionError("Can only retract your own listings")
        actor = self.get_actor(owner_kind, owner_id)
        if listing.side == "sell":
            qty = listing.quantity
            if qty <= 0:
                self.market.remove_listing(listing_id)
                raise ActionError("Listing already empty")
            if self.market.inventory.get(listing.item_id) < qty:
                raise ActionError("Market inventory mismatch on retract")
            self.market.inventory.add(listing.item_id, -qty)
            actor.inventory.add(listing.item_id, qty)
            self.market.remove_listing(listing_id)
            self.note_actor_action(owner_kind, owner_id)
            return ActionResult(
                True,
                f"Retracted sell #{listing_id}: {qty}x {listing.item_id} returned",
                {"listing_id": listing_id, "side": "sell", "quantity": qty, "item_id": listing.item_id},
            )
        # buy order
        refund = listing.price * listing.quantity
        if refund > 0 and not self.market.escrow_take(owner_kind, owner_id, refund):
            raise ActionError("Escrow mismatch on buy retract")
        actor.cash += refund
        self.market.remove_listing(listing_id)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Retracted buy #{listing_id}: refunded {refund}",
            {"listing_id": listing_id, "side": "buy", "refund": refund},
        )

    def buy_from_market(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
    ) -> ActionResult:
        """Standard buy: take goods now from lowest-price sell listings."""
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
                afford = buyer.cash // listing.price if listing.price > 0 else 0
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
        if listing.quantity < qty:
            raise ActionError("Listing quantity mismatch")
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
            sells = [
                s
                for s in self.market.sell_listings_for(buy.item_id)
                if s.price <= buy.price
                and not (s.owner_kind == buy.owner_kind and s.owner_id == buy.owner_id)
            ]
            if not sells:
                break
            sell = sells[0]
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
            buys = [
                b
                for b in self.market.buy_listings_for(sell.item_id)
                if b.price >= sell.price
                and not (b.owner_kind == sell.owner_kind and b.owner_id == sell.owner_id)
            ]
            if not buys:
                break
            buy = buys[0]
            before = buy.quantity
            fills = self._fill_buy_listing(buy)
            if not fills:
                break
            matched.extend(fills)
            if buy.quantity == before:
                break
        return matched

    # --- Direct proposals (agent ↔ agent) --------------------------------

    def propose_sell(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        """Direct sell proposal: escrow goods; cash moves only if accepted."""
        return self._create_proposal("sell", from_kind, from_id, to, item_id, quantity, price)

    def propose_buy(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        """Direct buy proposal: escrow cash; goods move only if accepted."""
        return self._create_proposal("buy", from_kind, from_id, to, item_id, quantity, price)

    def _create_proposal(
        self,
        side: str,
        from_kind: str,
        from_id: str,
        to: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
        proposer = self.get_actor(from_kind, from_id)
        to_kind, to_id = self.resolve_counterpart(to)
        if from_kind == to_kind and from_id == to_id:
            raise ActionError("Cannot propose a trade with yourself")
        self.get_actor(to_kind, to_id)  # validate counterpart exists

        pid = self.proposals.next_id()
        if side == "sell":
            if proposer.inventory.get(item_id) < quantity:
                raise ActionError("Not enough goods to propose sell")
            proposer.inventory.add(item_id, -quantity)
            self.proposals.goods_escrow.add(item_id, quantity)
        else:
            total = price * quantity
            if proposer.cash < total:
                raise ActionError("Not enough cash to propose buy")
            proposer.cash -= total
            self.proposals.cash_escrow[pid] = total

        proposal = TradeProposal(
            id=pid,
            side=side,  # type: ignore[arg-type]
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
            item_id=item_id,
            quantity=quantity,
            price=price,
            status="open",
            day=self.day,
        )
        self.proposals.add(proposal)

        # Notify counterpart via mailbox (best-effort)
        try:
            note = (
                f"[proposal #{pid}] {side} {quantity}x {item_id} @ {price}/u "
                f"from {from_kind}:{from_id}"
            )
            self.mail().send(
                from_kind=from_kind,
                from_id=from_id,
                to_kind=to_kind,
                to_id=to_id,
                body=note,
                day=self.day,
            )
        except Exception:  # noqa: BLE001
            pass

        self.note_actor_action(from_kind, from_id)
        return ActionResult(
            True,
            f"Proposed {side} #{pid} to {to_kind}:{to_id}: {quantity}x {item_id} @ {price}",
            {"proposal": proposal.to_public_dict()},
        )

    def accept_proposal(self, owner_kind: str, owner_id: str, proposal_id: int) -> ActionResult:
        """Counterpart accepts an open proposal addressed to them."""
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise ActionError(f"Unknown proposal #{proposal_id}")
        if proposal.status != "open":
            raise ActionError(f"Proposal #{proposal_id} is {proposal.status}")
        if proposal.to_kind != owner_kind or proposal.to_id != owner_id:
            raise ActionError("Only the recipient can accept this proposal")

        proposer = self.get_actor(proposal.from_kind, proposal.from_id)
        recipient = self.get_actor(owner_kind, owner_id)
        qty = proposal.quantity
        price = proposal.price
        total = proposal.total
        item_id = proposal.item_id

        if proposal.side == "sell":
            # Proposer already escrowed goods; recipient pays cash, receives goods
            if recipient.cash < total:
                raise ActionError("Not enough cash to accept sell proposal")
            if self.proposals.goods_escrow.get(item_id) < qty:
                raise ActionError("Proposal goods escrow mismatch")
            recipient.cash -= total
            proposer.cash += total
            self.proposals.goods_escrow.add(item_id, -qty)
            recipient.inventory.add(item_id, qty)
        else:
            # Proposer escrowed cash; recipient must supply goods
            reserved = self.proposals.cash_escrow.get(proposal_id)
            if reserved is None or reserved != total:
                raise ActionError("Proposal cash escrow mismatch")
            if recipient.inventory.get(item_id) < qty:
                raise ActionError("Not enough goods to fulfill buy proposal")
            recipient.inventory.add(item_id, -qty)
            proposer.inventory.add(item_id, qty)
            recipient.cash += total
            del self.proposals.cash_escrow[proposal_id]

        proposal.status = "accepted"
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Accepted proposal #{proposal_id}",
            {"proposal": proposal.to_public_dict()},
        )

    def reject_proposal(self, owner_kind: str, owner_id: str, proposal_id: int) -> ActionResult:
        """Counterpart rejects; escrow returns to proposer."""
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise ActionError(f"Unknown proposal #{proposal_id}")
        if proposal.status != "open":
            raise ActionError(f"Proposal #{proposal_id} is {proposal.status}")
        if proposal.to_kind != owner_kind or proposal.to_id != owner_id:
            raise ActionError("Only the recipient can reject this proposal")
        self._release_proposal_escrow(proposal)
        proposal.status = "rejected"
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Rejected proposal #{proposal_id}",
            {"proposal": proposal.to_public_dict()},
        )

    def cancel_proposal(self, owner_kind: str, owner_id: str, proposal_id: int) -> ActionResult:
        """Proposer cancels; escrow returns."""
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise ActionError(f"Unknown proposal #{proposal_id}")
        if proposal.status != "open":
            raise ActionError(f"Proposal #{proposal_id} is {proposal.status}")
        if proposal.from_kind != owner_kind or proposal.from_id != owner_id:
            raise ActionError("Only the proposer can cancel this proposal")
        self._release_proposal_escrow(proposal)
        proposal.status = "cancelled"
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Cancelled proposal #{proposal_id}",
            {"proposal": proposal.to_public_dict()},
        )

    def _release_proposal_escrow(self, proposal: TradeProposal) -> None:
        proposer = self.get_actor(proposal.from_kind, proposal.from_id)
        if proposal.side == "sell":
            qty = proposal.quantity
            if self.proposals.goods_escrow.get(proposal.item_id) < qty:
                raise ActionError("Proposal goods escrow mismatch on release")
            self.proposals.goods_escrow.add(proposal.item_id, -qty)
            proposer.inventory.add(proposal.item_id, qty)
        else:
            reserved = self.proposals.cash_escrow.pop(proposal.id, None)
            if reserved is None:
                raise ActionError("Proposal cash escrow missing on release")
            proposer.cash += reserved

    # --- Conservation helpers (tests / debugging) -----------------------

    def total_item_quantity(self, item_id: str) -> int:
        """All copies of an item: actors + market sells + proposal sell escrow."""
        total = self.market.inventory.get(item_id)
        total += self.proposals.goods_escrow.get(item_id)
        for actor in self.iter_all_actors():
            total += actor.inventory.get(item_id)
        return total

    def total_cash(self) -> int:
        """All cash: actors + market buy escrow + proposal buy escrow."""
        total = sum(self.market.escrow_cash.values())
        total += sum(self.proposals.cash_escrow.values())
        for actor in self.iter_all_actors():
            total += actor.cash
        return total

    def set_paused(self, paused: bool) -> ActionResult:
        self.paused = paused
        return ActionResult(True, "paused" if paused else "resumed")

    def pass_turn(self, owner_kind: str, owner_id: str) -> ActionResult:
        """Explicit no-op action so an agent can finish the day."""
        self.get_actor(owner_kind, owner_id)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, "Passed")

    # --- Mail -----------------------------------------------------------

    def resolve_counterpart(self, to: str) -> tuple[str, str]:
        """
        Resolve a counterpart from 'kind:id', bare id, or name.
        Prefers exact kind:id, then unique id, then unique name.
        """
        to = to.strip()
        if not to:
            raise ActionError("Missing recipient")
        if ":" in to:
            kind, aid = parse_actor_key(to)
            self.get_actor(kind, aid)
            return kind, aid
        # Exact id match
        matches: list[tuple[str, str]] = []
        for a in self.iter_all_actors():
            if a.id == to:
                matches.append((a.kind, a.id))
            elif a.name.lower() == to.lower():
                matches.append((a.kind, a.id))
        # Deduplicate
        uniq = list(dict.fromkeys(matches))
        if len(uniq) == 1:
            return uniq[0]
        if not uniq:
            raise ActionError(f"Unknown recipient: {to}")
        raise ActionError(f"Ambiguous recipient '{to}': {[actor_key(k, i) for k, i in uniq]}")

    def send_message(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        body: str,
    ) -> ActionResult:
        """AGENT↔AGENT / AGENT↔USER mail. Does not mark acted (free during turn)."""
        self.get_actor(from_kind, from_id)
        to_kind, to_id = self.resolve_counterpart(to)
        if from_kind == to_kind and from_id == to_id:
            raise ActionError("Cannot message yourself")
        try:
            msg = self.mail().send(
                from_kind=from_kind,
                from_id=from_id,
                to_kind=to_kind,
                to_id=to_id,
                body=body,
                day=self.day,
            )
        except (KeyError, ValueError) as exc:
            raise ActionError(str(exc)) from exc
        # Keep other saves in sync (agent files note "my" side indirectly via mail bundle)
        self.persistence.save_all(self)
        return ActionResult(
            True,
            f"Sent to {msg.to_key}: {msg.body[:80]}",
            {"from": msg.from_key, "to": msg.to_key, "day": msg.day, "body": msg.body},
        )

    def read_mail(self, owner_kind: str, owner_id: str, with_whom: str | None = None) -> ActionResult:
        self.get_actor(owner_kind, owner_id)
        store = self.mail()
        if with_whom:
            to_kind, to_id = self.resolve_counterpart(with_whom)
            box = store.get_box(actor_key(owner_kind, owner_id), actor_key(to_kind, to_id))
            return ActionResult(True, "mail", {"mailbox": box.to_public_dict()})
        return ActionResult(
            True,
            "mail",
            {
                "contacts": store.list_contacts(owner_kind, owner_id),
                "text": store.render_for_agent(owner_kind, owner_id),
            },
        )

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
            "proposals": self.proposals.to_public_dict(),
            "mailboxes": self.mail().to_public_dict() if self.mailboxes else {"mailbox_count": 0},
            "content": self.content.to_public_dict(),
            "map": self.grid.to_public_dict(),
        }
