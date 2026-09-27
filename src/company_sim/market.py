"""Shared market: indexed buy/sell listings + escrow inventory.

Invariants (no duplicate goods / no phantom cash):
  - Sum of open sell-listing quantities for an item == market.inventory[item]
  - Sell: goods leave the seller immediately; cash moves only on fill
  - Buy order: cash escrowed immediately; goods move on fill
  - Retract sell: only that listing's remaining goods return to that owner
  - Retract buy: remaining escrow returns to that buyer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from company_sim.items import Inventory

OrderSide = Literal["sell", "buy"]


@dataclass
class Listing:
    """A posted buy or sell order, indexed by id."""

    id: int
    side: OrderSide
    item_id: str
    quantity: int
    price: int  # cash per unit
    owner_kind: str  # "company" | "city"
    owner_id: str

    def owned_by(self, kind: str, actor_id: str) -> bool:
        return self.owner_kind == kind and self.owner_id == actor_id

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "side": self.side,
            "item_id": self.item_id,
            "quantity": self.quantity,
            "price": self.price,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "total": self.price * self.quantity,
        }

    def to_text_line(self) -> str:
        return (
            f"#{self.id} {self.side} {self.quantity}x {self.item_id} "
            f"@ {self.price}/u by {self.owner_kind}:{self.owner_id}"
        )


@dataclass
class Market:
    inventory: Inventory = field(default_factory=Inventory)
    escrow_cash: dict[str, int] = field(default_factory=dict)  # "kind:id" → reserved cash
    listings: dict[int, Listing] = field(default_factory=dict)
    _next_id_value: int = 1

    def _actor_key(self, kind: str, actor_id: str) -> str:
        return f"{kind}:{actor_id}"

    def next_id(self) -> int:
        lid = self._next_id_value
        self._next_id_value += 1
        return lid

    def peek_next_id(self) -> int:
        return self._next_id_value

    def sell_listings_for(self, item_id: str) -> list[Listing]:
        rows = [L for L in self.listings.values() if L.side == "sell" and L.item_id == item_id]
        rows.sort(key=lambda L: (L.price, L.id))
        return rows

    def buy_listings_for(self, item_id: str) -> list[Listing]:
        rows = [L for L in self.listings.values() if L.side == "buy" and L.item_id == item_id]
        rows.sort(key=lambda L: (-L.price, L.id))
        return rows

    def add_listing(self, listing: Listing) -> Listing:
        self.listings[listing.id] = listing
        return listing

    def remove_listing(self, listing_id: int) -> Listing | None:
        return self.listings.pop(listing_id, None)

    def escrow_add(self, kind: str, actor_id: str, amount: int) -> None:
        key = self._actor_key(kind, actor_id)
        self.escrow_cash[key] = self.escrow_cash.get(key, 0) + amount

    def escrow_take(self, kind: str, actor_id: str, amount: int) -> bool:
        key = self._actor_key(kind, actor_id)
        have = self.escrow_cash.get(key, 0)
        if have < amount:
            return False
        left = have - amount
        if left == 0:
            self.escrow_cash.pop(key, None)
        else:
            self.escrow_cash[key] = left
        return True

    def sell_qty_on_book(self, item_id: str) -> int:
        return sum(L.quantity for L in self.listings.values() if L.side == "sell" and L.item_id == item_id)

    def assert_inventory_matches_sells(self) -> None:
        """Fail if pooled market inventory drifts from open sell listings."""
        items = {L.item_id for L in self.listings.values() if L.side == "sell"}
        items.update(self.inventory.as_dict().keys())
        for item_id in items:
            book = self.sell_qty_on_book(item_id)
            have = self.inventory.get(item_id)
            if book != have:
                raise RuntimeError(
                    f"Market inventory mismatch for {item_id}: listings={book} inventory={have}"
                )

    def to_public_dict(self) -> dict:
        sells = sorted(
            (L for L in self.listings.values() if L.side == "sell"),
            key=lambda L: (L.item_id, L.price, L.id),
        )
        buys = sorted(
            (L for L in self.listings.values() if L.side == "buy"),
            key=lambda L: (L.item_id, -L.price, L.id),
        )
        return {
            "inventory": self.inventory.as_dict(),
            "escrow_cash": dict(self.escrow_cash),
            "sell_listings": [L.to_public_dict() for L in sells],
            "buy_listings": [L.to_public_dict() for L in buys],
            "listing_count": len(self.listings),
            "next_listing_id": self.peek_next_id(),
        }

    def to_text(self) -> str:
        lines = [
            "=== MARKET ===",
            f"inventory: {self.inventory.as_dict() or '{}'}",
            f"escrow_cash: {self.escrow_cash or '{}'}",
            f"listing_count: {len(self.listings)}",
            f"next_listing_id: {self.peek_next_id()}",
            "",
            "-- sell listings (lowest price first per item) --",
        ]
        sells = sorted(
            (L for L in self.listings.values() if L.side == "sell"),
            key=lambda L: (L.item_id, L.price, L.id),
        )
        if sells:
            lines.extend(L.to_text_line() for L in sells)
        else:
            lines.append("(none)")
        lines.append("")
        lines.append("-- buy listings (highest price first per item) --")
        buys = sorted(
            (L for L in self.listings.values() if L.side == "buy"),
            key=lambda L: (L.item_id, -L.price, L.id),
        )
        if buys:
            lines.extend(L.to_text_line() for L in buys)
        else:
            lines.append("(none)")
        return "\n".join(lines) + "\n"
