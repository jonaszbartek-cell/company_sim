"""Plots and parcels on the map. Buildings live in company_sim.buildings.

Roads are NOT plots — they are TileKind.ROAD on the grid (no size, no building).
Plot.size is always 1 for a single cell; merging into a Parcel increases effective size.
Location (x,y) lives on the Tile that holds this Plot (needed for map / LLM context).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import uuid

from company_sim.buildings import Building


class PlotType(str, Enum):
    STANDARD = "standard"
    SPECIALIZED = "specialized"


@dataclass
class Plot:
    """
    A buyable land cell. May hold one Building instance.

    Multiple adjacent owned plots can join a Parcel (effective size > 1).
    Grid coordinates live on the Tile that contains this Plot.
    """

    plot_type: PlotType
    id: str = field(default_factory=lambda: f"plot_{uuid.uuid4().hex[:8]}")
    owner_kind: str | None = None  # "company" | "city" | None
    owner_id: str | None = None
    value: int = 100  # future land valuation; seeded from price
    price: int = 100  # current buy price when unowned
    building: Building | None = None
    parcel_id: str | None = None

    @property
    def size(self) -> int:
        """Single-cell size. Parcel size (merge) is looked up via GridMap."""
        return 1

    @property
    def is_owned(self) -> bool:
        return self.owner_id is not None

    def owned_by(self, kind: str, actor_id: str) -> bool:
        return self.owner_kind == kind and self.owner_id == actor_id

    def claim(self, kind: str, actor_id: str) -> None:
        if self.is_owned:
            raise ValueError("Plot already owned")
        self.owner_kind = kind
        self.owner_id = actor_id

    def to_public_dict(self, *, parcel_size: int = 1, production_bonus: float = 1.0) -> dict:
        return {
            "id": self.id,
            "plot_type": self.plot_type.value,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "value": self.value,
            "price": self.price,
            "size": parcel_size,
            "parcel_id": self.parcel_id,
            "parcel_size": parcel_size,
            "production_bonus": production_bonus,
            "building": None if self.building is None else self.building.to_public_dict(),
        }


@dataclass
class Parcel:
    """Merged group of adjacent owned plots granting mechanical bonuses."""

    id: str
    owner_kind: str
    owner_id: str
    cells: list[tuple[int, int]] = field(default_factory=list)

    @classmethod
    def create(cls, owner_kind: str, owner_id: str, cells: list[tuple[int, int]]) -> Parcel:
        return cls(id=str(uuid.uuid4()), owner_kind=owner_kind, owner_id=owner_id, cells=list(cells))

    @property
    def size(self) -> int:
        return max(1, len(self.cells))

    def production_bonus(self, per_extra_cell: float = 0.05) -> float:
        """PLACEHOLDER: +per_extra_cell throughput per cell beyond the first."""
        return 1.0 + per_extra_cell * (self.size - 1)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "size": self.size,
            "cells": [{"x": x, "y": y} for x, y in self.cells],
            "production_bonus": self.production_bonus(),
        }
