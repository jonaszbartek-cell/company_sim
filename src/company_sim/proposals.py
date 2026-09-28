"""Direct proposals between agents: goods and plots.

Goods (company↔company):
  sell — reserve goods; buy — reserve cash.

Plots (company or city):
  plot_sell — seller locks plot, offers to buyer at a total price
  plot_buy  — buyer escrows cash, offers to buy a specific plot from owner

Accept / reject / cancel clear reservations and either transfer or unlock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProposalType = Literal["goods_sell", "goods_buy", "plot_sell", "plot_buy"]
ProposalStatus = Literal["pending", "accepted", "rejected", "cancelled"]


@dataclass
class DirectProposal:
    id: int
    proposal_type: ProposalType
    from_kind: str
    from_id: str
    to_kind: str
    to_id: str
    price: int  # per-unit for goods; total for plots
    status: ProposalStatus = "pending"
    day_created: int = 1
    # goods
    item_id: str | None = None
    quantity: int = 0
    # plots
    plot_x: int | None = None
    plot_y: int | None = None
    plot_id: str | None = None

    @property
    def side(self) -> str:
        """Legacy alias used by older UI: sell/buy."""
        if self.proposal_type in ("goods_sell", "plot_sell"):
            return "sell"
        return "buy"

    @property
    def total(self) -> int:
        if self.proposal_type in ("goods_sell", "goods_buy"):
            return self.price * self.quantity
        return self.price

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
            "proposal_type": self.proposal_type,
            "side": self.side,
            "item_id": self.item_id,
            "quantity": self.quantity,
            "price": self.price,
            "total": self.total,
            "plot_x": self.plot_x,
            "plot_y": self.plot_y,
            "plot_id": self.plot_id,
            "from": self.from_key,
            "to": self.to_key,
            "status": self.status,
            "day_created": self.day_created,
        }

    def to_text_line(self) -> str:
        if self.proposal_type.startswith("plot_"):
            return (
                f"#{self.id} [{self.status}] {self.proposal_type} "
                f"plot=({self.plot_x},{self.plot_y}) id={self.plot_id} "
                f"@ {self.price} {self.from_key} -> {self.to_key} (day {self.day_created})"
            )
        return (
            f"#{self.id} [{self.status}] {self.proposal_type} "
            f"{self.quantity}x {self.item_id} @ {self.price}/u "
            f"{self.from_key} -> {self.to_key} (day {self.day_created})"
        )


@dataclass
class ProposalBook:
    proposals: dict[int, DirectProposal] = field(default_factory=dict)
    reserved_goods: dict[int, tuple[str, int]] = field(default_factory=dict)
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
