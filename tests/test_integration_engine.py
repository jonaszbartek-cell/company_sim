"""Integration checks for messaging, sequential AI turns, and LLM file scope."""

from __future__ import annotations

import tempfile
from pathlib import Path

from company_sim.ai.scheduler import AIScheduler
from company_sim.ai.tools import ToolExecutor
from company_sim.mailboxes import pair_filename
from company_sim.world import World, WorldConfig


def _world(tmp: Path) -> World:
    return World.new_game(
        WorldConfig(
            map_width=18,
            map_height=12,
            starting_cities=1,
            ai_company_count=2,
            save_dir=str(tmp),
            min_seconds_between_turns=0.0,
        )
    )


def test_agent_to_agent_and_player_messaging_via_tools():
    """AGENT↔AGENT and AGENT↔USER (player) through World + ToolExecutor."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)

        # Agent → agent
        r1 = w.send_message("company", "ai_1", "ai_2", "Rival: trade coal?")
        assert r1.ok
        # Agent → player
        r2 = w.send_message("company", "ai_1", "player", "Player: open to buy steel?")
        assert r2.ok
        # Player → agent
        r3 = w.send_message("company", "player", "ai_1", "Sure, 35/u for steel.")
        assert r3.ok
        # City → player
        r4 = w.send_message("city", "city_a", "player", "Tax notice for day 1.")
        assert r4.ok

        # Tool path (what the LLM uses)
        ex = ToolExecutor(w, w.companies["ai_2"])
        out = ex.execute("send_message", {"to": "player", "body": "ai_2 greets player"})
        assert out["ok"] is True
        out2 = ex.execute("list_contacts", {})
        keys = {c["key"] for c in out2["data"]["contacts"]}
        assert "company:ai_1" in keys
        assert "company:player" in keys
        assert "city:city_a" in keys

        # Files on disk
        aa = root / "mailboxes" / pair_filename("company:ai_1", "company:ai_2")
        ap = root / "mailboxes" / pair_filename("company:ai_1", "company:player")
        assert "Rival: trade coal?" in aa.read_text(encoding="utf-8")
        assert "Sure, 35/u for steel." in ap.read_text(encoding="utf-8")
        assert "ai_2 greets player" in (
            root / "mailboxes" / pair_filename("company:ai_2", "company:player")
        ).read_text(encoding="utf-8")


def test_scheduler_advances_to_next_company_after_turn():
    """When current AI finishes, engine hands off to the next in queue."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        sched = AIScheduler()
        # LLM disabled → heuristic path
        assert sched.llm_mode == "off"

        queue = w.turn_queue_ids()
        assert queue == ["company:ai_1", "company:ai_2", "city:city_a"]
        assert w.current_turn_token() == "company:ai_1"

        # First AI turn
        w.time_sec = 10.0
        sched.update(w)
        assert w.companies["ai_1"].acted_this_day is True
        assert w.current_turn_token() == "company:ai_2"
        assert "Rival 1" in sched.last_thought

        # Second AI turn
        w.time_sec = 20.0
        sched.update(w)
        assert w.companies["ai_2"].acted_this_day is True
        assert w.current_turn_token() == "city:city_a"
        assert "Rival 2" in sched.last_thought

        # City turn
        w.time_sec = 30.0
        sched.update(w)
        assert w.grid.cities["city_a"].acted_this_day is True
        # Queue wraps to ai_1
        assert w.current_turn_token() == "company:ai_1"
        assert "Millhaven" in sched.last_thought

        # Player still needs to act for day advance
        assert w.day == 1
        w.pass_turn("company", "player")
        # Day advances when all companies acted (player + ai_1 + ai_2)
        assert w.day == 2


