"""Companies, inventory, placeholder production."""

from __future__ import annotations

from dataclasses import dataclass, field


# PLACEHOLDER production method — replace with data files later
PLACEHOLDER_METHODS: dict[str, dict] = {
    "basic_goods": {
        "id": "basic_goods",
        "name": "Basic Goods",
        "inputs": {"materials": 1},
        "outputs": {"goods": 1},
        "duration_sec": 5.0,
    }
}


@dataclass
class Company:
    id: str
    name: str
    is_player: bool = False
    cash: int = 1000
    inventory: dict[str, int] = field(default_factory=lambda: {"materials": 20, "goods": 0})

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_player": self.is_player,
            "cash": self.cash,
            "inventory": dict(self.inventory),
        }
