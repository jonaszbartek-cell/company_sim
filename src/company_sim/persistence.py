"""Text-file persistence for LLM agent context.

Layout (default under saves/):
  world.txt          — day, map summary, plot ownership overview
  market.txt         — listings + market inventory
  agents/<id>.txt    — one file per agent (company or city)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from company_sim.map_grid import TileKind

if TYPE_CHECKING:
    from company_sim.actors import Actor
    from company_sim.world import World


def default_save_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "saves"


class GamePersistence:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_save_dir()
        self.agents_dir = self.root / "agents"

    def ensure_dirs(self) -> None:
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    def world_path(self) -> Path:
        return self.root / "world.txt"

    def market_path(self) -> Path:
        return self.root / "market.txt"

    def agent_path(self, agent_id: str) -> Path:
        safe = agent_id.replace("/", "_")
        return self.agents_dir / f"{safe}.txt"

    def save_all(self, world: World) -> None:
        self.ensure_dirs()
        self.world_path().write_text(self.render_world(world), encoding="utf-8")
        self.market_path().write_text(world.market.to_text(), encoding="utf-8")
        for actor in world.iter_all_actors():
            self.agent_path(actor.id).write_text(self.render_agent(world, actor), encoding="utf-8")

    def load_context_for_agent(self, world: World, actor: Actor) -> str:
        """
        Refresh files, then return the three-file bundle the LLM should see
        for this agent: world + market + this agent's file.
        """
        self.save_all(world)
        world_txt = self.world_path().read_text(encoding="utf-8")
        market_txt = self.market_path().read_text(encoding="utf-8")
        agent_txt = self.agent_path(actor.id).read_text(encoding="utf-8")
        return (
            f"{world_txt}\n"
            f"{market_txt}\n"
            f"{agent_txt}\n"
            "---\n"
            "You control ONLY the agent above. Use tools to act, then call done.\n"
        )

    def render_world(self, world: World) -> str:
        companies = ", ".join(
            f"{c.id}({'P' if c.is_player else 'AI'}, cash={c.cash}, acted={c.acted_this_day})"
            for c in world.companies.values()
        )
        cities = ", ".join(
            f"{c.id}(pop={c.population}, cash={c.cash}, acted={c.acted_this_day})"
            for c in world.grid.cities.values()
        )
        owned_lines: list[str] = []
        for t in world.grid.tiles:
            if t.kind != TileKind.PLOT or not t.plot or not t.plot.owner_id:
                continue
            b = t.plot.building
            bstr = "none"
            if b:
                bstr = f"{b.building_id}[{b.status}] method={b.production_method_id}"
            owned_lines.append(
                f"  plot {t.plot.id} ({t.x},{t.y}) type={t.plot.plot_type.value} "
                f"size={world.grid.parcel_size(t.plot.parcel_id)} "
                f"owner={t.plot.owner_kind}:{t.plot.owner_id} "
                f"value={t.plot.value} building={bstr}"
            )
        lines = [
            "=== WORLD ===",
            f"day: {world.day}",
            f"paused: {world.paused}",
            f"map: {world.grid.width}x{world.grid.height}",
            f"companies: {companies}",
            f"cities: {cities}",
            f"turn_queue: {world.turn_queue_ids()}",
            f"current_turn: {world.current_turn_token()}",
            "",
            "-- owned plots --",
        ]
        if owned_lines:
            lines.extend(owned_lines)
        else:
            lines.append("  (none)")
        unowned = sum(
            1
            for t in world.grid.tiles
            if t.kind == TileKind.PLOT and t.plot and t.plot.owner_id is None
        )
        lines.append("")
        lines.append(f"unowned_plots: {unowned}")
        return "\n".join(lines) + "\n"

    def render_agent(self, world: World, actor: Actor) -> str:
        owned = world.owned_plots(actor.kind, actor.id)
        plot_lines: list[str] = []
        for t in owned:
            assert t.plot is not None
            b = t.plot.building
            if b:
                methods = [m.id for m in world.content.methods_for_building(b.building_id)]
                binfo = (
                    f"building id={b.id} type={b.building_id} status={b.status} "
                    f"method={b.production_method_id} possible={methods}"
                )
            else:
                binfo = "building=none"
            plot_lines.append(
                f"  {t.plot.id} @({t.x},{t.y}) type={t.plot.plot_type.value} "
                f"size={world.grid.parcel_size(t.plot.parcel_id)} value={t.plot.value} {binfo}"
            )
        lines = [
            f"=== AGENT {actor.kind}:{actor.id} ===",
            f"name: {actor.name}",
            f"kind: {actor.kind}",
            f"cash: {actor.cash}",
            f"inventory: {actor.inventory.as_dict() or '{}'}",
            f"acted_this_day: {actor.acted_this_day}",
            f"day: {world.day}",
            "",
            f"-- plots ({len(owned)}) --",
        ]
        if plot_lines:
            lines.extend(plot_lines)
        else:
            lines.append("  (none)")
        if actor.kind == "city":
            from company_sim.actors import City

            assert isinstance(actor, City)
            lines.append("")
            lines.append(f"population: {actor.population}")
            lines.append(f"center: ({actor.center_x},{actor.center_y})")
            lines.append(f"territory_cells: {len(actor.territory)}")
        if actor.kind == "company":
            from company_sim.actors import Company

            assert isinstance(actor, Company)
            lines.append("")
            lines.append(f"is_player: {actor.is_player}")
        return "\n".join(lines) + "\n"
