"""Square land plots. Roads live on plot edges; merges are pairwise side flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import uuid

from company_sim.buildings import Building

Side = str  # "N" | "E" | "S" | "W"
SIDES: tuple[str, ...] = ("N", "E", "S", "W")
OPPOSITE: dict[str, str] = {"N": "S", "S": "N", "E": "W", "W": "E"}
SIDE_DELTA: dict[str, tuple[int, int]] = {
    "N": (0, -1),
    "E": (1, 0),
    "S": (0, 1),
    "W": (-1, 0),
}


class PlotType(str, Enum):
    STANDARD = "standard"
    SPECIALIZED = "specialized"


def _empty_sides_bool() -> dict[str, bool]:
    return {s: False for s in SIDES}


def _empty_sides_opt() -> dict[str, str | None]:
    return {s: None for s in SIDES}


@dataclass
class Plot:
    """
    One square land cell.

    - roads[side]: edge road on that side of the square
    - combined[side]: plot id of the neighbor merged across that side (or None)
    Plots never disappear when combined — they only get flagged.
    """

    plot_type: PlotType
    id: str = field(default_factory=lambda: f"plot_{uuid.uuid4().hex[:8]}")
    owner_kind: str | None = None  # "company" | "city" | None
    owner_id: str | None = None
    value: int = 100
    building: Building | None = None
    roads: dict[str, bool] = field(default_factory=_empty_sides_bool)
    combined: dict[str, str | None] = field(default_factory=_empty_sides_opt)
    reserved_proposal_id: int | None = None  # locked while a plot proposal is pending

    @property
    def size(self) -> int:
        return 1

    @property
    def is_owned(self) -> bool:
        return self.owner_id is not None

    def owned_by(self, kind: str, actor_id: str) -> bool:
        return self.owner_kind == kind and self.owner_id == actor_id

    def has_any_road(self) -> bool:
        return any(self.roads.values())

    def combined_sides(self) -> list[str]:
        return [s for s, pid in self.combined.items() if pid]

    def claim(self, kind: str, actor_id: str) -> None:
        self.owner_kind = kind
        self.owner_id = actor_id

    def to_public_dict(self, *, group_size: int = 1, production_bonus: float = 1.0) -> dict:
        return {
            "id": self.id,
            "plot_type": self.plot_type.value,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "value": self.value,
            "size": group_size,
            "group_size": group_size,
            "production_bonus": production_bonus,
            "roads": dict(self.roads),
            "combined": {s: pid for s, pid in self.combined.items() if pid},
            "reserved_proposal_id": self.reserved_proposal_id,
            "building": None if self.building is None else self.building.to_public_dict(),
        }


def side_between(x1: int, y1: int, x2: int, y2: int) -> str | None:
    """Return the side of (x1,y1) that faces (x2,y2), or None if not adjacent."""
    dx, dy = x2 - x1, y2 - y1
    for side, (sx, sy) in SIDE_DELTA.items():
        if (dx, dy) == (sx, sy):
            return side
    return None
