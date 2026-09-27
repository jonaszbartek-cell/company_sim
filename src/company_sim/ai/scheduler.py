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

    def _heuristic_city(self, world: World, city_id: str) -> None:
        city = world.grid.cities[city_id]
        # Expand toward empty neighbor of an existing road near the city
        candidates: list[tuple[int, int]] = []
        for tile in world.grid.tiles:
            if tile.kind.value != "road":
                continue
            if abs(tile.x - city.x) + abs(tile.y - city.y) > 6:
                continue
            for nx, ny in world.grid.neighbors4(tile.x, tile.y):
                if world.grid.get(nx, ny).kind.value == "empty":
                    candidates.append((nx, ny))
        if not candidates:
            self.last_thought = f"{city.name}: no expansion room nearby"
            return
        # Prefer outward growth
        candidates.sort(key=lambda p: -(abs(p[0] - city.x) + abs(p[1] - city.y)))
        x, y = candidates[0]
        try:
            world.city_build_road(city_id, x, y)
            self.last_thought = f"{city.name}: built road at ({x},{y})"
        except Exception as exc:  # noqa: BLE001 — scaffold logging
            self.last_thought = f"{city.name}: road failed ({exc})"

    def _heuristic_company(self, world: World, company_id: str) -> None:
        company = world.companies[company_id]
        # Buy a cheap nearby unowned plot if possible
        unowned = [
            t
            for t in world.grid.tiles
            if t.kind.value == "plot"
            and t.plot
            and t.plot.owner_company_id is None
            and t.plot.price <= company.cash
        ]
        if unowned and company.cash >= unowned[0].plot.price:  # type: ignore[union-attr]
            t = unowned[0]
            try:
                world.buy_plot(company_id, t.x, t.y)
                world.build_building(company_id, t.x, t.y)
                self.last_thought = f"{company.name}: bought+built at ({t.x},{t.y})"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{company.name}: buy/build failed ({exc})"
                return
        self.last_thought = f"{company.name}: holding"
