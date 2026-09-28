"""Assert engine writes the right data into the right save files."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

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


def test_new_game_writes_all_save_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        assert (root / "world.txt").is_file()
        assert (root / "market.txt").is_file()
        for aid in ("player", "ai_1", "ai_2", "city_a"):
            assert (root / "agents" / f"{aid}.txt").is_file(), aid


def test_world_file_has_world_not_agent_inventory():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        text = (root / "world.txt").read_text(encoding="utf-8")
        assert text.startswith("=== WORLD ===")
        assert "file: world.txt" in text
        assert "day:" in text
        assert "map:" in text
        assert "-- owned plots --" in text
        assert "turn_queue:" in text
        # World file must NOT hold private agent inventory blocks
        assert "inventory:" not in text
        assert "=== MARKET ===" not in text
        assert "=== AGENT" not in text
        # Roster lists ids, not cash balances
        assert "cash=" not in text


def test_market_file_has_market_only():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        text = (root / "market.txt").read_text(encoding="utf-8")
        assert text.startswith("=== MARKET ===")
        assert "file: market.txt" in text
        assert "inventory:" in text
        assert "listing_count:" in text
        assert "-- sell listings" in text
        assert "-- buy listings" in text
        # Market file must not contain map / agent private sections
        assert "=== WORLD ===" not in text
        assert "=== AGENT" not in text
        assert "-- owned plots --" not in text
        assert "acted_this_day" not in text


def test_agent_file_has_only_that_agent():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        ai1 = (root / "agents" / "ai_1.txt").read_text(encoding="utf-8")
        assert ai1.startswith("=== AGENT company:ai_1 ===")
        assert "file: agents/ai_1.txt" in ai1
        assert "cash:" in ai1
        assert "inventory:" in ai1
        assert "acted_this_day:" in ai1
        assert "-- plots" in ai1
        assert "-- my market listings" in ai1
        assert "is_player:" in ai1
        # Must not leak other agents or full market book
        assert "=== AGENT company:ai_2 ===" not in ai1
        assert "=== AGENT company:player ===" not in ai1
        assert "=== MARKET ===" not in ai1
        assert "=== WORLD ===" not in ai1

        city = (root / "agents" / "city_a.txt").read_text(encoding="utf-8")
        assert city.startswith("=== AGENT city:city_a ===")
        assert "population:" in city
        assert "territory_cells:" in city
        assert "is_player:" not in city


def test_action_updates_correct_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        player = w.companies["player"]
        cash_before = player.cash
        owned = w.owned_plots("company", "player")
        t = owned[0]

        w.build_building("company", "player", t.x, t.y, "foundry")

        agent_txt = (root / "agents" / "player.txt").read_text(encoding="utf-8")
        assert f"cash: {player.cash}" in agent_txt
        assert player.cash == cash_before - 200
        assert "type=foundry" in agent_txt or "foundry" in agent_txt
        assert "status=idle" in agent_txt

        world_txt = (root / "world.txt").read_text(encoding="utf-8")
        assert "foundry" in world_txt
        assert f"owner=company:player" in world_txt

        # Market unchanged shape still present
        market_txt = (root / "market.txt").read_text(encoding="utf-8")
        assert market_txt.startswith("=== MARKET ===")


def test_sell_writes_listing_to_market_and_agent():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.companies["ai_1"].inventory.set("steel", 4)
        w.post_sell("company", "ai_1", "steel", 2, price=33)

        market_txt = (root / "market.txt").read_text(encoding="utf-8")
        assert re.search(r"#\d+ sell 2x steel @ 33/u by company:ai_1", market_txt)
        assert "steel" in market_txt

        agent_txt = (root / "agents" / "ai_1.txt").read_text(encoding="utf-8")
        assert "sell 2x steel @ 33/u" in agent_txt
        assert "'steel': 2" in agent_txt or '"steel": 2' in agent_txt or "steel': 2" in agent_txt

        # Other agent's "my market listings" must not include ai_1's steel sell
        other = (root / "agents" / "ai_2.txt").read_text(encoding="utf-8")
        assert "steel @ 33/u by company:ai_1" not in other
        assert "sell 2x steel @ 33/u" not in other.split("-- my market listings")[1].split("-- mail")[0]


def test_day_advance_persists_new_day():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.pass_turn("company", "player")
        w.pass_turn("company", "ai_1")
        w.pass_turn("company", "ai_2")
        assert w.day == 2
        world_txt = (root / "world.txt").read_text(encoding="utf-8")
        assert "day: 2" in world_txt
        player_txt = (root / "agents" / "player.txt").read_text(encoding="utf-8")
        assert "day: 2" in player_txt
        assert "acted_this_day: False" in player_txt


def test_llm_context_bundle_reads_three_files_only():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        bundle = w.persistence.load_context_for_agent(w, w.companies["ai_1"])
        assert bundle.count("=== WORLD ===") == 1
        assert bundle.count("=== MARKET ===") == 1
        assert "=== AGENT company:ai_1 ===" in bundle
        assert "=== AGENT company:ai_2 ===" not in bundle
        assert "=== AGENT company:player ===" not in bundle
        assert "You control ONLY the agent above" in bundle
