"""Market + day scheduling + text persistence."""

from __future__ import annotations

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


def test_seed_cast():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        assert len(w.companies) == 3  # player + 2 AI
        assert sum(1 for c in w.companies.values() if c.is_player) == 1
        assert len(w.grid.cities) == 1
        assert w.day == 1


def test_market_sell_and_lowest_price_buy():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 5)
        buyer.cash = 1000

        w.post_sell("company", "ai_1", "steel", 2, price=50)
        w.post_sell("company", "ai_1", "steel", 2, price=30)
        assert w.market.inventory.get("steel") == 4
        assert seller.inventory.get("steel") == 1

        before = buyer.cash
        r = w.buy_from_market("company", "player", "steel", 2)
        assert r.ok
        assert buyer.inventory.get("steel") == 2
        assert before - buyer.cash == 60  # 2 * 30 lowest
        assert seller.cash >= 1500 + 60


def test_day_advances_when_all_companies_act():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        assert w.day == 1
        w.pass_turn("company", "player")
        assert w.day == 1
        w.pass_turn("company", "ai_1")
        assert w.day == 1
        w.pass_turn("company", "ai_2")
        assert w.day == 2
        assert all(not c.acted_this_day for c in w.companies.values())


def test_produce_steel():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        player = w.companies["player"]
        owned = w.owned_plots("company", "player")
        assert owned
        t = owned[0]
        w.build_building("company", "player", t.x, t.y, "foundry")
        player.inventory = player.inventory.__class__({"iron": 2, "coal": 2, "energy": 2, "steel": 0})
        # build already marked acted; force another produce on same day by resetting flag
        player.acted_this_day = False
        r = w.produce("company", "player", t.x, t.y)
        assert r.ok
        assert player.inventory.get("steel") == 1
        assert t.plot.building.status == "working"


def test_persistence_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.persistence.save_all(w)
        assert (root / "world.txt").exists()
        assert (root / "market.txt").exists()
        assert (root / "agents" / "player.txt").exists()
        assert (root / "agents" / "ai_1.txt").exists()
        assert (root / "agents" / "city_a.txt").exists()
        bundle = w.persistence.load_context_for_agent(w, w.companies["ai_1"])
        assert "=== WORLD ===" in bundle
        assert "=== MARKET ===" in bundle
        assert "=== AGENT company:ai_1 ===" in bundle


def test_buy_order_matches_cheaper_sell():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        w.companies["ai_1"].inventory.set("coal", 3)
        w.post_sell("company", "ai_1", "coal", 3, price=5)
        buyer = w.companies["player"]
        cash_before = buyer.cash
        w.post_buy("company", "player", "coal", 2, price=8)
        assert buyer.inventory.get("coal") >= 22  # starter 20 + 2 filled
        # paid 5 each from escrow of 8 → net 10
        assert buyer.cash == cash_before - 10
