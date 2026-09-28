"""Load and cross-validate all editable game content from data/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    Indexes (rebuilt on load) make content queryable for UI / LLM / tools:
      - methods_by_building[building_id] → method ids
      - produced_by[item_id] → method ids that output the item
      - used_in[item_id] → method ids that consume the item
      - goods_index[item_id] → full good card (made in / used in / …)
    """

    items: ItemCatalog
    buildings: BuildingCatalog
    production: ProductionCatalog
    root: Path
    methods_by_building: dict[str, list[str]] = field(default_factory=dict)
    produced_by: dict[str, list[str]] = field(default_factory=dict)
    used_in: dict[str, list[str]] = field(default_factory=dict)
    goods_index: dict[str, dict] = field(default_factory=dict)

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
        content.rebuild_indexes()
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
        for bdef in self.buildings.all():
            self.items.validate_quantities(bdef.build_cost_items)

    def rebuild_indexes(self) -> None:
        """Build reverse indexes over items / buildings / methods."""
        methods_by_building: dict[str, list[str]] = {b.id: [] for b in self.buildings.all()}
        produced_by: dict[str, list[str]] = {i.id: [] for i in self.items.all()}
        used_in: dict[str, list[str]] = {i.id: [] for i in self.items.all()}

        for method in self.production.all():
            methods_by_building.setdefault(method.building_id, []).append(method.id)
            for item_id in method.outputs:
                produced_by.setdefault(item_id, []).append(method.id)
            for item_id in method.inputs:
                used_in.setdefault(item_id, []).append(method.id)

        goods_index: dict[str, dict] = {}
        for item in self.items.all():
            made_in_methods = produced_by.get(item.id, [])
            made_in_buildings: list[str] = []
            producers: list[dict] = []
            for mid in made_in_methods:
                method = self.production.get(mid)
                made_in_buildings.append(method.building_id)
                producers.append(
                    {
                        "method_id": method.id,
                        "method_name": method.name,
                        "building_id": method.building_id,
                        "building_name": self.buildings.get(method.building_id).name
                        if self.buildings.has(method.building_id)
                        else method.building_id,
                        "inputs": dict(method.inputs),
                        "outputs": dict(method.outputs),
                        "duration_sec": method.duration_sec,
                    }
                )
            consumers: list[dict] = []
            for mid in used_in.get(item.id, []):
                method = self.production.get(mid)
                consumers.append(
                    {
                        "method_id": method.id,
                        "method_name": method.name,
                        "building_id": method.building_id,
                        "building_name": self.buildings.get(method.building_id).name
                        if self.buildings.has(method.building_id)
                        else method.building_id,
                        "qty_required": int(method.inputs.get(item.id, 0)),
                    }
                )
            # Also note if used as a building construction cost
            build_cost_for = [
                b.id for b in self.buildings.all() if item.id in b.build_cost_items
            ]
            goods_index[item.id] = {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "stackable": item.stackable,
                "made_in_buildings": sorted(set(made_in_buildings)),
                "produced_by_methods": list(made_in_methods),
                "used_in_methods": list(used_in.get(item.id, [])),
                "used_as_build_cost_for": build_cost_for,
                "producers": producers,
                "consumers": consumers,
            }

        self.methods_by_building = methods_by_building
        self.produced_by = produced_by
        self.used_in = used_in
        self.goods_index = goods_index

    def methods_for_building(self, building_id: str) -> list:
        return [self.production.get(mid) for mid in self.methods_by_building.get(building_id, [])]

    def storage_items_for_building(self, building_id: str) -> list[str]:
        """Item ids that can be stored in this building (union of method I/O).

        Capacity is always 10 per item; list rebuilds when YAML methods change.
        """
        items: set[str] = set()
        for method in self.methods_for_building(building_id):
            items.update(method.inputs.keys())
            items.update(method.outputs.keys())
        return sorted(items)

    def storage_capacity_for_building(self, building_id: str) -> dict[str, int]:
        return {item_id: 10 for item_id in self.storage_items_for_building(building_id)}

    def good_card(self, item_id: str) -> dict:
        if item_id not in self.goods_index:
            raise KeyError(f"Unknown item: {item_id}")
        return self.goods_index[item_id]

    def render_goods_index_text(self, *, compact: bool = True) -> str:
        """Plain-text goods index for LLM / file packing."""
        lines = [
            "=== GOODS INDEX ===",
            "file: (derived from items.yaml + production_methods.yaml + buildings.yaml)",
            f"item_count: {len(self.goods_index)}",
            f"building_count: {len(self.buildings.all())}",
            f"method_count: {len(self.production.all())}",
            "",
        ]
        for item_id in sorted(self.goods_index):
            card = self.goods_index[item_id]
            made = ", ".join(card["made_in_buildings"]) or "(not produced)"
            used = ", ".join(card["used_in_methods"]) or "(not used as input)"
            lines.append(f"-- {card['name']} [{item_id}] ({card['category']}) --")
            if not compact and card.get("description"):
                lines.append(f"  {card['description']}")
            lines.append(f"  made_in: {made}")
            lines.append(f"  produced_by: {', '.join(card['produced_by_methods']) or '(none)'}")
            lines.append(f"  used_in: {used}")
            if card["used_as_build_cost_for"]:
                lines.append(
                    f"  build_cost_for: {', '.join(card['used_as_build_cost_for'])}"
                )
            lines.append("")
        return "\n".join(lines)

    def render_buildings_catalog_text(self) -> str:
        lines = [
            "=== BUILDINGS CATALOG ===",
            "file: (derived from buildings.yaml + production_methods.yaml)",
            f"building_count: {len(self.buildings.all())}",
            "",
        ]
        for b in self.buildings.all():
            methods = self.methods_by_building.get(b.id, [])
            slots = self.storage_items_for_building(b.id)
            lines.append(f"-- {b.name} [{b.id}] --")
            lines.append(f"  build_cost_cash: {b.build_cost}")
            lines.append(f"  build_cost_items: {b.build_cost_items or '{}'}")
            lines.append(f"  allowed_plot_types: {list(b.allowed_plot_types)}")
            lines.append(f"  methods: {', '.join(methods) or '(none)'}")
            lines.append(f"  storage_slots (cap 10 each): {', '.join(slots) or '(none)'}")
            if b.description:
                lines.append(f"  {b.description}")
            lines.append("")
        return "\n".join(lines)

    def render_methods_catalog_text(self) -> str:
        lines = [
            "=== PRODUCTION METHODS CATALOG ===",
            "file: (derived from production_methods.yaml)",
            f"method_count: {len(self.production.all())}",
            "",
        ]
        for m in self.production.all():
            lines.append(f"-- {m.name} [{m.id}] @ {m.building_id} --")
            lines.append(f"  duration_sec: {m.duration_sec}")
            lines.append(f"  inputs: {m.inputs or '{}'}")
            lines.append(f"  outputs: {m.outputs or '{}'}")
            lines.append("")
        return "\n".join(lines)

    def to_public_dict(self) -> dict:
        return {
            "items": self.items.to_public_dict(),
            "buildings": [
                {
                    **b.to_public_dict(),
                    "methods": list(self.methods_by_building.get(b.id, [])),
                    "storage_capacity": self.storage_capacity_for_building(b.id),
                }
                for b in self.buildings.all()
            ],
            "production_methods": self.production.to_public_dict(),
            "indexes": {
                "methods_by_building": dict(self.methods_by_building),
                "produced_by": dict(self.produced_by),
                "used_in": dict(self.used_in),
            },
            "goods_index": dict(self.goods_index),
        }
