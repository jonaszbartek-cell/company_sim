"""Direct trade proposals between agents (sell/buy offers).

Sell proposal: proposer escrows goods; cash moves only on accept.
Buy proposal: proposer escrows cash; goods move only on accept.

Goods/cash cannot be double-spent while escrowed in an open proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from company_sim.items import Inventory

ProposalSide = Literal["sell", "buy"]
ProposalStatus = Literal["open", "accepted", "rejected", "cancelled"]


@dataclass
class TradeProposal:
    id: int
    side: ProposalSide  # proposer's intent: sell goods to / buy goods from counterpart
    from_kind: str
    from_id: str
    to_kind: str
    to_id: str
    item_id: str
    quantity: int
    price: int  # cash per unit
    status: ProposalStatus = "open"
    day: int = 1

    @property
    def total(self) -> int:
        return self.price * self.quantity

    def from_key(self) -> str:
        return f"{self.from_kind}:{self.from_id}"

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
            "from": self.from_key(),
            "to": self.to_key(),
            "item_id": self.item_id,
            "quantity": self.quantity,
            "price": self.price,
            "total": self.total,
            "status": self.status,
            "day": self.day,
        }

    def to_text_line(self) -> str:
        return (
            f"#{self.id} {self.side} {self.quantity}x {self.item_id} @ {self.price}/u "
            f"{self.from_key()} -> {self.to_key()} [{self.status}] day={self.day}"
        )


@dataclass
class ProposalStore:
    """
    Indexed direct proposals + escrow so goods/cash cannot be duplicated.

    Sell proposals reserve goods in `goods_escrow`.
    Buy proposals reserve cash in `cash_escrow` keyed by proposal id.
    """

    proposals: dict[int, TradeProposal] = field(default_factory=dict)
    goods_escrow: Inventory = field(default_factory=Inventory)
    cash_escrow: dict[int, int] = field(default_factory=dict)  # proposal_id → cash
    _next_id_value: int = 1

    def next_id(self) -> int:
        pid = self._next_id_value
        self._next_id_value += 1
        return pid

    def get(self, proposal_id: int) -> TradeProposal | None:
        return self.proposals.get(proposal_id)

    def open_proposals(self) -> list[TradeProposal]:
        rows = [p for p in self.proposals.values() if p.status == "open"]
        rows.sort(key=lambda p: p.id)
        return rows

    def for_agent(self, kind: str, actor_id: str, *, open_only: bool = True) -> list[TradeProposal]:
        rows = [
            p
            for p in self.proposals.values()
            if p.involves(kind, actor_id) and (not open_only or p.status == "open")
        ]
        rows.sort(key=lambda p: p.id)
        return rows

    def add(self, proposal: TradeProposal) -> TradeProposal:
        self.proposals[proposal.id] = proposal
        return proposal

    def to_public_dict(self) -> dict:
        opens = self.open_proposals()
        return {
            "open_count": len(opens),
            "proposals": [p.to_public_dict() for p in opens],
            "goods_escrow": self.goods_escrow.as_dict(),
            "cash_escrow_total": sum(self.cash_escrow.values()),
        }

    def to_text(self) -> str:
        lines = [
            "=== DIRECT PROPOSALS ===",
            f"open_count: {len(self.open_proposals())}",
            f"goods_escrow: {self.goods_escrow.as_dict() or '{}'}",
            f"cash_escrow_total: {sum(self.cash_escrow.values())}",
            "",
            "-- open --",
        ]
        opens = self.open_proposals()
        if opens:
            lines.extend(p.to_text_line() for p in opens)
        else:
            lines.append("(none)")
        lines.append("")
        return "\n".join(lines) + "\n"

    def render_for_agent(self, kind: str, actor_id: str) -> str:
        rows = self.for_agent(kind, actor_id, open_only=False)
        # Keep recent closed + all open
        open_rows = [p for p in rows if p.status == "open"]
        closed = [p for p in rows if p.status != "open"][-8:]
        lines = [
            "=== YOUR DIRECT TRADES ===",
            f"open: {len(open_rows)}",
            "",
        ]
        if open_rows:
            lines.append("-- open --")
            lines.extend(f"  {p.to_text_line()}" for p in open_rows)
        else:
            lines.append("-- open --")
            lines.append("  (none)")
        if closed:
            lines.append("")
            lines.append("-- recent closed --")
            lines.extend(f"  {p.to_text_line()}" for p in closed)
        lines.append("")
        return "\n".join(lines) + "\n"
