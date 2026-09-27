"""Text-file persistence for LLM agent context.

File layout under saves/ — each file has a hard content contract:

  world.txt
    Shared world only: day, pause, map size, agent roster (ids only),
    turn queue, owned-plot map overview, unowned plot count.
    Does NOT contain any agent's cash/inventory details.

  market.txt
    Market only: market inventory, escrow cash, indexed buy/sell listings.
    Does NOT contain agent private state or map plots.

  agents/<id>.txt
    That agent only: id/name/kind/cash/inventory/acted flag,
    owned plots + buildings, that agent's open market listings,
    city-only territory fields / company-only is_player.
    Does NOT contain other agents' cash/inventory or full market book.

  mailboxes/<a>__<b>.txt
    Shared conversation for one unordered pair of actors (all combinations
    generated at startup). Messages are AGENT↔AGENT and AGENT↔USER.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from company_sim.map_grid import TileKind

if TYPE_CHECKING:
    from company_sim.actors import Actor
    from company_sim.market import Market
    from company_sim.world import World


def default_save_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "saves"


class GamePersistence:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_save_dir()
        self.agents_dir = self.root / "agents"

    def ensure_dirs(self) -> None:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "mailboxes").mkdir(parents=True, exist_ok=True)

    def world_path(self) -> Path:
        return self.root / "world.txt"

    def market_path(self) -> Path:
        return self.root / "market.txt"

    def agent_path(self, agent_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in agent_id)
        return self.agents_dir / f"{safe}.txt"

    # --- public save API -------------------------------------------------

    def save_world(self, world: World) -> Path:
        self.ensure_dirs()
        path = self.world_path()
        path.write_text(self.render_world(world), encoding="utf-8")
        return path

    def save_market(self, market: Market) -> Path:
        self.ensure_dirs()
        path = self.market_path()
        path.write_text(self.render_market(market), encoding="utf-8")
        return path

    def save_agent(self, world: World, actor: Actor) -> Path:
        self.ensure_dirs()
        path = self.agent_path(actor.id)
        path.write_text(self.render_agent(world, actor), encoding="utf-8")
        return path

    def save_mailboxes(self, world: World) -> list[Path]:
        self.ensure_dirs()
        if world.mailboxes is None:
            return []
        world.mailboxes.ensure_all_pairs(world.iter_all_actors())
        return world.mailboxes.save_all()

    def save_proposals(self, world: World) -> Path:
        self.ensure_dirs()
        path = self.root / "proposals.txt"
        path.write_text(world.proposals.to_text(), encoding="utf-8")
        return path

    def save_all(self, world: World) -> dict[str, Path]:
        """Write world + market + every agent + all mailboxes + proposals."""
        written: dict[str, Path] = {
            "world": self.save_world(world),
            "market": self.save_market(world.market),
            "proposals": self.save_proposals(world),
        }
        for actor in world.iter_all_actors():
            written[f"agent:{actor.id}"] = self.save_agent(world, actor)
        for path in self.save_mailboxes(world):
            written[f"mail:{path.name}"] = path
        return written

    def load_context_for_agent(self, world: World, actor: Actor) -> str:
        """
        Refresh all saves, then return the bundle for this agent:
        world + market + proposals + agents/<this>.txt + this agent's mailboxes.
        """
        self.save_all(world)
        world_txt = self.world_path().read_text(encoding="utf-8")
        market_txt = self.market_path().read_text(encoding="utf-8")
        proposals_txt = (self.root / "proposals.txt").read_text(encoding="utf-8")
        agent_txt = self.agent_path(actor.id).read_text(encoding="utf-8")
        mail_txt = ""
        if world.mailboxes is not None:
            mail_txt = world.mailboxes.render_for_agent(actor.kind, actor.id)
        # Filter proposals text to this agent's pending involvements (full file still on disk)
        mine = world.proposals.pending_for(actor.kind, actor.id)
        mine_txt = "=== YOUR PENDING PROPOSALS ===\n"
        if mine:
            mine_txt += "\n".join(p.to_text_line() for p in mine) + "\n"
        else:
            mine_txt += "(none)\n"
        return (
            f"{world_txt}"
            f"{market_txt}"
            f"{proposals_txt}"
            f"{mine_txt}\n"
            f"{agent_txt}"
            f"{mail_txt}"
            "---\n"
            "You control ONLY the agent above. Use tools to act "
            "(market orders, retract, direct propose_sell/propose_buy, send_message), then call done.\n"
        )

    # --- renderers (one concern each) ------------------------------------

    def render_world(self, world: World) -> str:
        """Shared world snapshot — no per-agent cash/inventory."""
        company_ids = [
            f"{c.id}({'player' if c.is_player else 'ai'}, acted={c.acted_this_day})"
            for c in world.companies.values()
        ]
        city_ids = [
            f"{c.id}(acted={c.acted_this_day})"
            for c in world.grid.cities.values()
        ]
        n_agents = len(list(world.iter_all_actors()))
        mail_n = len(world.mailboxes.boxes) if world.mailboxes else 0
        owned_lines: list[str] = []
        for t in world.grid.tiles:
            if t.kind != TileKind.PLOT or not t.plot or not t.plot.owner_id:
                continue
            b = t.plot.building
            if b:
                bstr = f"{b.id}:{b.building_id}[{b.status}] method={b.production_method_id}"
            else:
                bstr = "none"
            owned_lines.append(
                f"  {t.plot.id} ({t.x},{t.y}) type={t.plot.plot_type.value} "
                f"size={world.grid.parcel_size(t.plot.parcel_id)} "
                f"owner={t.plot.owner_kind}:{t.plot.owner_id} "
                f"value={t.plot.value} price={t.plot.price} building={bstr}"
            )

        unowned_lines: list[str] = []
        unowned_count = 0
        for t in world.grid.tiles:
            if t.kind != TileKind.PLOT or not t.plot or t.plot.owner_id is not None:
                continue
            unowned_count += 1
            if len(unowned_lines) < 24:
                unowned_lines.append(
                    f"  ({t.x},{t.y}) type={t.plot.plot_type.value} "
                    f"price={t.plot.price} value={t.plot.value} city={t.city_id}"
                )

        lines = [
            "=== WORLD ===",
            "file: world.txt",
            f"day: {world.day}",
            f"paused: {world.paused}",
            f"map: {world.grid.width}x{world.grid.height}",
            f"companies: {', '.join(company_ids)}",
            f"cities: {', '.join(city_ids)}",
            f"agents: {n_agents}",
            f"mailbox_pairs: {mail_n} (expected C({n_agents},2)={n_agents * (n_agents - 1) // 2})",
            f"turn_queue: {world.turn_queue_ids()}",
            f"current_turn: {world.current_turn_token()}",
            "",
            "-- owned plots --",
        ]
        if owned_lines:
            lines.extend(owned_lines)
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"-- unowned plots ({unowned_count}) --")
        if unowned_lines:
            lines.extend(unowned_lines)
            if unowned_count > len(unowned_lines):
                lines.append(f"  ... +{unowned_count - len(unowned_lines)} more")
        else:
            lines.append("  (none)")
        lines.append("")
        return "\n".join(lines) + "\n"

    def render_market(self, market: Market) -> str:
        """Market board only."""
        body = market.to_text()
        lines = body.splitlines()
        if lines and lines[0].startswith("=== MARKET ==="):
            lines.insert(1, "file: market.txt")
        else:
            lines.insert(0, "file: market.txt")
        return "\n".join(lines) + "\n"

    def render_agent(self, world: World, actor: Actor) -> str:
        """One agent's private state only."""
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
                f"size={world.grid.parcel_size(t.plot.parcel_id)} "
                f"value={t.plot.value} {binfo}"
            )

        my_listings = [
            L
            for L in world.market.listings.values()
            if L.owner_kind == actor.kind and L.owner_id == actor.id
        ]
        my_listings.sort(key=lambda L: (L.side, L.item_id, L.id))

        contacts: list[dict] = []
        if world.mailboxes is not None:
            contacts = world.mailboxes.list_contacts(actor.kind, actor.id)

        lines = [
            f"=== AGENT {actor.kind}:{actor.id} ===",
            f"file: agents/{actor.id}.txt",
            f"name: {actor.name}",
            f"kind: {actor.kind}",
            f"id: {actor.id}",
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

        lines.append("")
        lines.append(f"-- my market listings ({len(my_listings)}) --")
        if my_listings:
            lines.extend(f"  {L.to_text_line()}" for L in my_listings)
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append(f"-- mail contacts ({len(contacts)}) --")
        if contacts:
            for c in contacts:
                lines.append(f"  {c['key']} messages={c['message_count']} file={c['filename']}")
        else:
            lines.append("  (none)")

        if actor.kind == "city":
            from company_sim.actors import City

            assert isinstance(actor, City)
            lines.append("")
            lines.append("-- city --")
            lines.append(f"population: {actor.population}")
            lines.append(f"center: ({actor.center_x},{actor.center_y})")
            lines.append(f"territory_cells: {len(actor.territory)}")
        if actor.kind == "company":
            from company_sim.actors import Company

            assert isinstance(actor, Company)
            lines.append("")
            lines.append("-- company --")
            lines.append(f"is_player: {actor.is_player}")
        lines.append("")
        return "\n".join(lines) + "\n"
