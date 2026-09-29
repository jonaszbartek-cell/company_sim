"""Cities use government contracts, not the market."""

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


def test_city_cannot_use_market():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        try:
            w.post_sell("city", "city_a", "iron_ore", 1, 5)
            assert False
        except ActionError as exc:
            assert "companies" in exc.message.lower()
        try:
            w.buy_from_market("city", "city_a", "iron_ore", 1)
            assert False
        except ActionError as exc:
            assert "companies" in exc.message.lower()
        try:
            w.post_buy("city", "city_a", "iron_ore", 1, 5)
            assert False
        except ActionError as exc:
            assert "companies" in exc.message.lower()


def test_government_contract_lowest_bid_wins_and_fulfill_pays():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        city = w.grid.cities["city_a"]
        c1 = w.companies["ai_1"]
        c2 = w.companies["ai_2"]
        # Ensure winner can deliver
        c2.inventory.set("iron_ore", 5)
        c2.inventory.set("coal", 5)
        city_cash = city.cash
        c2_cash = c2.cash
        iron_city = city.inventory.get("iron_ore")

        r = w.post_government_contract("city", "city_a", {"iron_ore": 3, "coal": 2})
        cid = r.data["id"]
        w.bid_government_contract("company", "ai_1", cid, 100)
        w.bid_government_contract("company", "ai_2", cid, 60)  # lower wins
        w.award_government_contract("city", "city_a", cid)

        contract = w.gov_contracts.get(cid)
        assert contract is not None
        assert contract.status == "awarded"
        assert contract.winner_company_id == "ai_2"
        assert contract.winning_price == 60
        assert city.cash == city_cash - 60
        assert w.gov_contracts.escrow_cash[cid] == 60

        w.fulfill_government_contract("company", "ai_2", cid)
        assert contract.status == "fulfilled"
        assert city.inventory.get("iron_ore") == iron_city + 3
        assert city.inventory.get("coal") >= 2
        assert c2.cash == c2_cash + 60
        assert cid not in w.gov_contracts.escrow_cash


def test_fulfill_requires_all_resources():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        w.companies["ai_1"].inventory.set("iron_ore", 0)
        w.companies["ai_1"].inventory.set("coal", 0)
        r = w.post_government_contract("city", "city_a", {"iron_ore": 2, "coal": 2})
        cid = r.data["id"]
        w.bid_government_contract("company", "ai_1", cid, 40)
        w.award_government_contract("city", "city_a", cid)
        try:
            w.fulfill_government_contract("company", "ai_1", cid)
            assert False
        except ActionError as exc:
            assert "missing" in exc.message.lower()


def test_non_winner_cannot_fulfill():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        w.companies["ai_1"].inventory.set("iron_ore", 5)
        r = w.post_government_contract("city", "city_a", {"iron_ore": 1})
        cid = r.data["id"]
        w.bid_government_contract("company", "ai_1", cid, 20)
        w.bid_government_contract("company", "ai_2", cid, 50)
        w.award_government_contract("city", "city_a", cid)
        try:
            w.fulfill_government_contract("company", "ai_2", cid)
            assert False
        except ActionError as exc:
            assert "not the awarded" in exc.message.lower()


def test_cancel_awarded_refunds_city_escrow():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        city = w.grid.cities["city_a"]
        cash = city.cash
        r = w.post_government_contract("city", "city_a", {"energy": 1})
        cid = r.data["id"]
        w.bid_government_contract("company", "ai_1", cid, 15)
        w.award_government_contract("city", "city_a", cid)
        assert city.cash == cash - 15
        w.cancel_government_contract("city", "city_a", cid)
        assert city.cash == cash
        assert w.gov_contracts.get(cid).status == "cancelled"


def test_city_cannot_direct_trade_with_company():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        w.companies["ai_1"].inventory.set("steel", 2)
        try:
            w.propose_sell("company", "ai_1", "city_a", "steel", 1, 10)
            assert False
        except ActionError as exc:
            assert "government" in exc.message.lower()


def test_gov_contracts_file_saved():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.post_government_contract("city", "city_a", {"iron_ore": 1})
        text = (root / "government_contracts.txt").read_text(encoding="utf-8")
        assert "=== GOVERNMENT CONTRACTS ===" in text
        assert "needs: 1x iron_ore" in text
