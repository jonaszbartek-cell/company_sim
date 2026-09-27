"""Trading: market orders, retract, conservation, direct proposals."""

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


def test_sell_order_moves_goods_not_cash_until_bought():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 5)
        cash_s0, cash_b0 = seller.cash, buyer.cash
        goods0 = w.total_item_quantity("steel")
        cash0 = w.total_cash()

        r = w.post_sell("company", "ai_1", "steel", 3, price=40)
        assert r.ok
        assert seller.inventory.get("steel") == 2
        assert w.market.inventory.get("steel") == 3
        assert seller.cash == cash_s0  # no cash yet
        assert buyer.cash == cash_b0
        assert w.total_item_quantity("steel") == goods0
        assert w.total_cash() == cash0

        lid = r.data["listing_id"]
        listing = w.market.listings[lid]
        assert listing.side == "sell"
        assert listing.quantity == 3
        assert listing.price == 40
        assert listing.owner_id == "ai_1"


def test_standard_buy_pays_seller_at_listing_price():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 4)
        goods0 = w.total_item_quantity("steel")
        cash0 = w.total_cash()

        w.post_sell("company", "ai_1", "steel", 2, price=50)
        w.post_sell("company", "ai_1", "steel", 2, price=30)
        before_s, before_b = seller.cash, buyer.cash

        r = w.buy_from_market("company", "player", "steel", 2)
        assert r.ok
        assert r.data["got"] == 2
        assert r.data["spent"] == 60  # lowest price 30
        assert buyer.inventory.get("steel") == 2
        assert buyer.cash == before_b - 60
        assert seller.cash == before_s + 60
        assert w.market.inventory.get("steel") == 2  # remaining high-price lot
        assert w.total_item_quantity("steel") == goods0
        assert w.total_cash() == cash0


def test_retract_sell_returns_only_that_companys_goods():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        a1 = w.companies["ai_1"]
        a2 = w.companies["ai_2"]
        a1.inventory.set("coal", 5)
        a2.inventory.set("coal", 5)
        goods0 = w.total_item_quantity("coal")
        cash0 = w.total_cash()

        r1 = w.post_sell("company", "ai_1", "coal", 3, price=7)
        r2 = w.post_sell("company", "ai_2", "coal", 2, price=9)
        # Seed market may already have coal from city; track via actor inventories
        assert a1.inventory.get("coal") == 2
        assert a2.inventory.get("coal") == 3

        market_before = w.market.inventory.get("coal")
        w.retract_listing("company", "ai_1", r1.data["listing_id"])
        assert a1.inventory.get("coal") == 5  # all 3 returned
        assert a2.inventory.get("coal") == 3  # untouched
        assert w.market.inventory.get("coal") == market_before - 3
        assert r1.data["listing_id"] not in w.market.listings
        assert r2.data["listing_id"] in w.market.listings

        # Cannot retract someone else's listing
        try:
            w.retract_listing("company", "ai_1", r2.data["listing_id"])
            assert False, "expected error"
        except ActionError as exc:
            assert "own" in exc.message.lower()

        assert w.total_item_quantity("coal") == goods0
        assert w.total_cash() == cash0


def test_buy_order_auto_matches_sell_at_or_below_price():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("iron", 4)
        goods0 = w.total_item_quantity("iron")
        cash0 = w.total_cash()

        w.post_sell("company", "ai_1", "iron", 3, price=5)
        cash_s0, cash_b0 = seller.cash, buyer.cash

        # Buy order at 8 should fill at sell price 5, refund 3/u
        inv_before = buyer.inventory.get("iron")
        r = w.post_buy("company", "player", "iron", 2, price=8)
        assert r.ok
        assert buyer.inventory.get("iron") == inv_before + 2
        # After fill: spent net 10 (2*5), escrow released 16, refund 6 → net -10
        assert buyer.cash == cash_b0 - 10
        assert seller.cash == cash_s0 + 10
        assert w.total_item_quantity("iron") == goods0
        assert w.total_cash() == cash0


def test_buy_order_waits_then_matches_new_sell():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        # Clear seeded city sells so our buy order stays open
        for lid in list(w.market.listings):
            L = w.market.listings[lid]
            if L.side == "sell":
                w.market.inventory.add(L.item_id, -L.quantity)
                w.market.remove_listing(lid)
        seller.inventory.set("energy", 3)
        cash0 = w.total_cash()
        goods0 = w.total_item_quantity("energy")

        w.post_buy("company", "player", "energy", 2, price=12)
        assert any(L.side == "buy" and L.item_id == "energy" for L in w.market.listings.values())
        # Cash escrowed
        assert w.market.escrow_cash.get("company:player") == 24
        assert buyer.cash == 2500 - 24

        w.post_sell("company", "ai_1", "energy", 2, price=10)
        # Should auto-match
        assert buyer.inventory.get("energy") >= 22
        assert seller.cash >= 1500 + 20
        assert w.total_cash() == cash0
        assert w.total_item_quantity("energy") == goods0


