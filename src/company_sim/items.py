"""Items (goods) and inventories."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml


@dataclass(frozen=True)
class Item:
    """
    A tradable / storable good used as production input or output.

    Add entries in data/items.yaml — inventories reference items by id.
    """

    id: str
    name: str
    category: str = "general"
    description: str = ""
    stackable: bool = True

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "stackable": self.stackable,
            "art": f"/static/assets/goods/{self.id}.svg",
        }


@dataclass
class Inventory:
    """Quantity map keyed by Item.id.

    ``reserved`` keys are hard slots: they stay in ``quantities`` even at 0
    (used for building storage that must show every allowed good).
    """

    quantities: dict[str, int] = field(default_factory=dict)
    reserved: set[str] = field(default_factory=set)

    def get(self, item_id: str) -> int:
        return int(self.quantities.get(item_id, 0))

    def set(self, item_id: str, qty: int) -> None:
        if qty < 0:
            raise ValueError(f"Negative inventory for {item_id}")
        if qty == 0 and item_id not in self.reserved:
            self.quantities.pop(item_id, None)
        else:
            self.quantities[item_id] = int(qty)

    def add(self, item_id: str, qty: int) -> None:
        self.set(item_id, self.get(item_id) + qty)

    def has(self, requirements: dict[str, int]) -> bool:
        return all(self.get(i) >= q for i, q in requirements.items())

    def consume(self, requirements: dict[str, int]) -> bool:
        if not self.has(requirements):
            return False
        for item_id, qty in requirements.items():
            self.add(item_id, -qty)
        return True

    def produce(self, outputs: dict[str, int]) -> None:
        for item_id, qty in outputs.items():
            self.add(item_id, qty)

    def reserve_slots(self, item_ids: list[str] | set[str] | tuple[str, ...]) -> None:
        """Materialize hard slots (qty 0 kept) for the given item ids."""
        for item_id in item_ids:
            self.reserved.add(item_id)
            if item_id not in self.quantities:
                self.quantities[item_id] = 0

    def unreserve_slot(self, item_id: str) -> None:
        self.reserved.discard(item_id)
        if self.quantities.get(item_id, 0) == 0:
            self.quantities.pop(item_id, None)

    def as_dict(self) -> dict[str, int]:
        return dict(self.quantities)

    def __iter__(self) -> Iterator[tuple[str, int]]:
        return iter(self.quantities.items())


class ItemCatalog:
    def __init__(self, items: dict[str, Item] | None = None) -> None:
        self._items: dict[str, Item] = dict(items or {})

    @classmethod
    def from_yaml(cls, path: Path) -> ItemCatalog:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items: dict[str, Item] = {}
        for row in data.get("items", []):
            item = Item(
                id=row["id"],
                name=row.get("name", row["id"]),
                category=row.get("category", "general"),
                description=row.get("description", ""),
                stackable=bool(row.get("stackable", True)),
            )
            if item.id in items:
                raise ValueError(f"Duplicate item id in {path}: {item.id}")
            items[item.id] = item
        return cls(items)

    def get(self, item_id: str) -> Item:
        if item_id not in self._items:
            raise KeyError(f"Unknown item: {item_id}")
        return self._items[item_id]

    def require(self, item_id: str) -> Item:
        return self.get(item_id)

    def has(self, item_id: str) -> bool:
        return item_id in self._items

    def all(self) -> list[Item]:
        return list(self._items.values())

    def validate_quantities(self, quantities: dict[str, int]) -> None:
        for item_id in quantities:
            self.require(item_id)

    def to_public_dict(self) -> list[dict]:
        return [i.to_public_dict() for i in self.all()]


def default_items_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "items.yaml"


def load_default_catalog() -> ItemCatalog:
    path = default_items_path()
    if path.exists():
        return ItemCatalog.from_yaml(path)
    return ItemCatalog(
        {
            "iron_ore": Item(id="iron_ore", name="Iron Ore", category="raw"),
            "coal": Item(id="coal", name="Coal", category="raw"),
            "energy": Item(id="energy", name="Energy", category="utility"),
            "steel": Item(id="steel", name="Steel", category="processed"),
            "construction_materials": Item(
                id="construction_materials",
                name="Construction Materials",
                category="processed",
            ),
        }
    )
