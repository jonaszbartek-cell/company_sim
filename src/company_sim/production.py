"""Production methods (recipes): items in → items out over time in a building."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from company_sim.items import ItemCatalog


@dataclass(frozen=True)
class ProductionMethod:
    """A recipe that runs inside a specific building type (by building_id)."""

    id: str
    name: str
    inputs: dict[str, int]
    outputs: dict[str, int]
    duration_sec: float
    building_id: str
    description: str = ""

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
            "duration_sec": self.duration_sec,
            "building_id": self.building_id,
        }


class ProductionCatalog:
    def __init__(self, methods: dict[str, ProductionMethod] | None = None) -> None:
        self._methods: dict[str, ProductionMethod] = dict(methods or {})

    @classmethod
    def from_yaml(cls, path: Path, items: ItemCatalog) -> ProductionCatalog:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        methods: dict[str, ProductionMethod] = {}
        for row in data.get("production_methods", []):
            inputs = {k: int(v) for k, v in (row.get("inputs") or {}).items()}
            outputs = {k: int(v) for k, v in (row.get("outputs") or {}).items()}
            items.validate_quantities(inputs)
            items.validate_quantities(outputs)
            building_id = row.get("building_id") or (row.get("allowed_building_types") or ["foundry"])[0]
            method = ProductionMethod(
                id=row["id"],
                name=row.get("name", row["id"]),
                description=row.get("description", ""),
                inputs=inputs,
                outputs=outputs,
                duration_sec=float(row.get("duration_sec", 5.0)),
                building_id=str(building_id),
            )
            methods[method.id] = method
        return cls(methods)

    def get(self, method_id: str) -> ProductionMethod:
        if method_id not in self._methods:
            raise KeyError(f"Unknown production method: {method_id}")
        return self._methods[method_id]

    def all(self) -> list[ProductionMethod]:
        return list(self._methods.values())

    def for_building(self, building_id: str) -> list[ProductionMethod]:
        return [m for m in self.all() if m.building_id == building_id]

    def to_public_dict(self) -> list[dict]:
        return [m.to_public_dict() for m in self.all()]


def default_production_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "production_methods.yaml"


def load_default_production(items: ItemCatalog) -> ProductionCatalog:
    path = default_production_path()
    if path.exists():
        return ProductionCatalog.from_yaml(path, items)
    return ProductionCatalog(
        {
            "make_steel": ProductionMethod(
                id="make_steel",
                name="Steel",
                inputs={"iron_ore": 1, "coal": 1, "energy": 1},
                outputs={"steel": 1},
                duration_sec=1.0,
                building_id="foundry",
            )
        }
    )
