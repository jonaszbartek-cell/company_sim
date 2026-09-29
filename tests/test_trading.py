"""Market retract + direct proposals: no duplicate goods, correct cash."""

from __future__ import annotations

import tempfile
from pathlib import Path

from company_sim.actions import ActionError
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


def test_retract_sell_returns_only_that_listing_goods():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        seller.inventory.set("steel", 10)
        before = seller.inventory.get("steel")
        w.post_sell("company", "ai_1", "steel", 4, price=40)
        w.post_sell("company", "ai_1", "steel", 3, price=50)
        assert seller.inventory.get("steel") == before - 7
        steel_sells = [
            L
            for L in w.market.listings.values()
            if L.side == "sell" and L.owner_id == "ai_1" and L.item_id == "steel"
        ]
        assert len(steel_sells) == 2
        first = min(steel_sells, key=lambda L: L.id)
        qty = first.quantity
        w.retract_sell("company", "ai_1", first.id)
        assert seller.inventory.get("steel") == before - 7 + qty
        w.market.assert_inventory_matches_sells()
        assert w.market.sell_qty_on_book("steel") == w.market.inventory.get("steel")


def test_sell_cash_only_on_fill_not_on_post():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 5)
        cash_s = seller.cash
        cash_b = buyer.cash
        w.post_sell("company", "ai_1", "steel", 2, price=25)
        assert seller.cash == cash_s  # no cash yet
        assert seller.inventory.get("steel") == 3
        w.buy_from_market("company", "player", "steel", 2)
        assert seller.cash == cash_s + 50
        assert buyer.cash == cash_b - 50
        assert buyer.inventory.get("steel") == 2
        assert w.market.inventory.get("steel") == 0
        w.market.assert_inventory_matches_sells()


def test_buy_order_autofills_when_sell_at_or_below_price():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        buyer = w.companies["player"]
        seller = w.companies["ai_1"]
        # Use steel — seed market has no steel sells
        seller.inventory.set("steel", 5)
        cash_b = buyer.cash
        steel_b = buyer.inventory.get("steel")
        w.post_buy("company", "player", "steel", 2, price=10)
        assert buyer.cash == cash_b - 20  # still escrowed (no fill yet)
        assert buyer.inventory.get("steel") == steel_b
        w.post_sell("company", "ai_1", "steel", 2, price=7)  # <= buy price → auto fill
        assert buyer.inventory.get("steel") == steel_b + 2
        # Paid 7 each from escrow of 10 → net 14
        assert buyer.cash == cash_b - 14
        assert seller.cash >= 1500 + 14
        w.market.assert_inventory_matches_sells()


def test_cannot_retract_someone_elses_sell():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        w.companies["ai_1"].inventory.set("steel", 3)
        w.post_sell("company", "ai_1", "steel", 3, price=40)
        lid = next(L.id for L in w.market.listings.values() if L.side == "sell" and L.owner_id == "ai_1")
        try:
            w.retract_sell("company", "player", lid)
            assert False
        except ActionError as exc:
            assert "own" in exc.message.lower()


def test_direct_sell_proposal_accept():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 5)
        cash_s, cash_b = seller.cash, buyer.cash
        steel_s, steel_b = seller.inventory.get("steel"), buyer.inventory.get("steel")
        r = w.propose_sell("company", "ai_1", "player", "steel", 2, 30)
        assert r.ok
        assert seller.inventory.get("steel") == steel_s - 2  # reserved
        assert seller.cash == cash_s
        pid = r.data["id"]
        w.accept_proposal("company", "player", pid)
        assert buyer.inventory.get("steel") == steel_b + 2
        assert buyer.cash == cash_b - 60
        assert seller.cash == cash_s + 60
        assert seller.inventory.get("steel") == steel_s - 2
        assert w.proposals.get(pid).status == "accepted"


def test_direct_buy_proposal_reject_refunds_cash():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        buyer = w.companies["player"]
        cash = buyer.cash
        r = w.propose_buy("company", "player", "ai_1", "iron_ore", 3, 9)
        assert r.ok
        assert buyer.cash == cash - 27
        pid = r.data["id"]
        w.reject_proposal("company", "ai_1", pid)
        assert buyer.cash == cash
        assert w.proposals.get(pid).status == "rejected"


def test_direct_buy_proposal_accept_moves_goods_and_cash():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        buyer = w.companies["player"]
        seller = w.companies["ai_2"]
        seller.inventory.set("iron_ore", 10)
        cash_b, cash_s = buyer.cash, seller.cash
        iron_b, iron_s = buyer.inventory.get("iron_ore"), seller.inventory.get("iron_ore")
        r = w.propose_buy("company", "player", "ai_2", "iron_ore", 4, 5)
        pid = r.data["id"]
        w.accept_proposal("company", "ai_2", pid)
        assert buyer.inventory.get("iron_ore") == iron_b + 4
        assert seller.inventory.get("iron_ore") == iron_s - 4
        assert buyer.cash == cash_b - 20
        assert seller.cash == cash_s + 20


def test_proposals_file_saved():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.companies["ai_1"].inventory.set("steel", 2)
        w.propose_sell("company", "ai_1", "player", "steel", 1, 40)
        text = (root / "proposals.txt").read_text(encoding="utf-8")
        assert "=== DIRECT PROPOSALS ===" in text
        assert "goods_sell 1x steel" in text
