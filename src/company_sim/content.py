"""Load and cross-validate all editable game content from data/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from company_sim.buildings import BuildingCatalog, load_default_buildings
from company_sim.items import ItemCatalog, load_default_catalog
from company_sim.production import ProductionCatalog, load_default_production


@dataclass
class GameContent:
    """
    Single entry point for data-driven economy definitions.

    Edit files under /data to add items, buildings, or production methods.
    Reloaded at new-game start (restart the process after editing YAML).
    """

    items: ItemCatalog
    buildings: BuildingCatalog
    production: ProductionCatalog
    root: Path

    @classmethod
    def load(cls, root: Path | None = None) -> GameContent:
        root = root or Path(__file__).resolve().parents[2] / "data"
        items = ItemCatalog.from_yaml(root / "items.yaml") if (root / "items.yaml").exists() else load_default_catalog()
        buildings = (
            BuildingCatalog.from_yaml(root / "buildings.yaml")
            if (root / "buildings.yaml").exists()
            else load_default_buildings()
        )
        production = (
            ProductionCatalog.from_yaml(root / "production_methods.yaml", items)
            if (root / "production_methods.yaml").exists()
            else load_default_production(items)
        )
        content = cls(items=items, buildings=buildings, production=production, root=root)
        content.validate()
        return content

    def validate(self) -> None:
        """Fail fast if YAML references are broken."""
        for method in self.production.all():
            self.items.validate_quantities(method.inputs)
            self.items.validate_quantities(method.outputs)
            if not self.buildings.has(method.building_id):
                raise ValueError(
                    f"Production method '{method.id}' references unknown building_id "
                    f"'{method.building_id}'"
                )

    def methods_for_building(self, building_id: str) -> list:
        return [m for m in self.production.all() if m.building_id == building_id]

    def to_public_dict(self) -> dict:
        return {
            "items": self.items.to_public_dict(),
            "buildings": self.buildings.to_public_dict(),
            "production_methods": self.production.to_public_dict(),
        }
