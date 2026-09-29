"""Government contracts: cities procure goods without using the market.

Flow:
  1. City posts a contract with required resources + quantities (visible to all companies).
  2. Companies bid a total price for fulfilling the whole basket.
  3. City awards → lowest bid wins; city cash for that bid is escrowed.
  4. Winner gathers goods, fulfills → goods transfer to city, escrowed cash → company.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ContractStatus = Literal["open", "awarded", "fulfilled", "cancelled"]


@dataclass
class ContractBid:
    company_id: str
    price: int  # total cash for the whole requirements basket
    day: int

    def to_public_dict(self) -> dict:
        return {"company_id": self.company_id, "price": self.price, "day": self.day}

    def to_text_line(self) -> str:
        return f"  bid company:{self.company_id} total={self.price} (day {self.day})"


@dataclass
class GovernmentContract:
    id: int
    city_id: str
    requirements: dict[str, int]  # item_id → qty
    status: ContractStatus = "open"
    day_created: int = 1
    bids: dict[str, ContractBid] = field(default_factory=dict)  # company_id → bid
    winner_company_id: str | None = None
    winning_price: int | None = None
    day_awarded: int | None = None
    day_fulfilled: int | None = None

    def to_public_dict(self) -> dict:
        bids = sorted(self.bids.values(), key=lambda b: (b.price, b.day, b.company_id))
        return {
            "id": self.id,
            "city_id": self.city_id,
            "requirements": dict(self.requirements),
            "status": self.status,
            "day_created": self.day_created,
            "bids": [b.to_public_dict() for b in bids],
            "winner_company_id": self.winner_company_id,
            "winning_price": self.winning_price,
            "day_awarded": self.day_awarded,
            "day_fulfilled": self.day_fulfilled,
        }

    def to_text_block(self) -> str:
        req = ", ".join(f"{q}x {i}" for i, q in sorted(self.requirements.items()))
        lines = [
            f"#{self.id} city:{self.city_id} [{self.status}] needs: {req} (day {self.day_created})",
        ]
        if self.bids:
            for b in sorted(self.bids.values(), key=lambda x: (x.price, x.day, x.company_id)):
                lines.append(b.to_text_line())
        else:
            lines.append("  (no bids yet)")
        if self.winner_company_id is not None:
            lines.append(
                f"  winner=company:{self.winner_company_id} price={self.winning_price} "
                f"awarded_day={self.day_awarded}"
            )
        return "\n".join(lines)


@dataclass
class GovernmentContractBook:
    contracts: dict[int, GovernmentContract] = field(default_factory=dict)
    # Escrowed city cash keyed by contract id (held after award until fulfill/cancel)
    escrow_cash: dict[int, int] = field(default_factory=dict)
    _next_id_value: int = 1

    def next_id(self) -> int:
        lid = self._next_id_value
        self._next_id_value += 1
        return lid

    def add(self, contract: GovernmentContract) -> GovernmentContract:
        self.contracts[contract.id] = contract
        return contract

    def get(self, contract_id: int) -> GovernmentContract | None:
        return self.contracts.get(contract_id)

    def open_contracts(self) -> list[GovernmentContract]:
        rows = [c for c in self.contracts.values() if c.status == "open"]
        rows.sort(key=lambda c: c.id)
        return rows

    def awarded_for_company(self, company_id: str) -> list[GovernmentContract]:
        rows = [
            c
            for c in self.contracts.values()
            if c.status == "awarded" and c.winner_company_id == company_id
        ]
        rows.sort(key=lambda c: c.id)
        return rows

    def for_city(self, city_id: str) -> list[GovernmentContract]:
        rows = [c for c in self.contracts.values() if c.city_id == city_id]
        rows.sort(key=lambda c: c.id)
        return rows

    def active(self) -> list[GovernmentContract]:
        rows = [c for c in self.contracts.values() if c.status in ("open", "awarded")]
        rows.sort(key=lambda c: c.id)
        return rows

    def to_public_dict(self) -> dict:
        active = self.active()
        return {
            "active_count": len(active),
            "escrow_cash": dict(self.escrow_cash),
            "contracts": [c.to_public_dict() for c in active],
            "next_id": self._next_id_value,
        }

    def to_text(self) -> str:
        active = self.active()
        lines = [
            "=== GOVERNMENT CONTRACTS ===",
            "file: government_contracts.txt",
            f"active_count: {len(active)}",
            f"escrow_cash: {self.escrow_cash or '{}'}",
            "",
            "-- open / awarded --",
        ]
        if active:
            for c in active:
                lines.append(c.to_text_block())
                lines.append("")
        else:
            lines.append("(none)")
            lines.append("")
        return "\n".join(lines)
