"""World state + day-based agent turn loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from company_sim.actions import ActionError, ActionResult
from company_sim.actors import Actor, ActorKind, Company
from company_sim.buildings import Building
from company_sim.content import GameContent
from company_sim.contracts import ContractBid, GovernmentContract, GovernmentContractBook
from company_sim.items import Inventory
from company_sim.mailboxes import MailboxStore, actor_key, parse_actor_key
from company_sim.map_grid import GridMap, generate_map, place_city_seeds
from company_sim.market import Listing, Market
from company_sim.persistence import GamePersistence, default_save_dir
from company_sim.plots import SIDES
from company_sim.proposals import DirectProposal, ProposalBook


CITY_NAMES = ["Millhaven", "Northport", "Riverbend", "Oakridge", "Southgate", "Eastmere", "Westhold", "Hillford"]


@dataclass
class WorldConfig:
    map_size: int = 12  # plots per side (square map)
    tick_hz: float = 4.0
    starting_cities: int = 1
    ai_company_count: int = 2
    player_starting_cash: int = 2500
    road_build_cost: int = 50  # legacy cash cost (unused; roads cost steel)
    road_build_steel: int = 1  # placeholder: steel consumed per edge road
    min_seconds_between_turns: float = 1.5
    save_dir: str | None = None
    # Deprecated aliases (tests / older callers); folded into map_size in __post_init__
    map_width: int | None = None
    map_height: int | None = None

    def __post_init__(self) -> None:
        if self.map_width is not None or self.map_height is not None:
            w = self.map_width if self.map_width is not None else self.map_size
            h = self.map_height if self.map_height is not None else self.map_size
            self.map_size = max(int(w), int(h))
        self.map_size = int(self.map_size)

    @property
    def map_w(self) -> int:
        return self.map_size

    @property
    def map_h(self) -> int:
        return self.map_size


def _starter_inventory() -> Inventory:
    return Inventory({"iron": 20, "coal": 20, "energy": 20, "steel": 0})


@dataclass
class World:
    config: WorldConfig
    grid: GridMap
    content: GameContent
    market: Market = field(default_factory=Market)
    proposals: ProposalBook = field(default_factory=ProposalBook)
    gov_contracts: GovernmentContractBook = field(default_factory=GovernmentContractBook)
    mailboxes: MailboxStore | None = None
    companies: dict[str, Company] = field(default_factory=dict)
    player_company_id: str = "player"
    day: int = 1
    time_sec: float = 0.0
    paused: bool = False
    tick_index: int = 0
    turn_index: int = 0
    persistence: GamePersistence = field(default_factory=GamePersistence)
    started: bool = True

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
        if config.map_size < 2:
            raise ActionError("map_size must be at least 2")
        if config.starting_cities < 1:
            raise ActionError("Need at least one city")
        if config.ai_company_count < 0:
            raise ActionError("ai_company_count cannot be negative")

        content = GameContent.load()
        centers = place_city_seeds(config.map_size, config.starting_cities)
        seeds = []
        for i, (cx, cy) in enumerate(centers):
            cid = f"city_{chr(ord('a') + i)}" if i < 26 else f"city_{i+1}"
            name = CITY_NAMES[i % len(CITY_NAMES)]
            if i >= len(CITY_NAMES):
                name = f"{name} {i+1}"
            seeds.append((cid, name, cx, cy, 1000 + i * 50))

        grid = generate_map(config.map_size, city_seeds=seeds)
        save_root = Path(config.save_dir) if config.save_dir else default_save_dir()
        world = cls(
            config=config,
            grid=grid,
            content=content,
            market=Market(),
            proposals=ProposalBook(),
            gov_contracts=GovernmentContractBook(),
            mailboxes=MailboxStore(root=save_root),
            persistence=GamePersistence(save_root),
            started=True,
        )

        # Cities own every plot in their territory
        for tile in grid.tiles:
            if tile.plot and tile.city_id:
                tile.plot.claim("city", tile.city_id)

        for city in grid.cities.values():
            city.inventory = Inventory({"iron": 15, "coal": 15, "energy": 15, "steel": 0})

        # Player + AI companies start with NO plots
        player = Company(
            id="player",
            name="Player Co",
            is_player=True,
            cash=config.player_starting_cash,
            inventory=_starter_inventory(),
        )
        world.companies[player.id] = player
        world.player_company_id = player.id

        for i in range(config.ai_company_count):
            cid = f"ai_{i+1}"
            world.companies[cid] = Company(
                id=cid,
                name=f"Rival {i+1}",
                is_player=False,
                cash=1500,
                inventory=Inventory({"iron": 10, "coal": 10, "energy": 10, "steel": 0}),
            )

        world._seed_market()
        assert world.mailboxes is not None
        world.mailboxes.ensure_all_pairs(world.iter_all_actors())
        world.persistence.save_all(world)
        return world

    def mail(self) -> MailboxStore:
        if self.mailboxes is None:
            raise ActionError("Mailboxes not initialized")
        return self.mailboxes

    def _seed_market(self) -> None:
        for company in self.companies.values():
            if company.is_player:
                continue
            for item_id, qty, price in (("iron", 2, 9), ("coal", 2, 7)):
                if company.inventory.get(item_id) < qty:
                    continue
                company.inventory.add(item_id, -qty)
                self.market.inventory.add(item_id, qty)
                lid = self.market.next_id()
                self.market.add_listing(
                    Listing(
                        id=lid,
                        side="sell",
                        item_id=item_id,
                        quantity=qty,
                        price=price,
                        owner_kind="company",
                        owner_id=company.id,
                    )
                )

    def _require_company(self, kind: str, actor_id: str) -> Company:
        if kind != "company":
            raise ActionError("Only companies can use the market / goods trade actions")
        actor = self.get_actor("company", actor_id)
        assert isinstance(actor, Company)
        return actor

    def _require_city(self, kind: str, actor_id: str):
        if kind != "city":
            raise ActionError("Only cities can post or award government contracts")
        return self.get_actor("city", actor_id)

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
            if t.plot and t.plot.owner_kind == kind and t.plot.owner_id == actor_id
        ]

    def tick(self, dt: float) -> None:
        if self.paused:
            return
        self.time_sec += dt
        self.tick_index += 1

    def note_actor_action(self, kind: str, actor_id: str) -> None:
        actor = self.get_actor(kind, actor_id)
        actor.mark_acted()
        self._maybe_advance_day()
        self.persistence.save_all(self)

    def _maybe_advance_day(self) -> None:
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

    # --- Core land actions ----------------------------------------------

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
        if not tile.plot:
            raise ActionError("Not a plot")
        if not tile.plot.owned_by(owner_kind, owner_id):
            raise ActionError("You do not own this plot")
        if tile.plot.building is not None:
            raise ActionError("Plot already has a building")
        if tile.plot.reserved_proposal_id is not None:
            raise ActionError("Plot is reserved by a pending proposal")
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
        if not tile.plot or not tile.plot.building:
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
        actor = self.get_actor(owner_kind, owner_id)
        tile = self.grid.get(x, y)
        if not tile.plot or not tile.plot.building:
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
        bonus = self.grid.production_bonus_at(x, y)
        actor.inventory.produce(method.outputs)
        if bonus > 1.0 and int(bonus) > 1:
            for _ in range(int(bonus) - 1):
                actor.inventory.produce(method.outputs)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Produced via {method.id} at ({x},{y})",
            {"inputs": method.inputs, "outputs": method.outputs, "bonus": bonus},
        )

    def build_road(self, actor_kind: str, actor_id: str, x: int, y: int, side: str) -> ActionResult:
        """Build a road on one side (N/E/S/W) of an owned plot — this plot only.

        Placeholder cost: consumes road_build_steel steel from the owner's inventory
        (goods are deleted / removed from stock).
        """
        actor = self.get_actor(actor_kind, actor_id)
        side = side.upper()
        if side not in SIDES:
            raise ActionError(f"Invalid side {side}; use N/E/S/W")
        tile = self.grid.get(x, y)
        if not tile.plot:
            raise ActionError("Not a plot")
        if not tile.plot.owned_by(actor_kind, actor_id):
            raise ActionError("You must own the plot to build a road on its edge")
        steel_cost = int(self.config.road_build_steel)
        if steel_cost < 0:
            raise ActionError("Invalid road steel cost")
        if actor.inventory.get("steel") < steel_cost:
            raise ActionError(f"Need {steel_cost} steel to build a road (have {actor.inventory.get('steel')})")
        try:
            self.grid.build_edge_road(x, y, side)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        # Consume / delete construction goods
        if steel_cost:
            actor.inventory.add("steel", -steel_cost)
        self.note_actor_action(actor_kind, actor_id)
        return ActionResult(
            True,
            f"Built road on {side} side of ({x},{y}) (−{steel_cost} steel)",
            {"steel_cost": steel_cost, "side": side, "x": x, "y": y},
        )

    def city_build_road(self, city_id: str, x: int, y: int, side: str) -> ActionResult:
        return self.build_road("city", city_id, x, y, side)

    def company_build_road(self, company_id: str, x: int, y: int, side: str) -> ActionResult:
        return self.build_road("company", company_id, x, y, side)

    def merge_plots(self, owner_kind: str, owner_id: str, x1: int, y1: int, x2: int, y2: int) -> ActionResult:
        """Combine two adjacent plots (flag only). Forbidden if a road is between them."""
        self.get_actor(owner_kind, owner_id)
        try:
            self.grid.combine_plots(x1, y1, x2, y2, owner_kind, owner_id)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        size = self.grid.group_size(x1, y1)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Combined plots ({x1},{y1})+({x2},{y2}) — group size {size}",
            {"size": size, "x1": x1, "y1": y1, "x2": x2, "y2": y2},
        )


    # --- Market (companies only) ----------------------------------------

    def post_sell(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        """Goods leave seller → market inventory + indexed sell listing. Cash later."""
        actor = self._require_company(owner_kind, owner_id)
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
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
        self.market.assert_inventory_matches_sells()
        self.note_actor_action(owner_kind, owner_id)
        remaining = listing.quantity if listing.id in self.market.listings else 0
        return ActionResult(
            True,
            f"Posted sell #{lid}: {quantity}x {item_id} @ {price}"
            + (f" ({remaining} left on book)" if matched else ""),
            {"listing_id": lid, "matched": matched, "remaining": remaining},
        )

    def retract_sell(self, owner_kind: str, owner_id: str, listing_id: int) -> ActionResult:
        """Return remaining goods from this sell listing only to its owner."""
        self._require_company(owner_kind, owner_id)
        listing = self.market.listings.get(listing_id)
        if listing is None:
            raise ActionError(f"Unknown listing #{listing_id}")
        if listing.side != "sell":
            raise ActionError("Not a sell listing (use retract_buy)")
        if not listing.owned_by(owner_kind, owner_id):
            raise ActionError("You do not own this sell listing")
        qty = listing.quantity
        item_id = listing.item_id
        if self.market.inventory.get(item_id) < qty:
            raise ActionError("Market inventory mismatch on retract")
        self.market.inventory.add(item_id, -qty)
        actor = self.get_actor(owner_kind, owner_id)
        actor.inventory.add(item_id, qty)
        self.market.remove_listing(listing_id)
        self.market.assert_inventory_matches_sells()
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Retracted sell #{listing_id}: returned {qty}x {item_id}",
            {"listing_id": listing_id, "item_id": item_id, "quantity": qty},
        )

    def post_buy(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        """Cash escrowed. Auto-fills when a sell appears at price <= this buy price."""
        actor = self._require_company(owner_kind, owner_id)
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
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
        self.market.assert_inventory_matches_sells()
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Posted buy #{lid}: {quantity}x {item_id} @ {price}",
            {"listing_id": lid, "filled": filled},
        )

    def retract_buy(self, owner_kind: str, owner_id: str, listing_id: int) -> ActionResult:
        """Refund remaining escrow for this buy listing only."""
        self._require_company(owner_kind, owner_id)
        listing = self.market.listings.get(listing_id)
        if listing is None:
            raise ActionError(f"Unknown listing #{listing_id}")
        if listing.side != "buy":
            raise ActionError("Not a buy listing (use retract_sell)")
        if not listing.owned_by(owner_kind, owner_id):
            raise ActionError("You do not own this buy listing")
        refund = listing.price * listing.quantity
        if not self.market.escrow_take(owner_kind, owner_id, refund):
            raise ActionError("Escrow mismatch on retract")
        actor = self.get_actor(owner_kind, owner_id)
        actor.cash += refund
        self.market.remove_listing(listing_id)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Retracted buy #{listing_id}: refunded {refund}",
            {"listing_id": listing_id, "refund": refund},
        )

    def buy_from_market(
        self,
        owner_kind: str,
        owner_id: str,
        item_id: str,
        quantity: int,
    ) -> ActionResult:
        """Standard buy: take lowest-price sell listings now."""
        buyer = self._require_company(owner_kind, owner_id)
        if quantity <= 0:
            raise ActionError("Invalid quantity")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
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
        self.market.assert_inventory_matches_sells()
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"Bought {got}x {item_id} for {spent}",
            {"got": got, "spent": spent, "fills": fills},
        )

    def _transfer_sell_to_buyer(self, listing: Listing, qty: int, buyer: Actor) -> None:
        cost = qty * listing.price
        if qty <= 0:
            raise ActionError("Invalid transfer qty")
        if buyer.cash < cost:
            raise ActionError("Not enough cash")
        if listing.quantity < qty:
            raise ActionError("Listing quantity too low")
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
        """Fill buy order from sells at price <= buy.price (cheapest first)."""
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
        """When a sell is posted, fill buy orders priced at sell.price or higher."""
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

    # --- Direct proposals: goods + plots (accept / reject) --------------

    def propose_sell(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        """Direct goods sell: reserve goods until accept/reject."""
        proposer = self._require_company(from_kind, from_id)
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
        to_kind, to_id = self.resolve_counterpart(to)
        if to_kind != "company":
            raise ActionError("Cities do not use goods trade — use government contracts")
        if from_kind == to_kind and from_id == to_id:
            raise ActionError("Cannot propose to yourself")
        self.get_actor(to_kind, to_id)
        if proposer.inventory.get(item_id) < quantity:
            raise ActionError("Not enough goods to propose sell")
        proposer.inventory.add(item_id, -quantity)
        pid = self.proposals.next_id()
        prop = DirectProposal(
            id=pid,
            proposal_type="goods_sell",
            item_id=item_id,
            quantity=quantity,
            price=price,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
            day_created=self.day,
        )
        self.proposals.add(prop)
        self.proposals.reserved_goods[pid] = (item_id, quantity)
        try:
            self.send_message(
                from_kind,
                from_id,
                f"{to_kind}:{to_id}",
                f"[PROPOSAL #{pid} goods_sell] {quantity}x {item_id} @ {price}/u — accept or reject",
            )
        except ActionError:
            pass
        self.note_actor_action(from_kind, from_id)
        return ActionResult(
            True,
            f"Sell proposal #{pid} to {to_kind}:{to_id}: {quantity}x {item_id} @ {price}",
            prop.to_public_dict(),
        )

    def propose_buy(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        item_id: str,
        quantity: int,
        price: int,
    ) -> ActionResult:
        """Direct goods buy: reserve cash until accept/reject."""
        proposer = self._require_company(from_kind, from_id)
        if quantity <= 0 or price < 0:
            raise ActionError("Invalid quantity/price")
        if not self.items.has(item_id):
            raise ActionError(f"Unknown item: {item_id}")
        to_kind, to_id = self.resolve_counterpart(to)
        if to_kind != "company":
            raise ActionError("Cities do not use goods trade — use government contracts")
        if from_kind == to_kind and from_id == to_id:
            raise ActionError("Cannot propose to yourself")
        self.get_actor(to_kind, to_id)
        total = price * quantity
        if proposer.cash < total:
            raise ActionError("Not enough cash to propose buy")
        proposer.cash -= total
        pid = self.proposals.next_id()
        prop = DirectProposal(
            id=pid,
            proposal_type="goods_buy",
            item_id=item_id,
            quantity=quantity,
            price=price,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
            day_created=self.day,
        )
        self.proposals.add(prop)
        self.proposals.reserved_cash[pid] = total
        try:
            self.send_message(
                from_kind,
                from_id,
                f"{to_kind}:{to_id}",
                f"[PROPOSAL #{pid} goods_buy] {quantity}x {item_id} @ {price}/u — accept or reject",
            )
        except ActionError:
            pass
        self.note_actor_action(from_kind, from_id)
        return ActionResult(
            True,
            f"Buy proposal #{pid} to {to_kind}:{to_id}: {quantity}x {item_id} @ {price}",
            prop.to_public_dict(),
        )

    def propose_plot_sell(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        x: int,
        y: int,
        price: int,
    ) -> ActionResult:
        """Owner offers to sell an owned plot at a total price. Plot is reserved."""
        self.get_actor(from_kind, from_id)
        if price < 0:
            raise ActionError("Invalid price")
        if not self.grid.in_bounds(x, y):
            raise ActionError("Out of bounds")
        tile = self.grid.get(x, y)
        if not tile.plot:
            raise ActionError("Not a plot")
        if not tile.plot.owned_by(from_kind, from_id):
            raise ActionError("You do not own this plot")
        if tile.plot.reserved_proposal_id is not None:
            raise ActionError("Plot is already reserved by a pending proposal")
        to_kind, to_id = self.resolve_counterpart(to)
        if from_kind == to_kind and from_id == to_id:
            raise ActionError("Cannot propose to yourself")
        self.get_actor(to_kind, to_id)
        pid = self.proposals.next_id()
        prop = DirectProposal(
            id=pid,
            proposal_type="plot_sell",
            price=price,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
            day_created=self.day,
            plot_x=x,
            plot_y=y,
            plot_id=tile.plot.id,
        )
        tile.plot.reserved_proposal_id = pid
        self.proposals.add(prop)
        try:
            self.send_message(
                from_kind,
                from_id,
                f"{to_kind}:{to_id}",
                f"[PROPOSAL #{pid} plot_sell] plot ({x},{y}) for {price} — accept or reject",
            )
        except ActionError:
            pass
        self.note_actor_action(from_kind, from_id)
        return ActionResult(
            True,
            f"Plot sell proposal #{pid}: ({x},{y}) @ {price} → {to_kind}:{to_id}",
            prop.to_public_dict(),
        )

    def propose_plot_buy(
        self,
        from_kind: str,
        from_id: str,
        to: str,
        x: int,
        y: int,
        price: int,
    ) -> ActionResult:
        """Buyer escrows cash and offers to buy a specific plot from its owner."""
        buyer = self.get_actor(from_kind, from_id)
        if price < 0:
            raise ActionError("Invalid price")
        if not self.grid.in_bounds(x, y):
            raise ActionError("Out of bounds")
        tile = self.grid.get(x, y)
        if not tile.plot:
            raise ActionError("Not a plot")
        if not tile.plot.is_owned:
            raise ActionError("Plot has no owner")
        if tile.plot.owned_by(from_kind, from_id):
            raise ActionError("You already own this plot")
        if tile.plot.reserved_proposal_id is not None:
            raise ActionError("Plot is already reserved by a pending proposal")
        to_kind, to_id = self.resolve_counterpart(to)
        if from_kind == to_kind and from_id == to_id:
            raise ActionError("Cannot propose to yourself")
        # Must address the current owner
        if not tile.plot.owned_by(to_kind, to_id):
            raise ActionError(
                f"Recipient is not the owner (owner={tile.plot.owner_kind}:{tile.plot.owner_id})"
            )
        if buyer.cash < price:
            raise ActionError("Not enough cash to propose plot buy")
        buyer.cash -= price
        pid = self.proposals.next_id()
        prop = DirectProposal(
            id=pid,
            proposal_type="plot_buy",
            price=price,
            from_kind=from_kind,
            from_id=from_id,
            to_kind=to_kind,
            to_id=to_id,
            day_created=self.day,
            plot_x=x,
            plot_y=y,
            plot_id=tile.plot.id,
        )
        tile.plot.reserved_proposal_id = pid
        self.proposals.add(prop)
        self.proposals.reserved_cash[pid] = price
        try:
            self.send_message(
                from_kind,
                from_id,
                f"{to_kind}:{to_id}",
                f"[PROPOSAL #{pid} plot_buy] offer {price} for plot ({x},{y}) — accept or reject",
            )
        except ActionError:
            pass
        self.note_actor_action(from_kind, from_id)
        return ActionResult(
            True,
            f"Plot buy proposal #{pid}: ({x},{y}) @ {price} → {to_kind}:{to_id}",
            prop.to_public_dict(),
        )

    def accept_proposal(self, owner_kind: str, owner_id: str, proposal_id: int) -> ActionResult:
        """Recipient accepts a pending direct proposal (goods or plot)."""
        self.get_actor(owner_kind, owner_id)
        prop = self.proposals.get(proposal_id)
        if prop is None:
            raise ActionError(f"Unknown proposal #{proposal_id}")
        if prop.status != "pending":
            raise ActionError(f"Proposal #{proposal_id} is {prop.status}")
        if not (prop.to_kind == owner_kind and prop.to_id == owner_id):
            raise ActionError("Only the recipient can accept this proposal")

        if prop.proposal_type in ("goods_sell", "goods_buy"):
            if owner_kind != "company":
                raise ActionError("Only companies accept goods proposals")
            self._accept_goods_proposal(prop, owner_kind, owner_id)
        elif prop.proposal_type in ("plot_sell", "plot_buy"):
            self._accept_plot_proposal(prop, owner_kind, owner_id)
        else:
            raise ActionError(f"Unknown proposal type {prop.proposal_type}")

        prop.status = "accepted"
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, f"Accepted proposal #{proposal_id}", prop.to_public_dict())

    def reject_proposal(self, owner_kind: str, owner_id: str, proposal_id: int) -> ActionResult:
        """Recipient rejects or proposer cancels a pending proposal."""
        self.get_actor(owner_kind, owner_id)
        prop = self.proposals.get(proposal_id)
        if prop is None:
            raise ActionError(f"Unknown proposal #{proposal_id}")
        if prop.status != "pending":
            raise ActionError(f"Proposal #{proposal_id} is {prop.status}")
        is_recipient = prop.to_kind == owner_kind and prop.to_id == owner_id
        is_proposer = prop.from_kind == owner_kind and prop.from_id == owner_id
        if not (is_recipient or is_proposer):
            raise ActionError("Not a party to this proposal")
        self._release_proposal_reservation(prop)
        prop.status = "cancelled" if is_proposer else "rejected"
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(
            True,
            f"{prop.status.capitalize()} proposal #{proposal_id}",
            prop.to_public_dict(),
        )

    def _accept_goods_proposal(self, prop: DirectProposal, owner_kind: str, owner_id: str) -> None:
        counterpart = self.get_actor(owner_kind, owner_id)
        proposer = self.get_actor(prop.from_kind, prop.from_id)
        if prop.proposal_type == "goods_sell":
            total = prop.total
            if counterpart.cash < total:
                raise ActionError("Not enough cash to accept sell proposal")
            reserved = self.proposals.reserved_goods.pop(prop.id, None)
            if reserved != (prop.item_id, prop.quantity):
                raise ActionError("Reserved goods missing for proposal")
            counterpart.cash -= total
            proposer.cash += total
            counterpart.inventory.add(prop.item_id, prop.quantity)
        else:  # goods_buy
            if counterpart.inventory.get(prop.item_id) < prop.quantity:
                raise ActionError("Not enough goods to accept buy proposal")
            reserved_cash = self.proposals.reserved_cash.pop(prop.id, None)
            if reserved_cash != prop.total:
                raise ActionError("Reserved cash missing for proposal")
            counterpart.inventory.add(prop.item_id, -prop.quantity)
            proposer.inventory.add(prop.item_id, prop.quantity)
            counterpart.cash += prop.total

    def _accept_plot_proposal(self, prop: DirectProposal, owner_kind: str, owner_id: str) -> None:
        if prop.plot_x is None or prop.plot_y is None:
            raise ActionError("Proposal missing plot coordinates")
        x, y = prop.plot_x, prop.plot_y
        tile = self.grid.get(x, y)
        if not tile.plot or tile.plot.id != prop.plot_id:
            raise ActionError("Plot no longer matches proposal")
        if tile.plot.reserved_proposal_id != prop.id:
            raise ActionError("Plot reservation mismatch")

        if prop.proposal_type == "plot_sell":
            # Recipient (buyer) pays; proposer is seller/owner
            if not tile.plot.owned_by(prop.from_kind, prop.from_id):
                raise ActionError("Seller no longer owns the plot")
            buyer = self.get_actor(owner_kind, owner_id)
            seller = self.get_actor(prop.from_kind, prop.from_id)
            if buyer.cash < prop.price:
                raise ActionError("Not enough cash to accept plot sell")
            buyer.cash -= prop.price
            seller.cash += prop.price
            self.grid.clear_combines_at(x, y)
            tile.plot.claim(owner_kind, owner_id)
            if tile.plot.building:
                tile.plot.building.owner_kind = owner_kind
                tile.plot.building.owner_id = owner_id
            tile.plot.reserved_proposal_id = None
        else:  # plot_buy — recipient is owner/seller; proposer is buyer with escrowed cash
            if not tile.plot.owned_by(owner_kind, owner_id):
                raise ActionError("You no longer own this plot")
            reserved_cash = self.proposals.reserved_cash.pop(prop.id, None)
            if reserved_cash != prop.price:
                raise ActionError("Reserved cash missing for plot proposal")
            seller = self.get_actor(owner_kind, owner_id)
            buyer = self.get_actor(prop.from_kind, prop.from_id)
            seller.cash += prop.price
            self.grid.clear_combines_at(x, y)
            tile.plot.claim(prop.from_kind, prop.from_id)
            if tile.plot.building:
                tile.plot.building.owner_kind = prop.from_kind
                tile.plot.building.owner_id = prop.from_id
            tile.plot.reserved_proposal_id = None

    def _release_proposal_reservation(self, prop: DirectProposal) -> None:
        proposer = self.get_actor(prop.from_kind, prop.from_id)
        if prop.proposal_type == "goods_sell":
            reserved = self.proposals.reserved_goods.pop(prop.id, None)
            if reserved:
                item_id, qty = reserved
                proposer.inventory.add(item_id, qty)
        elif prop.proposal_type in ("goods_buy", "plot_buy"):
            reserved_cash = self.proposals.reserved_cash.pop(prop.id, None)
            if reserved_cash:
                proposer.cash += reserved_cash
        if prop.proposal_type in ("plot_sell", "plot_buy") and prop.plot_x is not None:
            tile = self.grid.get(prop.plot_x, prop.plot_y)
            if tile.plot and tile.plot.reserved_proposal_id == prop.id:
                tile.plot.reserved_proposal_id = None

    def list_proposals(self, owner_kind: str, owner_id: str) -> ActionResult:
        self.get_actor(owner_kind, owner_id)
        rows = self.proposals.pending_for(owner_kind, owner_id)
        return ActionResult(
            True,
            "proposals",
            {"proposals": [p.to_public_dict() for p in rows]},
        )

    # --- Government contracts (CITY procurement) ------------------------

    def post_government_contract(
        self,
        city_kind: str,
        city_id: str,
        requirements: dict[str, int],
    ) -> ActionResult:
        """City posts a public procurement need; all companies may bid."""
        self._require_city(city_kind, city_id)
        if not requirements:
            raise ActionError("Requirements cannot be empty")
        cleaned: dict[str, int] = {}
        for item_id, qty in requirements.items():
            q = int(qty)
            if q <= 0:
                raise ActionError(f"Invalid quantity for {item_id}")
            if not self.items.has(item_id):
                raise ActionError(f"Unknown item: {item_id}")
            cleaned[str(item_id)] = q
        cid = self.gov_contracts.next_id()
        contract = GovernmentContract(
            id=cid,
            city_id=city_id,
            requirements=cleaned,
            status="open",
            day_created=self.day,
        )
        self.gov_contracts.add(contract)
        # Notify all companies via mail
        for company in self.companies.values():
            try:
                req = ", ".join(f"{q}x {i}" for i, q in sorted(cleaned.items()))
                self.send_message(
                    "city",
                    city_id,
                    f"company:{company.id}",
                    f"[GOV CONTRACT #{cid}] needs {req}. Bid with bid_government_contract.",
                )
            except ActionError:
                pass
        self.note_actor_action("city", city_id)
        return ActionResult(True, f"Posted government contract #{cid}", contract.to_public_dict())

    def bid_government_contract(
        self,
        company_kind: str,
        company_id: str,
        contract_id: int,
        price: int,
    ) -> ActionResult:
        """Company offers a total price to fulfill the city's basket."""
        self._require_company(company_kind, company_id)
        if price < 0:
            raise ActionError("Invalid bid price")
        contract = self.gov_contracts.get(contract_id)
        if contract is None:
            raise ActionError(f"Unknown contract #{contract_id}")
        if contract.status != "open":
            raise ActionError(f"Contract #{contract_id} is {contract.status}, not open for bids")
        bid = ContractBid(company_id=company_id, price=int(price), day=self.day)
        contract.bids[company_id] = bid  # latest bid from this company replaces prior
        self.note_actor_action("company", company_id)
        return ActionResult(
            True,
            f"Bid {price} on government contract #{contract_id}",
            {"contract_id": contract_id, "bid": bid.to_public_dict()},
        )

    def award_government_contract(
        self,
        city_kind: str,
        city_id: str,
        contract_id: int,
    ) -> ActionResult:
        """City closes bidding; lowest price wins; city cash for that price is escrowed."""
        city = self._require_city(city_kind, city_id)
        contract = self.gov_contracts.get(contract_id)
        if contract is None:
            raise ActionError(f"Unknown contract #{contract_id}")
        if contract.city_id != city_id:
            raise ActionError("Not your government contract")
        if contract.status != "open":
            raise ActionError(f"Contract #{contract_id} is {contract.status}")
        if not contract.bids:
            raise ActionError("No bids to award")
        winner = min(contract.bids.values(), key=lambda b: (b.price, b.day, b.company_id))
        if city.cash < winner.price:
            raise ActionError("City cannot afford the winning bid")
        city.cash -= winner.price
        self.gov_contracts.escrow_cash[contract.id] = winner.price
        contract.status = "awarded"
        contract.winner_company_id = winner.company_id
        contract.winning_price = winner.price
        contract.day_awarded = self.day
        try:
            self.send_message(
                "city",
                city_id,
                f"company:{winner.company_id}",
                f"[GOV CONTRACT #{contract_id} AWARDED] You won at {winner.price}. "
                f"Deliver {contract.requirements} via fulfill_government_contract.",
            )
        except ActionError:
            pass
        self.note_actor_action("city", city_id)
        return ActionResult(
            True,
            f"Awarded contract #{contract_id} to company:{winner.company_id} @ {winner.price}",
            contract.to_public_dict(),
        )

    def fulfill_government_contract(
        self,
        company_kind: str,
        company_id: str,
        contract_id: int,
    ) -> ActionResult:
        """Winner transfers all required goods to the city; escrowed cash pays the company."""
        company = self._require_company(company_kind, company_id)
        contract = self.gov_contracts.get(contract_id)
        if contract is None:
            raise ActionError(f"Unknown contract #{contract_id}")
        if contract.status != "awarded":
            raise ActionError(f"Contract #{contract_id} is {contract.status}")
        if contract.winner_company_id != company_id:
            raise ActionError("You are not the awarded company for this contract")
        # Must hold every required resource
        missing = {
            item: need - company.inventory.get(item)
            for item, need in contract.requirements.items()
            if company.inventory.get(item) < need
        }
        if missing:
            raise ActionError(f"Missing resources to fulfill: {missing}")
        city = self.get_actor("city", contract.city_id)
        price = contract.winning_price
        if price is None:
            raise ActionError("Contract has no winning price")
        escrowed = self.gov_contracts.escrow_cash.get(contract.id)
        if escrowed != price:
            raise ActionError("Contract escrow mismatch")
        # Transfer goods cityward
        for item_id, qty in contract.requirements.items():
            company.inventory.add(item_id, -qty)
            city.inventory.add(item_id, qty)
        # Pay company from escrow
        del self.gov_contracts.escrow_cash[contract.id]
        company.cash += price
        contract.status = "fulfilled"
        contract.day_fulfilled = self.day
        self.note_actor_action("company", company_id)
        return ActionResult(
            True,
            f"Fulfilled government contract #{contract_id}; received {price}",
            contract.to_public_dict(),
        )

    def cancel_government_contract(
        self,
        city_kind: str,
        city_id: str,
        contract_id: int,
    ) -> ActionResult:
        """City cancels an open or awarded (unfulfilled) contract; refund escrow if any."""
        city = self._require_city(city_kind, city_id)
        contract = self.gov_contracts.get(contract_id)
        if contract is None:
            raise ActionError(f"Unknown contract #{contract_id}")
        if contract.city_id != city_id:
            raise ActionError("Not your government contract")
        if contract.status not in ("open", "awarded"):
            raise ActionError(f"Cannot cancel contract in status {contract.status}")
        if contract.id in self.gov_contracts.escrow_cash:
            city.cash += self.gov_contracts.escrow_cash.pop(contract.id)
        contract.status = "cancelled"
        self.note_actor_action("city", city_id)
        return ActionResult(True, f"Cancelled government contract #{contract_id}", contract.to_public_dict())

    def list_government_contracts(
        self,
        kind: str,
        actor_id: str,
    ) -> ActionResult:
        self.get_actor(kind, actor_id)
        return ActionResult(True, "government_contracts", self.gov_contracts.to_public_dict())

    def set_paused(self, paused: bool) -> ActionResult:
        self.paused = paused
        return ActionResult(True, "paused" if paused else "resumed")

    def pass_turn(self, owner_kind: str, owner_id: str) -> ActionResult:
        self.get_actor(owner_kind, owner_id)
        self.note_actor_action(owner_kind, owner_id)
        return ActionResult(True, "Passed")

    # --- Mail -----------------------------------------------------------

    def resolve_counterpart(self, to: str) -> tuple[str, str]:
        to = to.strip()
        if not to:
            raise ActionError("Missing recipient")
        if ":" in to:
            kind, aid = parse_actor_key(to)
            self.get_actor(kind, aid)
            return kind, aid
        matches: list[tuple[str, str]] = []
        for a in self.iter_all_actors():
            if a.id == to:
                matches.append((a.kind, a.id))
            elif a.name.lower() == to.lower():
                matches.append((a.kind, a.id))
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
            "started": self.started,
            "day": self.day,
            "time_sec": round(self.time_sec, 2),
            "tick_index": self.tick_index,
            "paused": self.paused,
            "player_company_id": self.player_company_id,
            "current_turn": self.current_turn_token(),
            "config": {
                "map_size": self.config.map_size,
                "starting_cities": self.config.starting_cities,
                "ai_company_count": self.config.ai_company_count,
                "road_build_cost": self.config.road_build_cost,
                "road_build_steel": self.config.road_build_steel,
            },
            "companies": [c.to_public_dict() for c in self.companies.values()],
            "market": self.market.to_public_dict(),
            "proposals": self.proposals.to_public_dict(),
            "government_contracts": self.gov_contracts.to_public_dict(),
            "mailboxes": self.mail().to_public_dict() if self.mailboxes else {"mailbox_count": 0},
            "content": self.content.to_public_dict(),
            "map": self.grid.to_public_dict(),
        }
