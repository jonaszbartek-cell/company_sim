"""AI scheduler: one LLM worker, many Actor minds; heuristic fallback."""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from company_sim.actors import Actor, City
from company_sim.ai.llm_client import LLMClient, LLMConfig, parse_tool_calls
from company_sim.ai.tools import (
    TOOL_DEFINITIONS,
    ToolExecutor,
    build_actor_context,
    system_prompt_for,
)

if TYPE_CHECKING:
    from company_sim.world import World

log = logging.getLogger(__name__)


@dataclass
class AIScheduler:
    """
    Round-robin across AI companies + cities.

    If local LLM is enabled and reachable, one decision runs at a time (async thread).
    Otherwise uses the heuristic policy so the game stays playable.
    """

    decision_interval_sec: float = 8.0
    llm: LLMClient = field(default_factory=LLMClient)
    _last_decision_at: dict[str, float] = field(default_factory=dict)
    _entity_cycle: itertools.cycle | None = None
    _entity_tokens: list[str] = field(default_factory=list)
    last_thought: str = "AI idle"
    busy: bool = False
    llm_mode: str = "unknown"  # off | online | fallback
    _loop_task: asyncio.Task | None = None

    def __post_init__(self) -> None:
        if not self.llm.config.enabled:
            self.llm_mode = "off"
            self.last_thought = "AI heuristic (LLM disabled — set COMPANY_SIM_LLM=1)"
        elif self.llm.available():
            self.llm_mode = "online"
            self.last_thought = f"LLM online ({self.llm.config.model})"
        else:
            self.llm_mode = "fallback"
            self.last_thought = "LLM enabled but unreachable — using heuristic"

    def ensure_entities(self, world: World) -> None:
        tokens = [f"{a.kind}:{a.id}" for a in world.iter_ai_actors()]
        if not tokens:
            self._entity_cycle = None
            self._entity_tokens = []
            return
        # Only rebuild the cycle when the actor set changes — recreating every
        # tick would reset itertools.cycle to the first entity forever.
        if tokens != self._entity_tokens:
            self._entity_tokens = tokens
            self._entity_cycle = itertools.cycle(tokens)

    def update(self, world: World) -> None:
        """Non-blocking. Called every sim tick from the asyncio loop."""
        if world.paused or self.busy:
            return
        self.ensure_entities(world)
        if self._entity_cycle is None:
            return

        token = next(self._entity_cycle)
        last = self._last_decision_at.get(token, -999.0)
        if world.time_sec - last < self.decision_interval_sec:
            return
        self._last_decision_at[token] = world.time_sec

        kind, entity_id = token.split(":", 1)
        try:
            actor = world.get_actor(kind, entity_id)
        except Exception:  # noqa: BLE001
            return

        if self.llm_mode == "online" or (
            self.llm.config.enabled and self.llm_mode != "off" and self.llm.available()
        ):
            self.llm_mode = "online"
            self.busy = True
            try:
                loop = asyncio.get_running_loop()
                self._loop_task = loop.create_task(self._llm_decide(world, actor))
            except RuntimeError:
                self.busy = False
                self._heuristic(world, actor)
            return

        self._heuristic(world, actor)

    async def _llm_decide(self, world: World, actor: Actor) -> None:
        try:
            note = await asyncio.to_thread(self._run_llm_session, world, actor)
            self.last_thought = note
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM decision failed for %s: %s — heuristic fallback", actor.id, exc)
            self.llm_mode = "fallback"
            self._heuristic(world, actor)
            self.last_thought = f"{actor.name}: LLM fail → heuristic ({exc})"
        finally:
            self.busy = False

    def _run_llm_session(self, world: World, actor: Actor) -> str:
        executor = ToolExecutor(world, actor)
        system = system_prompt_for(actor)
        user = build_actor_context(world, actor)
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

        for _ in range(self.llm.config.max_tool_rounds):
            resp = self.llm.chat(
                system=system,
                user=user,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
            msg = resp.message
            messages.append(msg)
            tool_calls = parse_tool_calls(msg)
            if not tool_calls:
                content = (msg.get("content") or "").strip()
                return f"{actor.name} [LLM]: {content or 'no tool calls'}"

            for name, args, call_id in tool_calls:
                result = executor.execute(name, args)
                tool_msg: dict[str, Any] = {
                    "role": "tool",
                    "content": str(result),
                }
                if call_id:
                    tool_msg["tool_call_id"] = call_id
                # Ollama also accepts name on tool messages
                tool_msg["name"] = name
                messages.append(tool_msg)
                if name == "done":
                    return f"{actor.name} [LLM]: {executor.done_note or 'done'} | {'; '.join(executor.log)}"

        if executor.log:
            return f"{actor.name} [LLM]: {'; '.join(executor.log)}"
        return f"{actor.name} [LLM]: max rounds reached"

    def _heuristic(self, world: World, actor: Actor) -> None:
        if actor.kind == "city":
            self._heuristic_city(world, actor)  # type: ignore[arg-type]
        else:
            self._heuristic_company(world, actor)

    def _road_candidates_near(self, world: World, cx: int, cy: int, radius: int) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int]] = []
        for tile in world.grid.tiles:
            if abs(tile.x - cx) + abs(tile.y - cy) > radius:
                continue
            if tile.kind.value == "empty":
                if any(world.grid.get(nx, ny).kind.value == "road" for nx, ny in world.grid.neighbors4(tile.x, tile.y)):
                    candidates.append((tile.x, tile.y))
            elif tile.kind.value == "plot" and tile.plot and tile.plot.owner_id is None:
                if any(world.grid.get(nx, ny).kind.value == "road" for nx, ny in world.grid.neighbors4(tile.x, tile.y)):
                    candidates.append((tile.x, tile.y))
        return candidates

    def _heuristic_city(self, world: World, city: City) -> None:
        owned = world.owned_plots("city", city.id)
        foundry_cost = world.buildings.get("foundry").build_cost
        for t in owned:
            if t.plot and t.plot.building is None and city.cash >= foundry_cost:
                try:
                    world.build_building("city", city.id, t.x, t.y)
                    self.last_thought = f"{city.name}: built foundry at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{city.name}: build failed ({exc})"
                    return

        candidates = self._road_candidates_near(world, city.center_x, city.center_y, radius=8)
        candidates.sort(
            key=lambda p: (
                0 if world.grid.get(p[0], p[1]).city_id == city.id else 1,
                -(abs(p[0] - city.center_x) + abs(p[1] - city.center_y)),
            )
        )
        if candidates and city.cash >= world.config.road_build_cost:
            x, y = candidates[0]
            try:
                world.city_build_road(city.id, x, y)
                self.last_thought = f"{city.name}: built road at ({x},{y})"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{city.name}: road failed ({exc})"
                return

        for t in world.grid.tiles:
            if (
                t.kind.value == "plot"
                and t.plot
                and t.plot.owner_id is None
                and t.city_id == city.id
                and city.cash >= t.plot.price
            ):
                try:
                    world.buy_plot("city", city.id, t.x, t.y)
                    self.last_thought = f"{city.name}: claimed plot ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{city.name}: claim failed ({exc})"
                    return

        self.last_thought = f"{city.name}: administering territory ({len(city.territory)} cells)"

    def _heuristic_company(self, world: World, company: Actor) -> None:
        owned = world.owned_plots("company", company.id)
        if not owned:
            unowned = [
                t
                for t in world.grid.tiles
                if t.kind.value == "plot"
                and t.plot
                and t.plot.owner_id is None
                and t.plot.price <= company.cash
            ]
            unowned.sort(key=lambda t: t.plot.price)  # type: ignore[union-attr]
            if unowned:
                t = unowned[0]
                try:
                    world.buy_plot("company", company.id, t.x, t.y)
                    if company.cash >= world.buildings.get("foundry").build_cost:
                        world.build_building("company", company.id, t.x, t.y)
                    self.last_thought = f"{company.name}: bought at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: buy failed ({exc})"
                    return

        foundry_cost = world.buildings.get("foundry").build_cost
        for t in owned:
            if t.plot and t.plot.building is None and company.cash >= foundry_cost:
                try:
                    world.build_building("company", company.id, t.x, t.y)
                    self.last_thought = f"{company.name}: built foundry at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: build failed ({exc})"
                    return

        if owned and company.cash >= world.config.road_build_cost:
            ox, oy = owned[0].x, owned[0].y
            candidates = self._road_candidates_near(world, ox, oy, radius=5)
            if candidates:
                x, y = candidates[0]
                try:
                    world.company_build_road(company.id, x, y)
                    self.last_thought = f"{company.name}: built road at ({x},{y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: road failed ({exc})"

        for t in owned:
            for nx, ny in world.grid.neighbors4(t.x, t.y):
                n = world.grid.get(nx, ny)
                if (
                    n.kind.value == "plot"
                    and n.plot
                    and n.plot.owner_kind == "company"
                    and n.plot.owner_id == company.id
                    and n.plot.parcel_id != t.plot.parcel_id
                ):
                    try:
                        world.merge_plots("company", company.id, t.x, t.y, nx, ny)
                        self.last_thought = f"{company.name}: merged plots"
                        return
                    except Exception:
                        pass

        self.last_thought = f"{company.name}: holding"
