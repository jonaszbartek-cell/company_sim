"""Edge roads, combine flags, plot proposals, startup ownership."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.world import World, WorldConfig


def _world(tmp: Path, *, cities: int = 2, ai: int = 2, size: int = 8) -> World:
    return World.new_game(
        WorldConfig(
            map_size=size,
            starting_cities=cities,
            ai_company_count=ai,
            save_dir=str(tmp),
            min_seconds_between_turns=0.0,
        )
    )


def test_cities_own_all_plots_companies_own_none():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=2, size=6)
        assert all(t.plot and t.plot.owner_kind == "city" for t in w.grid.tiles)
        for company in w.companies.values():
            assert w.owned_plots("company", company.id) == []
        # Equal-ish split
        counts = {cid: 0 for cid in w.grid.cities}
        for t in w.grid.tiles:
            assert t.plot and t.plot.owner_id
            counts[t.plot.owner_id] += 1
        assert len(counts) == 2
        assert min(counts.values()) >= 1


def test_edge_road_requires_ownership_and_mirrors():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=1, size=4)
        city = next(iter(w.grid.cities.values()))
        # Take a non-edge cell if possible
        tile = w.grid.get(1, 1)
        assert tile.plot and tile.plot.owned_by("city", city.id)
        w.build_road("city", city.id, 1, 1, "E")
        assert tile.plot.roads["E"] is True
        east = w.grid.get(2, 1)
        assert east.plot and east.plot.roads["W"] is True


def test_combine_flags_only_no_disappear_forbids_road_between():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=1, size=4)
        city = next(iter(w.grid.cities.values()))
        a = w.grid.get(1, 1)
        b = w.grid.get(2, 1)
        assert a.plot and b.plot
        w.merge_plots("city", city.id, 1, 1, 2, 1)
        assert a.plot.combined["E"] == b.plot.id
        assert b.plot.combined["W"] == a.plot.id
        # Plots still exist
        assert w.grid.find_plot(a.plot.id) is a.plot
        assert w.grid.find_plot(b.plot.id) is b.plot
        assert w.grid.group_size(1, 1) == 2
        with pytest.raises(ActionError, match="combined"):
            w.build_road("city", city.id, 1, 1, "E")


def test_cannot_combine_across_road():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=1, size=4)
        city = next(iter(w.grid.cities.values()))
        w.build_road("city", city.id, 1, 1, "E")
        with pytest.raises(ActionError, match="road"):
            w.merge_plots("city", city.id, 1, 1, 2, 1)


def test_plot_buy_proposal_accept_transfers_and_breaks_combine():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=1, ai=1, size=4)
        city = next(iter(w.grid.cities.values()))
        company = w.companies["ai_1"]
        company.cash = 500
        # Combine two city plots first
        w.merge_plots("city", city.id, 1, 1, 2, 1)
        a = w.grid.get(1, 1)
        assert a.plot and a.plot.combined["E"]
        cash_c, cash_city = company.cash, city.cash
        r = w.propose_plot_buy("company", "ai_1", f"city:{city.id}", 1, 1, 120)
        pid = r.data["id"]
        assert a.plot.reserved_proposal_id == pid
        w.accept_proposal("city", city.id, pid)
        assert a.plot.owned_by("company", "ai_1")
        assert a.plot.combined["E"] is None
        assert company.cash == cash_c - 120
        assert city.cash == cash_city + 120
        assert w.proposals.get(pid).status == "accepted"


def test_plot_sell_proposal_reject_unlocks():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=1, ai=1, size=4)
        city = next(iter(w.grid.cities.values()))
        # Give company a plot via direct claim for test setup
        tile = w.grid.get(0, 0)
        assert tile.plot
        tile.plot.claim("company", "ai_1")
        r = w.propose_plot_sell("company", "ai_1", f"city:{city.id}", 0, 0, 200)
        pid = r.data["id"]
        assert tile.plot.reserved_proposal_id == pid
        w.reject_proposal("city", city.id, pid)
        assert tile.plot.reserved_proposal_id is None
        assert tile.plot.owned_by("company", "ai_1")
        assert w.proposals.get(pid).status == "rejected"


def test_goods_proposal_still_accept_reject():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), cities=1, ai=2, size=4)
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        seller.inventory.set("steel", 5)
        r = w.propose_sell("company", "ai_1", "player", "steel", 2, 30)
        pid = r.data["id"]
        w.accept_proposal("company", "player", pid)
        assert buyer.inventory.get("steel") == 2
        assert w.proposals.get(pid).status == "accepted"


def test_startup_files_created():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root, cities=2, ai=1, size=4)
        assert (root / "world.txt").exists()
        assert (root / "market.txt").exists()
        assert (root / "proposals.txt").exists()
        assert (root / "agents" / "player.txt").exists()
        assert (root / "agents" / "city_a.txt").exists()
        world_txt = (root / "world.txt").read_text(encoding="utf-8")
        assert "plots per side=4" in world_txt
        assert "combined=" in world_txt
