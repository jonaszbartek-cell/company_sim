"""Grid of square plots only. Roads are edges on plot sides."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterator

from company_sim.actors import City
from company_sim.buildings import Building
from company_sim.items import Inventory
from company_sim.plots import (
    OPPOSITE,
    SIDES,
    Plot,
    PlotType,
    side_between,
)


@dataclass
class Tile:
    x: int
    y: int
    city_id: str | None = None  # administrative territory / starting owner city
    plot: Plot | None = None


MAX_BUILDING_FOOTPRINT = 9  # max width or height in plots


def group_bounds(cells: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    """Return (min_x, min_y, width, height) for a set of cells."""
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def is_filled_rectangle(cells: list[tuple[int, int]]) -> bool:
    if not cells:
        return False
    min_x, min_y, w, h = group_bounds(cells)
    if len(cells) != w * h:
        return False
    needed = {(x, y) for x in range(min_x, min_x + w) for y in range(min_y, min_y + h)}
    return set(cells) == needed


@dataclass
class GridMap:
    width: int
    height: int
    tiles: list[Tile] = field(default_factory=list)
    cities: dict[str, City] = field(default_factory=dict)
    _plot_index: dict[str, tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def create(cls, width: int, height: int) -> GridMap:
        tiles = [Tile(x=x, y=y) for y in range(height) for x in range(width)]
        return cls(width=width, height=height, tiles=tiles)

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get(self, x: int, y: int) -> Tile:
        return self.tiles[self.index(x, y)]

    def neighbors4(self, x: int, y: int) -> Iterator[tuple[int, int]]:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                yield nx, ny

    def rebuild_plot_index(self) -> None:
        self._plot_index = {}
        for t in self.tiles:
            if t.plot:
                self._plot_index[t.plot.id] = (t.x, t.y)

    def coords_for_plot_id(self, plot_id: str) -> tuple[int, int] | None:
        return self._plot_index.get(plot_id)

    def find_plot(self, plot_id: str) -> Plot | None:
        coords = self.coords_for_plot_id(plot_id)
        if coords is None:
            return None
        tile = self.get(*coords)
        return tile.plot

    def has_road_on_side(self, x: int, y: int, side: str) -> bool:
        tile = self.get(x, y)
        if not tile.plot:
            return False
        return bool(tile.plot.roads.get(side))

    def shared_edge_has_road(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """True if either plot has a road on the shared edge (roads are plot-local)."""
        side = side_between(x1, y1, x2, y2)
        if side is None:
            return False
        if self.has_road_on_side(x1, y1, side):
            return True
        return self.has_road_on_side(x2, y2, OPPOSITE[side])

    def build_edge_road(self, x: int, y: int, side: str) -> None:
        """Build a road on one side of this plot only — does not affect the neighbor."""
        if side not in SIDES:
            raise ValueError(f"Invalid side: {side}")
        tile = self.get(x, y)
        if not tile.plot:
            raise ValueError("No plot there")
        if tile.plot.combined.get(side):
            raise ValueError("Cannot build a road on a combined side")
        if tile.plot.roads.get(side):
            raise ValueError("Road already exists on that side")
        tile.plot.roads[side] = True

    def combine_plots(self, x1: int, y1: int, x2: int, y2: int, owner_kind: str, owner_id: str) -> None:
        """Combine two adjacent owned plots.

        Allowed when both are empty, one is empty + one has a building (expand),
        or both have the *same* building_id (merge). Groups that contain a
        building must stay a filled rectangle ≤9×9.
        """
        a = self.get(x1, y1)
        b = self.get(x2, y2)
        if not a.plot or not b.plot:
            raise ValueError("Both cells must be plots")
        if not a.plot.owned_by(owner_kind, owner_id) or not b.plot.owned_by(owner_kind, owner_id):
            raise ValueError("You must own both plots")
        side_a = side_between(x1, y1, x2, y2)
        if side_a is None:
            raise ValueError("Plots must be adjacent")
        side_b = OPPOSITE[side_a]
        if a.plot.roads.get(side_a) or b.plot.roads.get(side_b):
            raise ValueError("Cannot combine across a road")
        if a.plot.combined.get(side_a) or b.plot.combined.get(side_b):
            raise ValueError("Already combined on that side")
        if a.plot.reserved_proposal_id or b.plot.reserved_proposal_id:
            raise ValueError("Plot is reserved by a pending proposal")

        ba = a.plot.building
        bb = b.plot.building
        if ba and bb and ba.building_id != bb.building_id:
            raise ValueError("Can only combine plots with the same building type")
        if ba and bb:
            # Mine/Rig (locked-method buildings): merge requires identical methods
            if (
                ba.production_method_locked
                or bb.production_method_locked
                or ba.building_id in ("mine", "rig")
            ):
                if ba.production_method_id != bb.production_method_id:
                    raise ValueError(
                        "Can only combine mine/rig plots with the same production method"
                    )
        # Expanding a building onto an empty plot must respect allowed plot types
        expanding = None
        empty_plot = None
        if ba and not bb:
            expanding, empty_plot = ba, b.plot
        elif bb and not ba:
            expanding, empty_plot = bb, a.plot
        if expanding is not None and empty_plot is not None:
            allowed = _allowed_plot_types_for_building(expanding.building_id)
            if empty_plot.plot_type.value not in allowed and not (
                "specialized" in allowed
                and empty_plot.plot_type.value
                in ("specialized_mine", "specialized_well", "specialized")
            ):
                raise ValueError(
                    f"{expanding.building_id} cannot expand onto {empty_plot.plot_type.value} plots"
                )

        # Tentatively combine, then validate resulting group
        a.plot.combined[side_a] = b.plot.id
        b.plot.combined[side_b] = a.plot.id
        try:
            self._validate_and_sync_building_group(x1, y1)
        except ValueError:
            a.plot.combined[side_a] = None
            b.plot.combined[side_b] = None
            raise

    def _validate_and_sync_building_group(self, x: int, y: int) -> None:
        """After a combine, ensure building rules and sync footprint/instances."""
        cells = self.combined_group(x, y)
        buildings = []
        for cx, cy in cells:
            plot = self.get(cx, cy).plot
            if plot and plot.building:
                buildings.append((cx, cy, plot.building))

        if not buildings:
            return  # empty group — any connected shape ok

        types = {b.building_id for _, _, b in buildings}
        if len(types) > 1:
            raise ValueError("Combined group cannot mix different buildings")
        if not is_filled_rectangle(cells):
            raise ValueError("Plots with a building must form a filled rectangle")
        min_x, min_y, w, h = group_bounds(cells)
        if w > MAX_BUILDING_FOOTPRINT or h > MAX_BUILDING_FOOTPRINT:
            raise ValueError(f"Building footprint cannot exceed {MAX_BUILDING_FOOTPRINT}×{MAX_BUILDING_FOOTPRINT}")

        # Merge into one shared Building instance across the rectangle
        unique: dict[str, object] = {}
        for _, _, b in buildings:
            unique[b.id] = b
        primary = next(iter(unique.values()))
        for other in list(unique.values())[1:]:
            # Merge storage quantities into primary
            for item_id, qty in other.storage.as_dict().items():
                if qty:
                    primary.storage.add(item_id, qty)
            if not primary.production_method_id and other.production_method_id:
                primary.production_method_id = other.production_method_id
            if getattr(other, "production_method_locked", False):
                primary.production_method_locked = True
            # Keep capacity union
            for item_id, cap in other.storage_capacity.items():
                primary.storage_capacity.setdefault(item_id, cap)
                primary.storage.reserve_slots([item_id])

        primary.footprint_w = w
        primary.footprint_h = h
        primary.anchor_x = min_x
        primary.anchor_y = min_y
        for cx, cy in cells:
            self.get(cx, cy).plot.building = primary

    def place_building_on_group(self, x: int, y: int, building: Building) -> tuple[int, int, int, int]:
        """Place the same building instance on every cell of a rectangular group."""
        cells = self.combined_group(x, y) or [(x, y)]
        if not is_filled_rectangle(cells):
            raise ValueError("Building requires a filled rectangular plot group")
        min_x, min_y, w, h = group_bounds(cells)
        if w > MAX_BUILDING_FOOTPRINT or h > MAX_BUILDING_FOOTPRINT:
            raise ValueError(f"Building footprint cannot exceed {MAX_BUILDING_FOOTPRINT}×{MAX_BUILDING_FOOTPRINT}")
        for cx, cy in cells:
            plot = self.get(cx, cy).plot
            if not plot:
                raise ValueError("Missing plot in group")
            if plot.building is not None and plot.building is not building:
                raise ValueError("Plot already has a building")
        building.footprint_w = w
        building.footprint_h = h
        building.anchor_x = min_x
        building.anchor_y = min_y
        for cx, cy in cells:
            assert self.get(cx, cy).plot is not None
            self.get(cx, cy).plot.building = building  # type: ignore[union-attr]
        return min_x, min_y, w, h

    def clear_building_from_group(self, x: int, y: int) -> None:
        """Remove building from every plot in the combined group."""
        cells = self.combined_group(x, y) or [(x, y)]
        for cx, cy in cells:
            plot = self.get(cx, cy).plot
            if plot:
                plot.building = None

    def clear_combines_at(self, x: int, y: int) -> None:
        """Break all combine flags involving this plot (e.g. after ownership transfer)."""
        tile = self.get(x, y)
        if not tile.plot:
            return
        for side in list(SIDES):
            other_id = tile.plot.combined.get(side)
            if not other_id:
                continue
            tile.plot.combined[side] = None
            coords = self.coords_for_plot_id(other_id)
            if coords is None:
                continue
            other = self.get(*coords).plot
            if other:
                opp = OPPOSITE[side]
                if other.combined.get(opp) == tile.plot.id:
                    other.combined[opp] = None

    def road_mask_at(self, x: int, y: int) -> int:
        """Bitmask of edge roads on this plot: N=1 E=2 S=4 W=8."""
        tile = self.get(x, y)
        if not tile.plot:
            return 0
        bits = {"N": 1, "E": 2, "S": 4, "W": 8}
        mask = 0
        for side, bit in bits.items():
            if tile.plot.roads.get(side):
                mask |= bit
        return mask

    def combined_group(self, x: int, y: int) -> list[tuple[int, int]]:
        """Connected component via combine flags."""
        start = self.get(x, y)
        if not start.plot:
            return []
        seen: set[tuple[int, int]] = set()
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            plot = self.get(cx, cy).plot
            if not plot:
                continue
            for side, other_id in plot.combined.items():
                if not other_id:
                    continue
                coords = self.coords_for_plot_id(other_id)
                if coords and coords not in seen:
                    stack.append(coords)
        return list(seen)

    def group_size(self, x: int, y: int) -> int:
        return max(1, len(self.combined_group(x, y)))

    def production_bonus_at(self, x: int, y: int, per_extra_cell: float = 0.05) -> float:
        size = self.group_size(x, y)
        return 1.0 + per_extra_cell * (size - 1)

    def rebuild_territories(self) -> None:
        for city in self.cities.values():
            city.territory = []
        for tile in self.tiles:
            if tile.city_id and tile.city_id in self.cities:
                self.cities[tile.city_id].territory.append((tile.x, tile.y))

    def to_public_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "cities": [c.to_public_dict() for c in self.cities.values()],
            "tiles": [
                {
                    "x": t.x,
                    "y": t.y,
                    "kind": "plot",
                    "city_id": t.city_id,
                    "road_mask": self.road_mask_at(t.x, t.y),
                    "plot": None
                    if t.plot is None
                    else t.plot.to_public_dict(
                        group_size=self.group_size(t.x, t.y),
                        production_bonus=round(self.production_bonus_at(t.x, t.y), 3),
                    ),
                }
                for t in self.tiles
            ],
        }


def _allowed_plot_types_for_building(building_id: str) -> tuple[str, ...]:
    """Best-effort allowed plot types without requiring a World."""
    if building_id == "mine":
        return ("specialized_mine",)
    if building_id == "rig":
        return ("specialized_well",)
    return ("standard", "specialized_mine", "specialized_well")


def plan_specialized_plots(
    width: int,
    height: int,
    *,
    percent: float = 15.0,
    min_each: int = 5,
    seed: int | None = None,
) -> dict[tuple[int, int], PlotType]:
    """
    Place specialized_mine / specialized_well cells.

    - Guaranteed ``min_each`` of each type (when the map has room) are placed
      **randomly** across the map — not clustered.
    - Any additional plots from ``percent`` of all cells are placed in regional
      clusters (with optional small gaps).
    """
    import random

    n = width * height
    if n <= 0:
        return {}
    rng = random.Random(
        seed if seed is not None else (width * 10007 + height * 17 + int(percent * 10))
    )
    cells = [(x, y) for y in range(height) for x in range(width)]
    pct = max(0.0, min(100.0, float(percent)))
    target_total = int(round(n * pct / 100.0))
    capacity_each = n // 2
    guarantee = min(int(min_each), capacity_each)
    # Always include the random guarantees; percent may add more on top
    target_total = max(target_total, guarantee * 2)
    target_total = min(target_total, n)
    n_mine = max(guarantee, target_total // 2)
    n_well = max(guarantee, target_total - n_mine)
    while n_mine + n_well > n:
        if n_mine > n_well and n_mine > 0:
            n_mine -= 1
        elif n_well > 0:
            n_well -= 1
        else:
            break

    def _place_random(count: int, taken: set[tuple[int, int]]) -> set[tuple[int, int]]:
        """Scatter ``count`` cells uniformly at random (no clustering)."""
        if count <= 0:
            return set()
        available = [c for c in cells if c not in taken]
        if not available:
            return set()
        rng.shuffle(available)
        return set(available[: min(count, len(available))])

    def _place_clustered(count: int, taken: set[tuple[int, int]]) -> set[tuple[int, int]]:
        """Regional clusters with optional small gaps."""
        if count <= 0:
            return set()
        available = [c for c in cells if c not in taken]
        if not available:
            return set()
        n_clusters = max(1, min(count, int(count ** 0.5)))
        rng.shuffle(available)
        min_sep = max(2, min(width, height) // max(3, n_clusters + 1))
        centers: list[tuple[int, int]] = []
        for c in available:
            if all(abs(c[0] - cx) + abs(c[1] - cy) >= min_sep for cx, cy in centers):
                centers.append(c)
            if len(centers) >= n_clusters:
                break
        while len(centers) < n_clusters:
            centers.append(available[len(centers) % len(available)])

        radius = max(2, int((count / max(1, n_clusters)) ** 0.5) + 2)
        chosen: set[tuple[int, int]] = set()
        for cx, cy in centers:
            nearby = [
                c
                for c in available
                if c not in chosen and abs(c[0] - cx) + abs(c[1] - cy) <= radius
            ]
            nearby.sort(key=lambda c: abs(c[0] - cx) + abs(c[1] - cy))
            for i, c in enumerate(nearby):
                if len(chosen) >= count:
                    break
                if i == 0 or rng.random() < 0.7:
                    chosen.add(c)
            if len(chosen) >= count:
                break
        if len(chosen) < count:
            leftovers = sorted(
                [c for c in available if c not in chosen],
                key=lambda c: min(abs(c[0] - cx) + abs(c[1] - cy) for cx, cy in centers),
            )
            for c in leftovers:
                if len(chosen) >= count:
                    break
                chosen.add(c)
        return chosen

    # Phase 1: guaranteed minimums — random scatter (not clustered)
    g_mine = min(guarantee, n_mine)
    g_well = min(guarantee, n_well)
    mine_cells = _place_random(g_mine, set())
    well_cells = _place_random(g_well, mine_cells)

    # Phase 2: remaining from percent — clustered
    extra_mine = max(0, n_mine - len(mine_cells))
    extra_well = max(0, n_well - len(well_cells))
    taken = mine_cells | well_cells
    mine_cells |= _place_clustered(extra_mine, taken)
    taken = mine_cells | well_cells
    well_cells |= _place_clustered(extra_well, taken)

    out: dict[tuple[int, int], PlotType] = {}
    for c in mine_cells:
        out[c] = PlotType.SPECIALIZED_MINE
    for c in well_cells:
        out[c] = PlotType.SPECIALIZED_WELL
    return out


def generate_map(
    size: int,
    city_seeds: list[tuple[str, str, int, int, int]],
    *,
    specialized_plot_percent: float = 15.0,
    specialized_seed: int | None = None,
) -> GridMap:
    """
    Build an NxN grid of square plots only.

    city_seeds: (id, name, center_x, center_y, population)
    Territory is assigned by nearest city center; ownership is applied by World.

    Specialized resource plots: a guaranteed random scatter of mine/well cells,
    plus additional clustered cells from ``specialized_plot_percent``.
    """
    if size < 2:
        raise ValueError("Map size must be at least 2")
    grid = GridMap.create(size, size)

    for cid, name, x, y, pop in city_seeds:
        if not grid.in_bounds(x, y):
            x = min(max(0, x), size - 1)
            y = min(max(0, y), size - 1)
        grid.cities[cid] = City(
            id=cid,
            name=name,
            cash=3000,
            center_x=x,
            center_y=y,
            population=pop,
            inventory=Inventory(
                {
                    "iron_ore": 20,
                    "coal": 20,
                    "energy": 20,
                    "steel": 0,
                    "construction_materials": 50,
                }
            ),
        )

    specialized = plan_specialized_plots(
        size,
        size,
        percent=specialized_plot_percent,
        min_each=5,
        seed=specialized_seed,
    )

    # Equal-ish division: assign every cell to nearest city seed
    for tile in grid.tiles:
        tile.city_id = _nearest_city_id(grid, tile.x, tile.y)
        ptype = specialized.get((tile.x, tile.y), PlotType.STANDARD)
        value = 150 if ptype != PlotType.STANDARD else 100
        tile.plot = Plot(plot_type=ptype, value=value)

    grid.rebuild_plot_index()
    grid.rebuild_territories()
    return grid


def _nearest_city_id(grid: GridMap, x: int, y: int) -> str | None:
    best_id = None
    best_d = 10**9
    for c in grid.cities.values():
        d = abs(x - c.center_x) + abs(y - c.center_y)
        if d < best_d:
            best_d = d
            best_id = c.id
    return best_id


def place_city_seeds(
    size: int,
    count: int,
    *,
    rng: random.Random | None = None,
    min_sep: int | None = None,
) -> list[tuple[int, int]]:
    """Spread city centers across the map.

    When ``rng`` is set, pick centers randomly with Chebyshev separation
    (not a regular grid / line). Otherwise use the deterministic grid layout.
    """
    if count <= 0:
        return []
    if count == 1:
        return [(size // 2, size // 2)]

    if rng is not None:
        sep = min_sep if min_sep is not None else max(2, size // (count + 1))
        points: list[tuple[int, int]] = []
        # Keep centers off the absolute border a bit
        margin = max(1, size // 16)
        lo, hi = margin, max(margin + 1, size - margin)
        tries = 0
        while len(points) < count and tries < count * 400:
            tries += 1
            x = rng.randrange(lo, hi)
            y = rng.randrange(lo, hi)
            if any(max(abs(x - ox), abs(y - oy)) < sep for ox, oy in points):
                continue
            points.append((x, y))
        if len(points) < count:
            # Relax separation and finish
            while len(points) < count:
                x = rng.randrange(size)
                y = rng.randrange(size)
                if (x, y) in points:
                    continue
                if any(max(abs(x - ox), abs(y - oy)) < 2 for ox, oy in points):
                    continue
                points.append((x, y))
        return points

    # Place on a rough grid
    cols = int(count**0.5 + 0.999)
    rows = (count + cols - 1) // cols
    points = []
    i = 0
    for r in range(rows):
        for c in range(cols):
            if i >= count:
                break
            x = int((c + 0.5) * size / cols)
            y = int((r + 0.5) * size / rows)
            x = min(max(0, x), size - 1)
            y = min(max(0, y), size - 1)
            points.append((x, y))
            i += 1
    return points


__all__ = [
    "Tile",
    "GridMap",
    "generate_map",
    "plan_specialized_plots",
    "place_city_seeds",
    "Plot",
    "PlotType",
    "SIDES",
    "OPPOSITE",
    "side_between",
]
