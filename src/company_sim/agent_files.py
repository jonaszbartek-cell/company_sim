"""Per-agent instruction files + LLM context packing + debug traces.

How the LLM gets files (important):
  The LLM process never browses the save directory. On each AI turn the
  Python host (AIScheduler) picks a small set of text files for the *current*
  actor, reads their contents, and concatenates them into the chat prompt.
  The next actor gets a freshly built prompt from *their* files instead.

What keeps agents from seeing each other's private state:
  1. Prompt packing lists only this actor's instruction + agent private file,
     this actor's mail threads, and shared public boards (world/market/gov/
     proposals). Other agents' ``agents/<other>.txt`` and instruction files
     are never opened for this turn.
  2. ToolExecutor is constructed with that same actor, so every tool call
     mutates only that actor's cash/inventory/plots (or public boards).
  3. Debug traces (optional) record exactly which paths were packed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from company_sim.actors import Actor
    from company_sim.world import World


def safe_id(agent_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in agent_id)


def instructions_filename(kind: str, agent_id: str) -> str:
    """e.g. COMPANY_INSTRUCTIONS_ai_1.txt / CITY_INSTRUCTIONS_city_a.txt"""
    prefix = "COMPANY_INSTRUCTIONS" if kind == "company" else "CITY_INSTRUCTIONS"
    return f"{prefix}_{safe_id(agent_id)}.txt"


@dataclass
class PackedFile:
    path: str
    role: str  # "private" | "shared" | "instructions" | "mail"
    chars: int


@dataclass
class AgentFileBundle:
    """Files selected for one agent turn."""

    actor_key: str
    files: list[PackedFile] = field(default_factory=list)
    prompt_text: str = ""

    def path_list(self) -> list[str]:
        return [f.path for f in self.files]


class AgentFileStore:
    """Creates instruction stubs and packs the prompt for an agent turn."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.instructions_dir = root / "instructions"
        self.debug_dir = root / "llm_debug"

    def ensure_dirs(self) -> None:
        self.instructions_dir.mkdir(parents=True, exist_ok=True)

    def instructions_path(self, kind: str, agent_id: str) -> Path:
        return self.instructions_dir / instructions_filename(kind, agent_id)

    def write_placeholder_instructions(self, kind: str, agent_id: str, name: str) -> Path:
        """Create COMPANY/CITY_INSTRUCTIONS_<id>.txt if missing (placeholder body)."""
        self.ensure_dirs()
        path = self.instructions_path(kind, agent_id)
        if path.exists():
            return path
        label = "COMPANY" if kind == "company" else "CITY"
        body = (
            f"=== {label} INSTRUCTIONS_{agent_id} ===\n"
            f"file: instructions/{path.name}\n"
            f"agent: {kind}:{agent_id}\n"
            f"name: {name}\n"
            "\n"
            "(placeholder) Put standing orders / personality / goals for this agent here.\n"
            "This file is included only when this agent is the active LLM turn.\n"
        )
        path.write_text(body, encoding="utf-8")
        return path

    def ensure_all_instructions(self, world: World) -> list[Path]:
        written: list[Path] = []
        for actor in world.iter_all_actors():
            written.append(
                self.write_placeholder_instructions(actor.kind, actor.id, actor.name)
            )
        return written

    def pack_for_agent(self, world: World, actor: Actor, *, compact: bool = True) -> AgentFileBundle:
        """
        Read only the files this actor is allowed to see and build the prompt.

        Private: instructions + agents/<id>.txt + this agent's mailboxes
        Shared:  world.txt, market.txt (companies), proposals.txt, gov contracts
                 + filtered pending proposals involving this actor
        """
        world.persistence.save_all(world)
        self.ensure_all_instructions(world)

        files: list[PackedFile] = []
        chunks: list[str] = []

        def add(path: Path, role: str, text: str | None = None, limit: int | None = None) -> None:
            if not path.exists():
                return
            raw = text if text is not None else path.read_text(encoding="utf-8")
            if limit is not None and len(raw) > limit:
                raw = raw[:limit] + "\n...[truncated]...\n"
            rel = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)
            files.append(PackedFile(path=rel, role=role, chars=len(raw)))
            chunks.append(raw if raw.endswith("\n") else raw + "\n")

        # 1) This agent's standing instructions only
        add(self.instructions_path(actor.kind, actor.id), "instructions")

        # 2) This agent's private state only
        add(world.persistence.agent_path(actor.id), "private")

        # 3) Shared boards (public knowledge — still no other agents' private files)
        add(world.persistence.world_path(), "shared", limit=4000 if compact else None)
        if actor.kind == "company":
            add(world.persistence.market_path(), "shared", limit=3000 if compact else None)
        gov = self.root / "government_contracts.txt"
        add(gov, "shared", limit=2500 if compact else None)
        proposals = self.root / "proposals.txt"
        add(proposals, "shared", limit=2500 if compact else None)
        # Economy catalogs — shared knowledge for every agent (goods / buildings / methods)
        goods = self.root / "goods_index.txt"
        buildings = self.root / "buildings_catalog.txt"
        methods = self.root / "production_methods_catalog.txt"
        if not goods.exists() or not buildings.exists() or not methods.exists():
            world.persistence.save_goods_index(world)
            world.persistence.save_buildings_catalog(world)
            world.persistence.save_methods_catalog(world)
        # Full catalogs (not truncated) so every agent can see all economy data
        add(goods, "shared")
        add(buildings, "shared")
        add(methods, "shared")

        # 4) Pending proposals involving this actor (derived filter, not another file)
        mine = world.proposals.pending_for(actor.kind, actor.id)
        mine_txt = "=== YOUR PENDING PROPOSALS ===\n"
        if mine:
            mine_txt += "\n".join(p.to_text_line() for p in mine) + "\n"
        else:
            mine_txt += "(none)\n"
        files.append(PackedFile(path="(derived)/pending_proposals", role="private", chars=len(mine_txt)))
        chunks.append(mine_txt)

        # 5) This agent's mail only
        if world.mailboxes is not None:
            mail_txt = world.mailboxes.render_for_agent(actor.kind, actor.id)
            files.append(
                PackedFile(path="mailboxes/(threads for this agent)", role="mail", chars=len(mail_txt))
            )
            chunks.append(mail_txt if mail_txt.endswith("\n") else mail_txt + "\n")

        access_note = (
            "=== FILE ACCESS ===\n"
            f"active_agent: {actor.kind}:{actor.id}\n"
            "The LLM cannot open files itself. Only the paths listed above were read "
            "into this prompt. Other agents' instructions/ and agents/ files were NOT included.\n"
        )
        chunks.append(access_note)
        files.append(PackedFile(path="(derived)/file_access_note", role="shared", chars=len(access_note)))

        prompt = "".join(chunks)
        return AgentFileBundle(
            actor_key=f"{actor.kind}:{actor.id}",
            files=files,
            prompt_text=prompt,
        )


