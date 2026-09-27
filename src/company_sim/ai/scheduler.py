"""AI scheduler stub — one worker slot, many entities. LLM wired later."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from company_sim.world import World


@dataclass
class AIScheduler:
    """Round-robin placeholder. Later: call local llama-server with tools."""

    decision_interval_sec: float = 8.0
    _last_decision_at: dict[str, float] = field(default_factory=dict)
    _entity_cycle: itertools.cycle | None = None
    last_thought: str = "AI idle (LLM not connected yet)"
    busy: bool = False

    def ensure_entities(self, world: World) -> None:
        ids = [c.id for c in world.companies.values() if not c.is_player]
        ids += list(world.grid.cities.keys())
        self._entity_cycle = itertools.cycle(ids) if ids else None

    def update(self, world: World) -> None:
        """Non-blocking. For now applies a tiny heuristic so rivals/cities move."""
        if world.paused or self.busy:
            return
        self.ensure_entities(world)
        if self._entity_cycle is None:
            return

        entity_id = next(self._entity_cycle)
        last = self._last_decision_at.get(entity_id, -999.0)
        if world.time_sec - last < self.decision_interval_sec:
            return

        self._last_decision_at[entity_id] = world.time_sec

        if entity_id in world.grid.cities:
            self._heuristic_city(world, entity_id)
        elif entity_id in world.companies:
            self._heuristic_company(world, entity_id)

    def _road_candidates_near(self, world: World, cx: int, cy: int, radius: int) -> list[tuple[int, int]]:
        """Unowned plots (or empty) adjacent to existing road/city near a point."""
        candidates: list[tuple[int, int]] = []
        for tile in world.grid.tiles:
            if abs(tile.x - cx) + abs(tile.y - cy) > radius:
                continue
            if tile.kind.value == "empty":
                if any(
                    world.grid.get(nx, ny).kind.value in ("road", "city")
                    for nx, ny in world.grid.neighbors4(tile.x, tile.y)
                ):
                    candidates.append((tile.x, tile.y))
            elif tile.kind.value == "plot" and tile.plot and tile.plot.owner_company_id is None:
                if any(
                    world.grid.get(nx, ny).kind.value in ("road", "city")
                    for nx, ny in world.grid.neighbors4(tile.x, tile.y)
                ):
                    candidates.append((tile.x, tile.y))
        return candidates

    def _heuristic_city(self, world: World, city_id: str) -> None:
        city = world.grid.cities[city_id]
        candidates = self._road_candidates_near(world, city.x, city.y, radius=8)
        if not candidates:
            self.last_thought = f"{city.name}: no expansion room nearby"
            return
        candidates.sort(key=lambda p: -(abs(p[0] - city.x) + abs(p[1] - city.y)))
        x, y = candidates[0]
        try:
            world.city_build_road(city_id, x, y)
            self.last_thought = f"{city.name}: built road at ({x},{y})"
        except Exception as exc:  # noqa: BLE001
            self.last_thought = f"{city.name}: road failed ({exc})"

    def _heuristic_company(self, world: World, company_id: str) -> None:
        company = world.companies[company_id]
        owned = [
            t
            for t in world.grid.tiles
            if t.kind.value == "plot" and t.plot and t.plot.owner_company_id == company_id
        ]
        # Prefer buy+build if we have no site yet
        if not owned:
            unowned = [
                t
                for t in world.grid.tiles
                if t.kind.value == "plot"
                and t.plot
                and t.plot.owner_company_id is None
                and t.plot.price <= company.cash
            ]
            unowned.sort(key=lambda t: t.plot.price)  # type: ignore[union-attr]
            if unowned:
                t = unowned[0]
                try:
                    world.buy_plot(company_id, t.x, t.y)
                    if company.cash >= 200:
                        world.build_building(company_id, t.x, t.y)
                    self.last_thought = f"{company.name}: bought at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: buy failed ({exc})"
                    return

        # Sometimes extend road from owned land
        if owned and company.cash >= world.config.road_build_cost:
            ox, oy = owned[0].x, owned[0].y
            candidates = self._road_candidates_near(world, ox, oy, radius=5)
            if candidates:
                x, y = candidates[0]
                try:
                    world.company_build_road(company_id, x, y)
                    self.last_thought = f"{company.name}: built road at ({x},{y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: road failed ({exc})"

        # Merge two adjacent owned plots if possible
        for t in owned:
            for nx, ny in world.grid.neighbors4(t.x, t.y):
                n = world.grid.get(nx, ny)
                if (
                    n.kind.value == "plot"
                    and n.plot
                    and n.plot.owner_company_id == company_id
                    and n.plot.parcel_id != t.plot.parcel_id
                ):
                    try:
                        world.merge_plots(company_id, t.x, t.y, nx, ny)
                        self.last_thought = f"{company.name}: merged plots"
                        return
                    except Exception:
                        pass

        self.last_thought = f"{company.name}: holding"
