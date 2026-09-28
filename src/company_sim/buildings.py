"""Building definitions (data-driven) and runtime building instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import uuid

import yaml

BuildingStatus = Literal["idle", "working"]


@dataclass(frozen=True)
class BuildingDefinition:
    """
    Catalog entry for a constructible building type.

    Edit data/buildings.yaml to add more — no code change required for
    new ids/names/costs (production methods reference building_id).
    """

    id: str
    name: str
    description: str = ""
    build_cost: int = 100  # cash
    build_cost_items: dict[str, int] = field(default_factory=dict)
    allowed_plot_types: tuple[str, ...] = ("standard", "specialized")

    def allows_plot_type(self, plot_type: object) -> bool:
        value = getattr(plot_type, "value", plot_type)
        return str(value) in self.allowed_plot_types

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "build_cost": self.build_cost,
            "build_cost_items": dict(self.build_cost_items),
            "allowed_plot_types": list(self.allowed_plot_types),
        }


@dataclass
class Building:
    """
    Runtime instance of a building on a plot.

    possible production methods come from GameContent via building_id;
    production_method_id is the currently chosen method.
    """

    building_id: str
    owner_kind: str  # "company" | "city"
    owner_id: str
    id: str = field(default_factory=lambda: f"bld_{uuid.uuid4().hex[:8]}")
    production_method_id: str | None = None
    status: BuildingStatus = "idle"
    progress: float = 0.0  # 0..1 toward next batch (legacy / multi-day)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "building_id": self.building_id,
            "building_type": self.building_id,  # alias for older UI
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "production_method_id": self.production_method_id,
            "status": self.status,
            "progress": self.progress,
        }


class BuildingCatalog:
    def __init__(self, buildings: dict[str, BuildingDefinition] | None = None) -> None:
        self._buildings: dict[str, BuildingDefinition] = dict(buildings or {})

    @classmethod
    def from_yaml(cls, path: Path) -> BuildingCatalog:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        buildings: dict[str, BuildingDefinition] = {}
        for row in data.get("buildings", []):
            allowed = tuple(row.get("allowed_plot_types") or ["standard", "specialized"])
            cost_items = {str(k): int(v) for k, v in (row.get("build_cost_items") or {}).items()}
            bdef = BuildingDefinition(
                id=row["id"],
                name=row.get("name", row["id"]),
                description=row.get("description", ""),
                build_cost=int(row.get("build_cost", 100)),
                build_cost_items=cost_items,
                allowed_plot_types=allowed,
            )
            if bdef.id in buildings:
                raise ValueError(f"Duplicate building id in {path}: {bdef.id}")
            buildings[bdef.id] = bdef
        return cls(buildings)

    def get(self, building_id: str) -> BuildingDefinition:
        if building_id not in self._buildings:
            raise KeyError(f"Unknown building: {building_id}")
        return self._buildings[building_id]

    def has(self, building_id: str) -> bool:
        return building_id in self._buildings

    def all(self) -> list[BuildingDefinition]:
        return list(self._buildings.values())

    def to_public_dict(self) -> list[dict]:
        return [b.to_public_dict() for b in self.all()]


def default_buildings_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "buildings.yaml"


def load_default_buildings() -> BuildingCatalog:
    path = default_buildings_path()
    if path.exists():
        return BuildingCatalog.from_yaml(path)
    return BuildingCatalog(
        {
            "foundry": BuildingDefinition(
                id="foundry",
                name="Foundry",
                description="Industrial building that smelts metals",
                build_cost=100,
                build_cost_items={"construction_materials": 10},
            )
        }
    )
