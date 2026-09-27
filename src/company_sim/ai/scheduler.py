"""AI scheduler: sequential LLM agent turns (one mind at a time).

One game day advances when all companies have acted (see World.note_actor_action).
Turns can be slowed via min_seconds_between_turns — never sped up past that floor.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from company_sim.actors import Actor, City
from company_sim.ai.llm_client import LLMClient, parse_tool_calls
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
    Engine loop: LLM acts as current AI agent → when finished, next agent.

    Before each decision, world/market/agent text files are refreshed so the
    model prompt can load the three-file bundle for that company/city.
    """

    llm: LLMClient = field(default_factory=LLMClient)
    _last_turn_wall: float = -999.0
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

    def update(self, world: World) -> None:
        """Non-blocking. Called from the asyncio UI loop."""
        if world.paused or self.busy:
            return
        actor = world.current_turn_actor()
        if actor is None:
            return

        # Slow-down floor only (cannot speed past config.min_seconds_between_turns)
        min_gap = max(0.0, world.config.min_seconds_between_turns)
        if world.time_sec - self._last_turn_wall < min_gap:
            return

        # Skip AI mind if this agent already acted this day (wait for others / day roll)
        if actor.acted_this_day:
            world.advance_ai_turn()
            return

        self._last_turn_wall = world.time_sec

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
                self._run_heuristic_turn(world, actor)
            return

        self._run_heuristic_turn(world, actor)

    def _run_heuristic_turn(self, world: World, actor: Actor) -> None:
        try:
            context = world.persistence.load_context_for_agent(world, actor)
            log.debug("Agent context loaded (%d chars) for %s", len(context), actor.id)
            self._heuristic(world, actor)
        finally:
            if not actor.acted_this_day:
                world.pass_turn(actor.kind, actor.id)
            world.persistence.save_all(world)
            world.advance_ai_turn()

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
            if not actor.acted_this_day:
                try:
                    world.pass_turn(actor.kind, actor.id)
                except Exception:  # noqa: BLE001
                    actor.mark_acted()
            world.persistence.save_all(world)
            world.advance_ai_turn()
            self.busy = False

    def _run_llm_session(self, world: World, actor: Actor) -> str:
        # Refresh text files; feed world + market + this agent into the prompt
        file_bundle = world.persistence.load_context_for_agent(world, actor)
        executor = ToolExecutor(world, actor)
        system = system_prompt_for(actor)
        user = file_bundle + "\n" + build_actor_context(world, actor)
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
        for t in owned:
            if t.plot and t.plot.building is None and city.cash >= 200:
                try:
                    world.build_building("city", city.id, t.x, t.y)
                    self.last_thought = f"{city.name}: built foundry at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{city.name}: build failed ({exc})"
                    return

        # Prefer selling surplus steel / buying missing inputs later — for now claim land
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

        candidates = self._road_candidates_near(world, city.center_x, city.center_y, radius=8)
        if candidates and city.cash >= world.config.road_build_cost:
            x, y = candidates[0]
            try:
                world.city_build_road(city.id, x, y)
                self.last_thought = f"{city.name}: built road at ({x},{y})"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{city.name}: road failed ({exc})"
                return

        self.last_thought = f"{city.name}: administering (day {world.day})"

    def _heuristic_company(self, world: World, company: Actor) -> None:
        owned = world.owned_plots("company", company.id)

        # Occasionally ping the player / a rival (AGENT↔USER / AGENT↔AGENT)
        if world.day <= 2 or world.tick_index % 17 == 0:
            try:
                target = "player" if company.id != "player" else "ai_2"
                world.send_message(
                    "company",
                    company.id,
                    target,
                    f"{company.name}: open to trade steel/inputs on day {world.day}.",
                )
                self.last_thought = f"{company.name}: messaged {target}"
                # Fall through to also take an economic action this turn
            except Exception:
                pass

        # Produce if we have a foundry + inputs
        for t in owned:
            b = t.plot.building if t.plot else None
            if not b or not b.production_method_id:
                continue
            try:
                method = world.production.get(b.production_method_id)
            except KeyError:
                continue
            if company.inventory.has(method.inputs):
                try:
                    world.produce("company", company.id, t.x, t.y)
                    self.last_thought = f"{company.name}: produced {method.id}"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: produce failed ({exc})"
                    break

        # Sell steel if any
        steel = company.inventory.get("steel")
        if steel >= 1:
            try:
                world.post_sell("company", company.id, "steel", min(steel, 3), price=40)
                self.last_thought = f"{company.name}: posted steel sell"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{company.name}: sell failed ({exc})"

        # Buy cheapest missing input from market
        for item_id in ("iron", "coal", "energy"):
            if company.inventory.get(item_id) < 3:
                try:
                    world.buy_from_market("company", company.id, item_id, 2)
                    self.last_thought = f"{company.name}: bought {item_id}"
                    return
                except Exception:
                    continue

        # Build on empty owned plot
        for t in owned:
            if t.plot and t.plot.building is None and company.cash >= 200:
                try:
                    world.build_building("company", company.id, t.x, t.y)
                    self.last_thought = f"{company.name}: built foundry at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: build failed ({exc})"
                    return

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
                    self.last_thought = f"{company.name}: bought at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: buy failed ({exc})"
                    return

        self.last_thought = f"{company.name}: holding (day {world.day})"
