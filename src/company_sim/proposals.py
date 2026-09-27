"""Direct trade proposals between two agents (not the public market).

Sell proposal: proposer offers to sell qty @ price to a counterpart.
  → goods are reserved from proposer until accept / reject / cancel.

Buy proposal: proposer offers to buy qty @ price from a counterpart.
  → cash is reserved from proposer until accept / reject / cancel.

Accept moves the other side (cash or goods) and clears the reservation.
Reject/cancel returns the reservation to the proposer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProposalSide = Literal["sell", "buy"]
ProposalStatus = Literal["pending", "accepted", "rejected", "cancelled"]


@dataclass
class DirectProposal:
    id: int
    side: ProposalSide
    item_id: str
    quantity: int
    price: int  # cash per unit
    from_kind: str
    from_id: str
    to_kind: str
    to_id: str
    status: ProposalStatus = "pending"
    day_created: int = 1

    @property
    def total(self) -> int:
        return self.price * self.quantity

    @property
    def from_key(self) -> str:
        return f"{self.from_kind}:{self.from_id}"

    @property
    def to_key(self) -> str:
        return f"{self.to_kind}:{self.to_id}"

    def involves(self, kind: str, actor_id: str) -> bool:
        return (self.from_kind == kind and self.from_id == actor_id) or (
            self.to_kind == kind and self.to_id == actor_id
        )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "side": self.side,
            "item_id": self.item_id,
            "quantity": self.quantity,
            "price": self.price,
            "total": self.total,
            "from": self.from_key,
            "to": self.to_key,
            "status": self.status,
            "day_created": self.day_created,
        }

    def to_text_line(self) -> str:
        return (
            f"#{self.id} [{self.status}] {self.side} {self.quantity}x {self.item_id} "
            f"@ {self.price}/u {self.from_key} -> {self.to_key} (day {self.day_created})"
        )


@dataclass
class ProposalBook:
    """Indexed direct proposals + reserved goods/cash keyed by proposal id."""

    proposals: dict[int, DirectProposal] = field(default_factory=dict)
    # Reserved goods sitting in proposals: proposal_id → (item_id, qty)
    reserved_goods: dict[int, tuple[str, int]] = field(default_factory=dict)
    # Reserved cash: proposal_id → amount
    reserved_cash: dict[int, int] = field(default_factory=dict)
    _next_id_value: int = 1

    def next_id(self) -> int:
        lid = self._next_id_value
        self._next_id_value += 1
        return lid

    def add(self, proposal: DirectProposal) -> DirectProposal:
        self.proposals[proposal.id] = proposal
        return proposal

    def get(self, proposal_id: int) -> DirectProposal | None:
        return self.proposals.get(proposal_id)

    def pending_for(self, kind: str, actor_id: str) -> list[DirectProposal]:
        rows = [
            p
            for p in self.proposals.values()
            if p.status == "pending" and p.involves(kind, actor_id)
        ]
        rows.sort(key=lambda p: p.id)
        return rows

    def all_involving(self, kind: str, actor_id: str) -> list[DirectProposal]:
        rows = [p for p in self.proposals.values() if p.involves(kind, actor_id)]
        rows.sort(key=lambda p: p.id)
        return rows

    def to_public_dict(self) -> dict:
        pending = [p for p in self.proposals.values() if p.status == "pending"]
        pending.sort(key=lambda p: p.id)
        return {
            "pending_count": len(pending),
            "proposals": [p.to_public_dict() for p in pending],
            "next_id": self._next_id_value,
        }

    def to_text(self) -> str:
        pending = [p for p in self.proposals.values() if p.status == "pending"]
        pending.sort(key=lambda p: p.id)
        lines = [
            "=== DIRECT PROPOSALS ===",
            "file: proposals.txt",
            f"pending_count: {len(pending)}",
            "",
            "-- pending --",
        ]
        if pending:
            lines.extend(p.to_text_line() for p in pending)
        else:
            lines.append("(none)")
        lines.append("")
        return "\n".join(lines) + "\n"
