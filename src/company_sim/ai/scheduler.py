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

        # Small companies: deterministic engine script only (never LLM)
        from company_sim.actors import Company as CompanyCls

        if isinstance(actor, CompanyCls) and actor.is_small:
            self._run_small_company_turn(world, actor)
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
                self._run_heuristic_turn(world, actor)
            return

        self._run_heuristic_turn(world, actor)

    def _run_small_company_turn(self, world: World, actor: Actor) -> None:
        from company_sim.actors import Company as CompanyCls
        from company_sim.small_companies import run_small_company_turn

        try:
            assert isinstance(actor, CompanyCls)
            self.last_thought = run_small_company_turn(world, actor)
        finally:
            if not actor.acted_this_day:
                world.pass_turn(actor.kind, actor.id)
            world.persistence.save_all(world)
            world.advance_ai_turn()

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
        """
        Pack *this* actor's files into the prompt, run tools, optionally write a debug trace.

        The LLM never opens the filesystem. Isolation = host only reads this actor's
        instruction + private agent file (+ shared boards / their mail). Next turn
        rebuilds the prompt for the next actor from scratch.
        """
        from company_sim.agent_files import AgentFileStore

        if world.file_store is None:
            world.file_store = AgentFileStore(world.persistence.root)
        from company_sim.ai.tools import tool_definitions_for

        bundle = world.file_store.pack_for_agent(world, actor, compact=True)
        executor = ToolExecutor(world, actor)
        system = system_prompt_for(actor)
        tools = tool_definitions_for(actor)
        known_tools = {str(d["function"]["name"]) for d in tools}
        pending = world.proposals.pending_addressed_to(actor.kind, actor.id)
        owned = world.owned_plots(actor.kind, actor.id)
        if pending:
            bits = []
            for p in pending[:4]:
                bits.append(
                    f"#{p.id} {p.proposal_type} from {p.from_kind}:{p.from_id} "
                    f"total={p.total}"
                )
            now_hint = (
                "NOW: pending proposals for you — "
                + "; ".join(bits)
                + ". Call accept_proposal(proposal_id=…) for fair offers "
                "(plot_buy price>=80) or reject_proposal, then done."
            )
        elif actor.kind == "company" and not owned:
            now_hint = (
                "NOW: you own no land. Call list_plots_for_sale, then ONE propose_plot_buy, then done."
            )
        elif actor.kind == "company" and owned and all(
            t.plot and t.plot.building is None for t in owned
        ):
            t0 = owned[0]
            ptype = t0.plot.plot_type.value if t0.plot else "standard"
            if ptype == "specialized_mine":
                bid, mid = "mine", "extract_iron_ore"
            elif ptype == "specialized_well":
                bid, mid = "rig", "extract_oil"
            else:
                bid, mid = "foundry", "make_steel"
            now_hint = (
                f"NOW: you own empty plot(s) ({ptype}). Call build_building(x={t0.x}, y={t0.y}, "
                f"building_id=\"{bid}\", method_id=\"{mid}\") to choose the method at build, then done."
            )
        else:
            now_hint = (
                "NOW: call tools only. Start with get_status, take 1-2 useful actions, then done. "
                "To change an unlocked factory method anytime: set_production_method."
            )
        user = (
            bundle.prompt_text
            + "\n"
            + build_actor_context(world, actor)
            + "\n"
            + now_hint
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        rounds: list[dict[str, Any]] = []
        final_note = f"{actor.name} [LLM]: max rounds reached"

        for _ in range(self.llm.config.max_tool_rounds):
            resp = self.llm.chat(
                system=system,
                user=user,
                tools=tools,
                messages=messages,
            )
            msg = resp.message
            messages.append(msg)
            tool_calls = parse_tool_calls(msg, known_tools=known_tools)
            round_rec: dict[str, Any] = {
                "assistant_content": (msg.get("content") or "").strip(),
                "tool_calls": [],
                "tool_results": [],
            }
            if not tool_calls:
                content = (msg.get("content") or "").strip()
                rounds.append(round_rec)
                if executor.log:
                    final_note = f"{actor.name} [LLM]: {'; '.join(executor.log)}"
                else:
                    final_note = f"{actor.name} [LLM]: {content or 'no tool calls'}"
                self._write_debug(world, actor, system, bundle, rounds, final_note)
                return final_note

            done = False
            for name, args, call_id in tool_calls:
                round_rec["tool_calls"].append({"name": name, "arguments": args})
                result = executor.execute(name, args)
                round_rec["tool_results"].append(f"{name} → {result}")
                tool_msg: dict[str, Any] = {
                    "role": "tool",
                    "content": str(result),
                    "name": name,
                }
                if call_id:
                    tool_msg["tool_call_id"] = call_id
                messages.append(tool_msg)
                if name == "done":
                    done = True
            rounds.append(round_rec)
            if done:
                final_note = (
                    f"{actor.name} [LLM]: {executor.done_note or 'done'} | "
                    f"{'; '.join(executor.log)}"
                )
                self._write_debug(world, actor, system, bundle, rounds, final_note)
                return final_note

        if executor.log:
            final_note = f"{actor.name} [LLM]: {'; '.join(executor.log)}"
        self._write_debug(world, actor, system, bundle, rounds, final_note)
        return final_note

    def _write_debug(
        self,
        world: World,
        actor: Actor,
        system: str,
        bundle: Any,
        rounds: list[dict[str, Any]],
        final_note: str,
    ) -> None:
        dbg = world.llm_debug_log
        if dbg is None or not dbg.enabled:
            return
        path = dbg.write_turn(
            actor_kind=actor.kind,
            actor_id=actor.id,
            day=world.day,
            system=system,
            bundle=bundle,
            rounds=rounds,
            final_note=final_note,
        )
        if path is not None:
            log.info("LLM debug trace → %s", path)

    def _heuristic(self, world: World, actor: Actor) -> None:
        if actor.kind == "city":
            self._heuristic_city(world, actor)  # type: ignore[arg-type]
        else:
            self._heuristic_company(world, actor)

    def _edge_road_candidates(self, world: World, kind: str, actor_id: str) -> list[tuple[int, int, str]]:
        """Owned plots missing an edge road (prefer sides facing another owned plot)."""
        out: list[tuple[int, int, str]] = []
        for t in world.owned_plots(kind, actor_id):
            if not t.plot:
                continue
            for side in ("N", "E", "S", "W"):
                if t.plot.roads.get(side) or t.plot.combined.get(side):
                    continue
                out.append((t.x, t.y, side))
        return out

    def _heuristic_city(self, world: World, city: City) -> None:
        # Respond to pending plot proposals addressed to this city
        for prop in world.proposals.pending_for("city", city.id):
            if not (prop.to_kind == "city" and prop.to_id == city.id):
                continue
            try:
                if prop.proposal_type == "plot_buy" and prop.price >= 80:
                    world.accept_proposal("city", city.id, prop.id)
                    self.last_thought = f"{city.name}: accepted plot proposal #{prop.id}"
                    return
                world.reject_proposal("city", city.id, prop.id)
                self.last_thought = f"{city.name}: rejected proposal #{prop.id}"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{city.name}: proposal handling failed ({exc})"
                return

        # Award any open contract that already has bids
        for c in world.gov_contracts.open_contracts():
            if c.city_id == city.id and c.bids:
                try:
                    world.award_government_contract("city", city.id, c.id)
                    self.last_thought = f"{city.name}: awarded gov contract #{c.id}"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{city.name}: award failed ({exc})"
                    return

        # Post a small procurement if none open for this city
        mine_open = [c for c in world.gov_contracts.open_contracts() if c.city_id == city.id]
        mine_awarded = [
            c for c in world.gov_contracts.active() if c.city_id == city.id and c.status == "awarded"
        ]
        if not mine_open and not mine_awarded and city.cash >= 80:
            try:
                world.post_government_contract(
                    "city", city.id, {"iron_ore": 2, "coal": 2, "energy": 1}
                )
                self.last_thought = f"{city.name}: posted government contract"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{city.name}: contract failed ({exc})"

        owned = world.owned_plots("city", city.id)
        for t in owned:
            if t.plot and t.plot.building is None and city.cash >= 200 and t.plot.reserved_proposal_id is None:
                try:
                    world.build_building("city", city.id, t.x, t.y)
                    self.last_thought = f"{city.name}: built foundry at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{city.name}: build failed ({exc})"
                    return

        candidates = self._edge_road_candidates(world, "city", city.id)
        steel_need = world.config.road_build_steel
        if candidates and city.inventory.get("steel") >= steel_need:
            x, y, side = candidates[0]
            try:
                world.city_build_road(city.id, x, y, side)
                self.last_thought = f"{city.name}: built {side} road at ({x},{y})"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{city.name}: road failed ({exc})"
                return

        self.last_thought = f"{city.name}: administering (day {world.day})"

    def _heuristic_company(self, world: World, company: Actor) -> None:
        owned = world.owned_plots("company", company.id)

        # Accept/reject pending proposals addressed to this company
        for prop in world.proposals.pending_for("company", company.id):
            if not (prop.to_kind == "company" and prop.to_id == company.id):
                continue
            try:
                if prop.proposal_type in ("goods_sell", "plot_sell"):
                    if company.cash >= prop.total:
                        world.accept_proposal("company", company.id, prop.id)
                        self.last_thought = f"{company.name}: accepted #{prop.id}"
                        return
                elif prop.proposal_type in ("goods_buy", "plot_buy"):
                    world.accept_proposal("company", company.id, prop.id)
                    self.last_thought = f"{company.name}: accepted #{prop.id}"
                    return
                world.reject_proposal("company", company.id, prop.id)
                self.last_thought = f"{company.name}: rejected #{prop.id}"
                return
            except Exception:
                continue

        # Fulfill awarded government contracts if possible
        for c in world.gov_contracts.awarded_for_company(company.id):
            try:
                world.fulfill_government_contract("company", company.id, c.id)
                self.last_thought = f"{company.name}: fulfilled gov contract #{c.id}"
                return
            except Exception:
                # Try to buy missing inputs from market first
                for item_id, need in c.requirements.items():
                    have = company.inventory.get(item_id)
                    if have < need:
                        try:
                            world.buy_from_market("company", company.id, item_id, need - have)
                            self.last_thought = f"{company.name}: buying {item_id} for contract"
                            return
                        except Exception:
                            continue

        # Bid on open government contracts
        for c in world.gov_contracts.open_contracts():
            if company.id in c.bids:
                continue
            # Simple bid: 12 per unit
            total_units = sum(c.requirements.values())
            price = max(10, total_units * 12)
            if company.cash < 0:
                continue
            try:
                world.bid_government_contract("company", company.id, c.id, price)
                self.last_thought = f"{company.name}: bid {price} on gov #{c.id}"
                return
            except Exception:
                continue

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
            except Exception:
                pass

        # Produce if we have a building + inputs across owned building storage
        for t in owned:
            b = t.plot.building if t.plot else None
            if not b or not b.production_method_id or b.status == "working":
                continue
            try:
                method = world.production.get(b.production_method_id)
            except KeyError:
                continue
            # Deposit missing inputs from company inventory into this building
            owned_buildings = [
                (ot.x, ot.y, ot.plot.building)
                for ot in owned
                if ot.plot and ot.plot.building
            ]
            for item_id, need in method.inputs.items():
                in_storage = sum(ob.storage.get(item_id) for _x, _y, ob in owned_buildings)
                short = need - in_storage
                if short <= 0:
                    continue
                have = company.inventory.get(item_id)
                if have <= 0:
                    break
                try:
                    world.deposit_to_building(
                        "company", company.id, t.x, t.y, item_id, min(short, have)
                    )
                    self.last_thought = f"{company.name}: deposited {item_id} for {method.id}"
                    return
                except Exception:
                    break
            # Start multi-day batch when enough stock exists across owned buildings
            try:
                world.produce("company", company.id, t.x, t.y)
                self.last_thought = f"{company.name}: started {method.id}"
                return
            except Exception as exc:  # noqa: BLE001
                self.last_thought = f"{company.name}: produce failed ({exc})"
                continue

        # Withdraw finished goods from building storage into inventory
        for t in owned:
            b = t.plot.building if t.plot else None
            if not b:
                continue
            for item_id, qty in list(b.storage.as_dict().items()):
                if qty <= 0:
                    continue
                # Prefer withdrawing outputs (not leftover inputs)
                try:
                    method = (
                        world.production.get(b.production_method_id)
                        if b.production_method_id
                        else None
                    )
                except KeyError:
                    method = None
                if method and item_id in method.inputs and item_id not in method.outputs:
                    continue
                try:
                    world.withdraw_from_building(
                        "company", company.id, t.x, t.y, item_id, qty
                    )
                    self.last_thought = f"{company.name}: withdrew {qty}x {item_id}"
                    return
                except Exception:
                    continue

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
        for item_id in ("iron_ore", "coal", "energy"):
            if company.inventory.get(item_id) < 3:
                try:
                    world.buy_from_market("company", company.id, item_id, 2)
                    self.last_thought = f"{company.name}: bought {item_id}"
                    return
                except Exception:
                    continue

        # Build on empty owned plot
        for t in owned:
            if t.plot and t.plot.building is None and company.cash >= 200 and t.plot.reserved_proposal_id is None:
                try:
                    world.build_building("company", company.id, t.x, t.y)
                    self.last_thought = f"{company.name}: built foundry at ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: build failed ({exc})"
                    return

        # No land yet — offer to buy a cheap city plot
        if not owned:
            city_plots = [
                t
                for t in world.grid.tiles
                if t.plot
                and t.plot.owner_kind == "city"
                and t.plot.reserved_proposal_id is None
                and t.plot.value <= company.cash
            ]
            city_plots.sort(key=lambda t: t.plot.value)  # type: ignore[union-attr]
            if city_plots:
                t = city_plots[0]
                assert t.plot is not None
                price = t.plot.value
                try:
                    world.propose_plot_buy(
                        "company",
                        company.id,
                        f"city:{t.plot.owner_id}",
                        t.x,
                        t.y,
                        price,
                    )
                    self.last_thought = f"{company.name}: offered {price} for ({t.x},{t.y})"
                    return
                except Exception as exc:  # noqa: BLE001
                    self.last_thought = f"{company.name}: plot buy failed ({exc})"
                    return

        self.last_thought = f"{company.name}: holding (day {world.day})"
