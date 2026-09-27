"""Shared economic actors: City and Company share the same core behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from company_sim.items import Inventory

ActorKind = Literal["company", "city"]


@dataclass
class Actor:
    """
    Base for City and Company.

    Both hold cash/inventory, own plots/buildings through the world Action API,
    and (for AI) are driven by the same LLM tool surface.
    """

    id: str
    name: str
    cash: int = 1000
    inventory: Inventory = field(default_factory=Inventory)

    @property
    def kind(self) -> ActorKind:
        raise NotImplementedError

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "cash": self.cash,
            "inventory": self.inventory.as_dict(),
        }


@dataclass
class Company(Actor):
    is_player: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.inventory, dict):
            self.inventory = Inventory(self.inventory)
        if not self.inventory.quantities:
            self.inventory = Inventory({"iron": 20, "coal": 20, "energy": 20, "steel": 0})

    @property
    def kind(self) -> ActorKind:
        return "company"

    def to_public_dict(self) -> dict:
        data = super().to_public_dict()
        data["is_player"] = self.is_player
        return data


@dataclass
class City(Actor):
    """
    LLM-run municipality. Not a special map tile — administers a territory of
    normal roads/plots and may own buildings on ordinary plots.
    """

    center_x: int = 0
    center_y: int = 0
    population: int = 1000
    territory: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.inventory, dict):
            self.inventory = Inventory(self.inventory)
        if not self.inventory.quantities:
            self.inventory = Inventory({"iron": 20, "coal": 20, "energy": 20, "steel": 0})

    @property
    def kind(self) -> ActorKind:
        return "city"

    def to_public_dict(self) -> dict:
        data = super().to_public_dict()
        data.update(
            {
                "center_x": self.center_x,
                "center_y": self.center_y,
                "population": self.population,
                "territory_size": len(self.territory),
            }
        )
        return data