def test_retract_buy_refunds_escrow():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        buyer = w.companies["player"]
        cash0 = w.total_cash()
        r = w.post_buy("company", "player", "steel", 2, price=15)
        assert buyer.cash == 2500 - 30
        w.retract_listing("company", "player", r.data["listing_id"])
        assert buyer.cash == 2500
        assert "company:player" not in w.market.escrow_cash
        assert w.total_cash() == cash0


def test_cannot_sell_more_than_owned_no_duplicate_goods():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        a = w.companies["ai_1"]
        a.inventory.set("steel", 2)
        goods0 = w.total_item_quantity("steel")
        w.post_sell("company", "ai_1", "steel", 2, price=10)
        assert a.inventory.get("steel") == 0
        try:
            w.post_sell("company", "ai_1", "steel", 1, price=10)
            assert False
        except ActionError:
            pass
        # Also cannot propose sell of goods already on market
        try:
            w.propose_sell("company", "ai_1", "player", "steel", 1, price=10)
            assert False
        except ActionError:
            pass
        assert w.total_item_quantity("steel") == goods0


def test_direct_sell_proposal_accept():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 3)
        goods0 = w.total_item_quantity("steel")
        cash0 = w.total_cash()
        cash_s0, cash_b0 = seller.cash, buyer.cash

        r = w.propose_sell("company", "ai_1", "player", "steel", 2, price=25)
        assert r.ok
        pid = r.data["proposal"]["id"]
        assert seller.inventory.get("steel") == 1  # escrowed 2
        assert w.proposals.goods_escrow.get("steel") == 2
        assert seller.cash == cash_s0  # no cash yet

        # Buyer accepts
        buyer.acted_this_day = False
        w.accept_proposal("company", "player", pid)
        assert buyer.inventory.get("steel") == 2
        assert seller.inventory.get("steel") == 1
        assert w.proposals.goods_escrow.get("steel") == 0
        assert buyer.cash == cash_b0 - 50
        assert seller.cash == cash_s0 + 50
        assert w.proposals.get(pid).status == "accepted"
        assert w.total_item_quantity("steel") == goods0
        assert w.total_cash() == cash0


def test_direct_sell_proposal_reject_returns_goods():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        seller = w.companies["ai_1"]
        seller.inventory.set("steel", 2)
        goods0 = w.total_item_quantity("steel")
        cash0 = w.total_cash()

        r = w.propose_sell("company", "ai_1", "ai_2", "steel", 2, price=20)
        pid = r.data["proposal"]["id"]
        w.reject_proposal("company", "ai_2", pid)
        assert seller.inventory.get("steel") == 2
        assert w.proposals.goods_escrow.get("steel") == 0
        assert w.proposals.get(pid).status == "rejected"
        assert w.total_item_quantity("steel") == goods0
        assert w.total_cash() == cash0


def test_direct_buy_proposal_accept():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        buyer = w.companies["player"]
        seller = w.companies["ai_1"]
        seller.inventory.set("coal", 4)
        goods0 = w.total_item_quantity("coal")
        cash0 = w.total_cash()
        cash_s0, cash_b0 = seller.cash, buyer.cash

        r = w.propose_buy("company", "player", "ai_1", "coal", 2, price=6)
        pid = r.data["proposal"]["id"]
        assert buyer.cash == cash_b0 - 12
        assert w.proposals.cash_escrow[pid] == 12

        seller.acted_this_day = False
        w.accept_proposal("company", "ai_1", pid)
        assert buyer.inventory.get("coal") >= 22
        assert seller.inventory.get("coal") == 2
        assert seller.cash == cash_s0 + 12
        assert pid not in w.proposals.cash_escrow
        assert w.total_item_quantity("coal") == goods0
        assert w.total_cash() == cash0


def test_direct_buy_proposal_cancel_refunds_cash():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        buyer = w.companies["player"]
        cash0 = w.total_cash()
        r = w.propose_buy("company", "player", "ai_2", "iron", 1, price=9)
        pid = r.data["proposal"]["id"]
        assert buyer.cash == 2500 - 9
        w.cancel_proposal("company", "player", pid)
        assert buyer.cash == 2500
        assert w.proposals.get(pid).status == "cancelled"
        assert w.total_cash() == cash0


def test_sell_proposal_blocks_duplicate_market_sell():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        a = w.companies["ai_1"]
        a.inventory.set("steel", 1)
        w.propose_sell("company", "ai_1", "player", "steel", 1, price=10)
        try:
            w.post_sell("company", "ai_1", "steel", 1, price=10)
            assert False
        except ActionError:
            pass


def test_proposals_persist_in_save_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.companies["ai_1"].inventory.set("steel", 2)
        w.propose_sell("company", "ai_1", "player", "steel", 1, price=33)
        text = (root / "proposals.txt").read_text(encoding="utf-8")
        assert "=== DIRECT PROPOSALS ===" in text
        assert "sell 1x steel @ 33/u" in text
        agent = (root / "agents" / "ai_1.txt").read_text(encoding="utf-8")
        assert "my open direct proposals" in agent
        assert "steel @ 33/u" in agent
        bundle = w.persistence.load_context_for_agent(w, w.companies["player"])
        assert "=== DIRECT PROPOSALS ===" in bundle
        assert "=== YOUR DIRECT TRADES ===" in bundle
