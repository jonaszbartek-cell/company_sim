"""Edge cases, invalid inputs, and weird sequences across the whole sim."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.agent_files import AgentFileStore, LLMDebugLog
from company_sim.ai.tools import ToolExecutor, player_tool_catalog
from company_sim.world import World, WorldConfig


def _w(
    tmp: Path,
    *,
    size: int = 6,
    cities: int = 1,
    ai: int = 1,
    llm_debug: bool = False,
) -> World:
    return World.new_game(
        WorldConfig(
            map_size=size,
            starting_cities=cities,
            ai_company_count=ai,
            save_dir=str(tmp),
            min_seconds_between_turns=0.0,
            llm_debug=llm_debug,
        )
    )


def _claim_plot(w: World, company_id: str, x: int, y: int) -> None:
    tile = w.grid.get(x, y)
    assert tile.plot
    tile.plot.claim("company", company_id)


# ---------- setup / config extremes ----------


def test_minimum_map_size_two():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), size=2, cities=1, ai=0)
        assert w.config.map_size == 2
        assert len(w.grid.tiles) == 4
        assert all(t.plot and t.plot.owner_kind == "city" for t in w.grid.tiles)


def test_reject_map_size_one():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ActionError):
            _w(Path(td), size=1)


def test_zero_ai_companies_still_boots():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0, cities=1)
        assert list(w.companies.keys()) == ["player"]
        assert (Path(td) / "instructions" / "COMPANY_INSTRUCTIONS_player.txt").is_file()
        assert (Path(td) / "instructions" / "CITY_INSTRUCTIONS_city_a.txt").is_file()


def test_many_cities_split_all_plots():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), size=8, cities=4, ai=0)
        assert len(w.grid.cities) == 4
        owners = {t.plot.owner_id for t in w.grid.tiles if t.plot}
        assert owners == set(w.grid.cities.keys())


def test_legacy_map_width_height_folded_into_square():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_width=5,
                map_height=9,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(td),
            )
        )
        assert w.config.map_size == 9


# ---------- land / roads / combine weirdness ----------


def test_build_on_unowned_plot_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        with pytest.raises(ActionError, match="own"):
            w.build_building("company", "player", 0, 0, "foundry")


def test_build_unknown_building_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        _claim_plot(w, "player", 1, 1)
        with pytest.raises(ActionError, match="Unknown building"):
            w.build_building("company", "player", 1, 1, "spaceship")


def test_produce_without_inputs_fails_and_does_not_consume():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        _claim_plot(w, "player", 1, 1)
        player = w.companies["player"]
        player.cash = 5000
        player.inventory.set("iron", 0)
        player.inventory.set("coal", 0)
        player.inventory.set("energy", 0)
        w.build_building("company", "player", 1, 1, "foundry")
        with pytest.raises(ActionError, match="Missing inputs"):
            w.produce("company", "player", 1, 1)


def test_set_production_method_wrong_building_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        _claim_plot(w, "player", 1, 1)
        w.companies["player"].cash = 5000
        w.build_building("company", "player", 1, 1, "foundry")
        with pytest.raises(ActionError):
            w.set_production_method("company", "player", 1, 1, "not_a_method")


def test_road_invalid_side_and_duplicate_road():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        _claim_plot(w, "player", 1, 1)
        player = w.companies["player"]
        player.inventory.set("steel", 5)
        with pytest.raises(ActionError, match="side"):
            w.build_road("company", "player", 1, 1, "NE")
        w.build_road("company", "player", 1, 1, "N")
        # Second road on same side should fail or be no-op error
        with pytest.raises(ActionError):
            w.build_road("company", "player", 1, 1, "N")


def test_cannot_road_on_combined_side():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0, size=4)
        _claim_plot(w, "player", 1, 1)
        _claim_plot(w, "player", 2, 1)
        player = w.companies["player"]
        player.inventory.set("steel", 5)
        w.merge_plots("company", "player", 1, 1, 2, 1)
        with pytest.raises(ActionError):
            w.build_road("company", "player", 1, 1, "E")


def test_merge_same_plot_or_diagonal_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0, size=4)
        _claim_plot(w, "player", 1, 1)
        _claim_plot(w, "player", 2, 2)
        with pytest.raises(ActionError):
            w.merge_plots("company", "player", 1, 1, 1, 1)
        with pytest.raises(ActionError):
            w.merge_plots("company", "player", 1, 1, 2, 2)


def test_merge_unowned_neighbor_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0, size=4)
        _claim_plot(w, "player", 1, 1)
        with pytest.raises(ActionError):
            w.merge_plots("company", "player", 1, 1, 2, 1)


def test_out_of_bounds_plot_access_is_weirdly_asymmetric():
    """Negative coords wrap via Python modulo; huge positive raises IndexError."""
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), size=4, ai=0)
        t = w.grid.get(-1, 0)
        assert t is not None
        assert 0 <= t.x < 4 and 0 <= t.y < 4
        with pytest.raises(IndexError):
            w.grid.get(0, 99)


# ---------- market weirdness ----------


def test_post_sell_zero_or_negative_rejected():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        player = w.companies["player"]
        player.inventory.set("iron", 10)
        with pytest.raises(ActionError):
            w.post_sell("company", "player", "iron", 0, 5)
        with pytest.raises(ActionError):
            w.post_sell("company", "player", "iron", -1, 5)
        with pytest.raises(ActionError):
            w.post_sell("company", "player", "iron", 1, -5)


def test_post_sell_unknown_item():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        with pytest.raises(ActionError, match="Unknown item"):
            w.post_sell("company", "player", "unobtanium", 1, 10)


def test_cannot_buy_own_sell_listing():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        player = w.companies["player"]
        # Clear seeded market sells from other companies (none) and post own
        player.inventory.set("iron", 5)
        player.cash = 1000
        w.post_sell("company", "player", "iron", 5, 1)
        # Only own listing remains for iron at price 1 — buy should fail or skip own
        before = player.inventory.get("iron")
        with pytest.raises(ActionError):
            w.buy_from_market("company", "player", "iron", 1)
        assert player.inventory.get("iron") == before


def test_buy_partial_when_cash_short():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=1)
        seller = w.companies["ai_1"]
        buyer = w.companies["player"]
        # Drain seeded market and put expensive sell
        for lid in list(w.market.listings.keys()):
            L = w.market.listings[lid]
            if L.side == "sell":
                try:
                    w.retract_sell(L.owner_kind, L.owner_id, lid)
                except ActionError:
                    pass
        seller.inventory.set("coal", 10)
        w.post_sell("company", "ai_1", "coal", 10, 100)
        buyer.cash = 250  # can afford 2 only
        before = buyer.inventory.get("coal")
        r = w.buy_from_market("company", "player", "coal", 10)
        assert r.ok
        assert r.data["got"] == 2
        assert buyer.inventory.get("coal") == before + 2
        assert buyer.cash == 50


def test_retract_sell_twice_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        player = w.companies["player"]
        player.inventory.set("iron", 3)
        r = w.post_sell("company", "player", "iron", 3, 9)
        lid = r.data["listing_id"]
        w.retract_sell("company", "player", lid)
        with pytest.raises(ActionError):
            w.retract_sell("company", "player", lid)


def test_city_banned_from_market_and_goods_proposals():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        city = next(iter(w.grid.cities.values()))
        city.inventory.set("iron", 5)
        with pytest.raises(ActionError, match="companies"):
            w.post_sell("city", city.id, "iron", 1, 5)
        with pytest.raises(ActionError):
            w.propose_sell("city", city.id, "company:player", "iron", 1, 5)


# ---------- proposals ----------


def test_plot_buy_insufficient_cash_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        city = next(iter(w.grid.cities.values()))
        player = w.companies["player"]
        player.cash = 5
        tile = next(t for t in w.grid.tiles if t.plot and t.plot.owned_by("city", city.id))
        with pytest.raises(ActionError):
            w.propose_plot_buy("company", "player", f"city:{city.id}", tile.x, tile.y, 100)


def test_reject_plot_buy_refunds_escrow():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        city = next(iter(w.grid.cities.values()))
        player = w.companies["player"]
        start = player.cash
        tile = next(t for t in w.grid.tiles if t.plot and t.plot.owned_by("city", city.id))
        prop = w.propose_plot_buy("company", "player", f"city:{city.id}", tile.x, tile.y, 80)
        pid = prop.data["id"]
        assert player.cash == start - 80
        w.reject_proposal("city", city.id, pid)
        assert player.cash == start
        assert tile.plot.reserved_proposal_id is None or tile.plot.owner_kind == "city"


def test_cannot_accept_proposal_addressed_to_someone_else():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=1)
        city = next(iter(w.grid.cities.values()))
        player = w.companies["player"]
        tile = next(t for t in w.grid.tiles if t.plot and t.plot.owned_by("city", city.id))
        prop = w.propose_plot_buy("company", "player", f"city:{city.id}", tile.x, tile.y, 50)
        pid = prop.data["id"]
        with pytest.raises(ActionError):
            w.accept_proposal("company", "ai_1", pid)


def test_propose_sell_to_self_rejected_or_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        player = w.companies["player"]
        player.inventory.set("iron", 2)
        with pytest.raises(ActionError):
            w.propose_sell("company", "player", "company:player", "iron", 1, 5)


# ---------- day / turns ----------


def test_day_does_not_advance_until_all_companies_acted():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=2)
        assert w.day == 1
        w.pass_turn("company", "player")
        assert w.day == 1
        w.pass_turn("company", "ai_1")
        assert w.day == 1
        w.pass_turn("company", "ai_2")
        assert w.day == 2
        for c in w.companies.values():
            assert c.acted_this_day is False


def test_pass_twice_same_day_is_idempotent_or_safe():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        w.pass_turn("company", "player")
        day = w.day
        # Second pass after day already advanced (only one company)
        assert day == 2
        w.pass_turn("company", "player")
        assert w.day == 3


# ---------- mail weirdness ----------


def test_cannot_message_self():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        with pytest.raises(ActionError):
            w.send_message("company", "player", "company:player", "hello")


def test_empty_message_rejected():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=1)
        with pytest.raises(ActionError):
            w.send_message("company", "player", "company:ai_1", "")
        with pytest.raises(ActionError):
            w.send_message("company", "player", "company:ai_1", "   ")


def test_message_over_500_chars_rejected():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=1)
        with pytest.raises(ActionError):
            w.send_message("company", "player", "company:ai_1", "x" * 501)


def test_message_unknown_recipient():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        with pytest.raises(ActionError):
            w.send_message("company", "player", "company:ghost", "hi")


# ---------- instructions + packing isolation stress ----------


def test_instruction_stubs_idempotent_do_not_overwrite_edits():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _w(root, ai=1, llm_debug=True)
        path = root / "instructions" / "COMPANY_INSTRUCTIONS_ai_1.txt"
        path.write_text("CUSTOM STANDING ORDERS\n", encoding="utf-8")
        w.file_store.ensure_all_instructions(w)
        assert path.read_text(encoding="utf-8") == "CUSTOM STANDING ORDERS\n"


def test_pack_never_leaks_other_agent_cash_blocks():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=3)
        for cid, cash in (("ai_1", 1111), ("ai_2", 2222), ("ai_3", 3333), ("player", 4444)):
            w.companies[cid].cash = cash
        w.persistence.save_all(w)
        for actor in w.companies.values():
            bundle = w.file_store.pack_for_agent(w, actor, compact=True)
            # Own cash appears
            assert f"cash: {actor.cash}" in bundle.prompt_text or f"cash:{actor.cash}" in bundle.prompt_text.replace(
                " ", ""
            )
            for other in w.companies.values():
                if other.id == actor.id:
                    continue
                assert f"=== AGENT company:{other.id} ===" not in bundle.prompt_text
                # Other agent's private instruction file not listed
                assert f"COMPANY_INSTRUCTIONS_{other.id}" not in "\n".join(bundle.path_list())


def test_llm_debug_path_traversal_blocked():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _w(root, llm_debug=True)
        dbg = w.llm_debug_log
        assert dbg is not None
        # Write a real trace first
        actor = w.companies["player"]
        bundle = w.file_store.pack_for_agent(w, actor)
        path = dbg.write_turn(
            actor_kind="company",
            actor_id="player",
            day=1,
            system="s",
            bundle=bundle,
            rounds=[],
            final_note="n",
        )
        assert path is not None
        assert dbg.read_trace("../../etc/passwd") is None
        assert dbg.read_trace("/etc/passwd") is None
        rel = str(path.relative_to(dbg.debug_dir))
        assert dbg.read_trace(rel) is not None


# ---------- gov contracts edges ----------


def test_company_cannot_post_or_award_gov_contract():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        with pytest.raises(ActionError):
            w.post_government_contract("company", "player", {"iron": 1})
        city = next(iter(w.grid.cities.values()))
        posted = w.post_government_contract("city", city.id, {"iron": 1})
        cid = posted.data["id"]
        w.bid_government_contract("company", "player", cid, 50)
        with pytest.raises(ActionError):
            w.award_government_contract("company", "player", cid)


def test_bid_on_missing_contract():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        with pytest.raises(ActionError):
            w.bid_government_contract("company", "player", 99999, 10)


def test_award_with_no_bids_fails():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        city = next(iter(w.grid.cities.values()))
        posted = w.post_government_contract("city", city.id, {"coal": 1})
        cid = posted.data["id"]
        with pytest.raises(ActionError):
            w.award_government_contract("city", city.id, cid)


# ---------- tool executor chaos ----------


def test_tool_executor_unknown_tool():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        ex = ToolExecutor(w, w.companies["player"])
        r = ex.execute("teleport", {})
        assert r["ok"] is False


def test_tool_executor_missing_required_args_fails_softly():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        ex = ToolExecutor(w, w.companies["player"])
        for name in (
            "propose_plot_buy",
            "build_building",
            "post_sell",
            "merge_plots",
            "send_message",
        ):
            r = ex.execute(name, {})
            assert r["ok"] is False, name


def test_every_player_catalog_tool_survives_garbage_args():
    garbage = {
        "to": "",
        "x": -1,
        "y": 9999,
        "price": -99,
        "quantity": 0,
        "item_id": "",
        "listing_id": -1,
        "proposal_id": 0,
        "contract_id": -5,
        "side": "Z",
        "building_id": "",
        "method_id": "",
        "body": "",
        "requirements": "nope",
        "with_whom": "nobody",
        "limit": -3,
    }
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=1)
        ex = ToolExecutor(w, w.companies["player"])
        for tool in player_tool_catalog():
            r = ex.execute(tool["name"], dict(garbage))
            assert isinstance(r, dict), tool["name"]
            assert "ok" in r, tool["name"]
            # Must not raise / crash the process


def test_city_tool_executor_can_post_gov_but_not_market():
    with tempfile.TemporaryDirectory() as td:
        w = _w(Path(td), ai=0)
        city = next(iter(w.grid.cities.values()))
        ex = ToolExecutor(w, city)
        bad = ex.execute("post_sell", {"item_id": "iron", "quantity": 1, "price": 5})
        assert bad["ok"] is False
        good = ex.execute("post_government_contract", {"requirements": {"iron": 1}})
        assert good["ok"] is True


# ---------- persistence consistency after chaos ----------


def test_save_reload_surfaces_after_mixed_actions():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _w(root, ai=1, llm_debug=True)
        player = w.companies["player"]
        _claim_plot(w, "player", 1, 1)
        player.cash = 5000
        player.inventory.set("steel", 3)
        player.inventory.set("iron", 5)
        w.build_building("company", "player", 1, 1, "foundry")
        w.build_road("company", "player", 1, 1, "S")
        w.post_sell("company", "player", "iron", 2, 11)
        w.send_message("company", "player", "company:ai_1", "yo")
        w.persistence.save_all(w)

        assert (root / "agents" / "player.txt").read_text(encoding="utf-8").count("foundry") >= 1
        market = (root / "market.txt").read_text(encoding="utf-8")
        assert "iron" in market
        assert (root / "instructions" / "COMPANY_INSTRUCTIONS_player.txt").is_file()
        pub = w.to_public_dict()
        assert pub["llm_debug"]["enabled"] is True
        assert "COMPANY_INSTRUCTIONS_player.txt" in pub["llm_debug"]["instructions"]