class LLMDebugLog:
    """Writes per-turn traces when debug is enabled."""

    def __init__(self, root: Path, enabled: bool = False) -> None:
        self.root = root
        self.enabled = enabled
        self.debug_dir = root / "llm_debug"
        self._seq = 0
        self.last_trace_path: Path | None = None
        self.last_summary: str | None = None

    def ensure_dir(self) -> None:
        if self.enabled:
            self.debug_dir.mkdir(parents=True, exist_ok=True)

    def write_turn(
        self,
        *,
        actor_kind: str,
        actor_id: str,
        day: int,
        system: str,
        bundle: AgentFileBundle,
        rounds: list[dict],
        final_note: str,
    ) -> Path | None:
        if not self.enabled:
            return None
        self.ensure_dir()
        self._seq += 1
        folder = self.debug_dir / f"{actor_kind}_{safe_id(actor_id)}"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        path = folder / f"day{day}_seq{self._seq:04d}_{stamp}.txt"

        lines: list[str] = [
            "=== LLM DEBUG TRACE ===",
            f"time_utc: {datetime.now(timezone.utc).isoformat()}",
            f"agent: {actor_kind}:{actor_id}",
            f"day: {day}",
            f"seq: {self._seq}",
            "",
            "-- files packed into prompt --",
        ]
        for f in bundle.files:
            lines.append(f"  [{f.role}] {f.path} ({f.chars} chars)")
        lines.append("")
        lines.append("-- system prompt --")
        lines.append(system)
        lines.append("")
        lines.append("-- user prompt (packed files) --")
        lines.append(bundle.prompt_text)
        lines.append("")
        lines.append("-- rounds --")
        for i, rnd in enumerate(rounds, 1):
            lines.append(f"## round {i}")
            if rnd.get("assistant_content"):
                lines.append(f"assistant_content: {rnd['assistant_content']}")
            for tc in rnd.get("tool_calls") or []:
                lines.append(f"tool_call: {tc.get('name')}({tc.get('arguments')})")
            for tr in rnd.get("tool_results") or []:
                lines.append(f"tool_result: {tr}")
            lines.append("")
        lines.append("-- final note --")
        lines.append(final_note)
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        self.last_trace_path = path
        self.last_summary = (
            f"{actor_kind}:{actor_id} day={day} files={len(bundle.files)} "
            f"rounds={len(rounds)} → {path.name}"
        )
        # Also append a one-line index
        index = self.debug_dir / "index.log"
        with index.open("a", encoding="utf-8") as fh:
            fh.write(
                f"{datetime.now(timezone.utc).isoformat()} {actor_kind}:{actor_id} "
                f"day={day} {path.relative_to(self.debug_dir)}\n"
            )
        return path

    def recent_traces(self, limit: int = 20) -> list[dict]:
        if not self.debug_dir.exists():
            return []
        index = self.debug_dir / "index.log"
        if not index.exists():
            return []
        rows = index.read_text(encoding="utf-8").splitlines()
        out = []
        for line in rows[-limit:]:
            out.append({"line": line})
        return list(reversed(out))

    def read_trace(self, relative: str) -> str | None:
        path = (self.debug_dir / relative).resolve()
        if not str(path).startswith(str(self.debug_dir.resolve())):
            return None
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