def test_llm_context_scoped_to_current_company_files():
    """Acting company gets world + market + own agent file + own mail only."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)

        # Distinct private state per company
        w.companies["ai_1"].cash = 1111
        w.companies["ai_1"].inventory.set("steel", 7)
        w.companies["ai_2"].cash = 2222
        w.companies["ai_2"].inventory.set("steel", 3)
        w.companies["player"].cash = 3333

        w.send_message("company", "ai_1", "ai_2", "PRIVATE_AI1_AI2")
        w.send_message("company", "player", "city_a", "PRIVATE_PLAYER_CITY")
        w.send_message("company", "ai_1", "player", "VISIBLE_TO_AI1_AND_PLAYER")

        # Give ai_1 a distinctive market listing
        w.companies["ai_1"].inventory.set("coal", 5)
        w.post_sell("company", "ai_1", "coal", 2, price=19)

        bundle_ai1 = w.persistence.load_context_for_agent(w, w.companies["ai_1"])
        bundle_ai2 = w.persistence.load_context_for_agent(w, w.companies["ai_2"])
        bundle_player = w.persistence.load_context_for_agent(w, w.companies["player"])

        # Shared world + market in every bundle
        for b in (bundle_ai1, bundle_ai2, bundle_player):
            assert "=== WORLD ===" in b
            assert "file: world.txt" in b
            assert "=== MARKET ===" in b
            assert "file: market.txt" in b
            assert "sell 2x coal @ 19/u" in b  # market board is shared

        # Own agent section only
        assert "=== AGENT company:ai_1 ===" in bundle_ai1
        assert "cash: 1111" in bundle_ai1
        assert "'steel': 7" in bundle_ai1 or "steel': 7" in bundle_ai1
        assert "=== AGENT company:ai_2 ===" not in bundle_ai1
        assert "cash: 2222" not in bundle_ai1
        assert "cash: 3333" not in bundle_ai1

        assert "=== AGENT company:ai_2 ===" in bundle_ai2
        assert "cash: 2222" in bundle_ai2
        assert "=== AGENT company:ai_1 ===" not in bundle_ai2
        assert "cash: 1111" not in bundle_ai2

        # Mail scoping: each agent only sees threads they participate in
        assert "PRIVATE_AI1_AI2" in bundle_ai1
        assert "PRIVATE_AI1_AI2" in bundle_ai2
        assert "PRIVATE_AI1_AI2" not in bundle_player

        assert "PRIVATE_PLAYER_CITY" in bundle_player
        assert "PRIVATE_PLAYER_CITY" not in bundle_ai1
        assert "PRIVATE_PLAYER_CITY" not in bundle_ai2

        assert "VISIBLE_TO_AI1_AND_PLAYER" in bundle_ai1
        assert "VISIBLE_TO_AI1_AND_PLAYER" in bundle_player
        assert "VISIBLE_TO_AI1_AND_PLAYER" not in bundle_ai2

        # Agent file lists only that agent's open listings
        assert "sell 2x coal @ 19/u" in (root / "agents" / "ai_1.txt").read_text(encoding="utf-8")
        ai2_agent = (root / "agents" / "ai_2.txt").read_text(encoding="utf-8")
        assert "-- my market listings (0) --" in ai2_agent or (
            "my market listings" in ai2_agent and "(none)" in ai2_agent.split("my market listings")[1][:80]
        )

        # On-disk world must not leak private cash
        world_txt = (root / "world.txt").read_text(encoding="utf-8")
        assert "cash: 1111" not in world_txt
        assert "inventory:" not in world_txt


def test_scheduler_loads_context_before_heuristic_turn():
    """Context bundle for the current company is loadable when their turn starts."""
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        actor = w.current_turn_actor()
        assert actor is not None
        assert actor.id == "ai_1"
        ctx = w.persistence.load_context_for_agent(w, actor)
        assert f"=== AGENT company:{actor.id} ===" in ctx
        assert "=== WORLD ===" in ctx
        assert "=== MARKET ===" in ctx
        assert "=== MAIL (your conversations) ===" in ctx
        # Contacts in agent file match C(n-1,1) = 3 for 4 agents
        contacts = w.mail().list_contacts(actor.kind, actor.id)
        assert len(contacts) == 3
