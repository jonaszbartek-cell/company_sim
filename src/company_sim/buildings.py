"""Building definitions (data-driven) and runtime building instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import uuid

import yaml

from company_sim.items import Inventory

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
            "art": {
                "map": f"/static/assets/buildings/map/{self.id}/1x1.svg",
                "ui": f"/static/assets/buildings/ui/{self.id}.svg",
            },
        }


@dataclass
class Building:
    """
    Runtime instance of a building on a plot.

    On build, storage slots are *materialized*: one hard slot (cap usually 10)
    for every good that any method of this building_id uses or produces.
    ``storage_capacity`` is the live slot map on the instance; call
    ``reconcile_storage(content)`` after catalog updates / on load so new
    YAML methods add slots without wiping existing stock. Contents belong to
    the plot owner.
    """

    building_id: str
    owner_kind: str  # "company" | "city"
    owner_id: str
    id: str = field(default_factory=lambda: f"bld_{uuid.uuid4().hex[:8]}")
    production_method_id: str | None = None
    status: BuildingStatus = "idle"
    progress: float = 0.0  # 0..1 toward next batch (legacy / multi-day)
    storage: Inventory = field(default_factory=Inventory)
    # Materialized at build / reconcile: item_id -> capacity
    storage_capacity: dict[str, int] = field(default_factory=dict)
    # Footprint in plots (rectangular group this building occupies)
    footprint_w: int = 1
    footprint_h: int = 1
    # Top-left of the footprint in world coords (for multi-plot map art)
    anchor_x: int | None = None
    anchor_y: int | None = None

    @property
    def footprint_size(self) -> int:
        return max(1, int(self.footprint_w) * int(self.footprint_h))

    def map_art_path(self) -> str:
        w = max(1, min(9, int(self.footprint_w)))
        h = max(1, min(9, int(self.footprint_h)))
        return f"/static/assets/buildings/map/{self.building_id}/{w}x{h}.svg"

    def materialize_storage(self, capacity: dict[str, int]) -> None:
        """Create hard storage slots from a capacity map (call on build)."""
        self.storage_capacity = {str(k): int(v) for k, v in capacity.items()}
        self.storage.reserve_slots(self.storage_capacity.keys())

    def reconcile_storage(self, capacity: dict[str, int]) -> dict[str, object]:
        """Sync slots with current catalog capacity without losing stock.

        - New catalog goods → add hard slots at 0
        - Removed catalog goods with qty 0 → drop slot
        - Removed catalog goods with qty > 0 → keep stock (orphan) until withdrawn;
          slot is no longer depositable (not in storage_capacity)
        """
        expected = {str(k): int(v) for k, v in capacity.items()}
        added = sorted(set(expected) - set(self.storage_capacity))
        removed_empty: list[str] = []
        orphans: list[str] = []
        for item_id in list(self.storage_capacity.keys()):
            if item_id in expected:
                continue
            qty = self.storage.get(item_id)
            del self.storage_capacity[item_id]
            if qty <= 0:
                self.storage.unreserve_slot(item_id)
                removed_empty.append(item_id)
            else:
                # Keep quantities; no longer a formal slot
                self.storage.reserved.discard(item_id)
                orphans.append(item_id)
        self.storage_capacity.update(expected)
        self.storage.reserve_slots(expected.keys())
        return {
            "added": added,
            "removed_empty": sorted(removed_empty),
            "orphans": sorted(orphans),
        }

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
            "storage": self.storage.as_dict(),
            "storage_capacity": dict(self.storage_capacity),
            "footprint_w": int(self.footprint_w),
            "footprint_h": int(self.footprint_h),
            "footprint_size": self.footprint_size,
            "anchor_x": self.anchor_x,
            "anchor_y": self.anchor_y,
            "art": {
                "map": self.map_art_path(),
                "ui": f"/static/assets/buildings/ui/{self.building_id}.svg",
            },
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
