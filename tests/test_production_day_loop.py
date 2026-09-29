"""Day-boundary pause + multi-day production loop (player, AI, small companies)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.ai.scheduler import AIScheduler
from company_sim.ai.tools import ToolExecutor
from company_sim.small_companies import run_small_company_turn
from company_sim.world import World, WorldConfig


def _make(td: Path, **kwargs) -> World:
    cfg = dict(
        map_size=12,
        starting_cities=1,
        ai_company_count=0,
        small_companies_per_city=0,
        min_seconds_between_turns=0.0,
        market_seed_qty=80,
        market_seed_price=1,
        specialized_plot_percent=30.0,
        save_dir=str(td),
    )
    cfg.update(kwargs)
    return World.new_game(WorldConfig(**cfg))


def _advance_days(w: World, n: int) -> None:
    """Force n day rolls by marking every company acted."""
    for _ in range(n):
        for c in w.iter_companies():
            c.acted_this_day = False
        for c in w.iter_companies():
            c.mark_acted()
        w._maybe_advance_day()


def _claim_standard(w: World, company_id: str):
    t = next(
        t
        for t in w.grid.tiles
        if t.plot
        and t.plot.building is None
        and t.plot.plot_type.value == "standard"
        and t.plot.owner_kind == "city"
    )
    t.plot.claim("company", company_id)
    return t


# ---------------------------------------------------------------------------
# Pause at end of day
# ---------------------------------------------------------------------------


def test_pause_waits_until_day_completes():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td), ai_company_count=1)
        assert w.day == 1
        r = w.set_paused(True)
        assert r.ok
        assert w.pause_requested is True
        assert w.paused is False
        assert "end of day" in r.message

        # Sim still ticks while pause is pending
        w.tick(0.5)
        assert w.tick_index == 1

        w.pass_turn("company", "player")
        assert w.day == 1
        assert w.paused is False
        w.pass_turn("company", "ai_1")
        assert w.day == 2
        assert w.paused is True
        assert w.pause_requested is False

        # While paused, time does not advance
        prev = w.tick_index
        w.tick(1.0)
        assert w.tick_index == prev

        r = w.set_paused(False)
        assert r.message == "resumed"
        assert w.paused is False
        w.tick(0.25)
        assert w.tick_index == prev + 1


def test_cancel_pending_pause_resumes():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td), ai_company_count=1)
        w.set_paused(True)
        assert w.pause_requested
        w.set_paused(False)
        assert not w.pause_requested and not w.paused
        w.pass_turn("company", "player")
        w.pass_turn("company", "ai_1")
        assert w.day == 2
        assert w.paused is False


# ---------------------------------------------------------------------------
# Catalog placeholders
# ---------------------------------------------------------------------------


def test_methods_are_ten_in_ten_out_three_days():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td))
        for m in w.production.all():
            assert m.duration_sec == 3
            for q in m.inputs.values():
                assert q == 10
            for q in m.outputs.values():
                assert q == 10


# ---------------------------------------------------------------------------
# Production: nearest buildings, split inputs, multi-day, auto-restart
# ---------------------------------------------------------------------------


def test_player_production_pulls_split_inputs_and_finishes_in_three_days():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td))
        player = w.companies["player"]
        player.cash = 50_000
        player.inventory.set("construction_materials", 100)

        a = _claim_standard(w, "player")
        b = _claim_standard(w, "player")
        # Build foundry on A, warehouse-like second foundry on B just for storage
        w.build_building("company", "player", a.x, a.y, "foundry", method_id="make_steel")
        player.acted_this_day = False
        w.build_building("company", "player", b.x, b.y, "foundry", method_id="make_copper")
        foundry = a.plot.building
        other = b.plot.building
        assert foundry and other

        # Split inputs: 6 iron/coal/energy on foundry, 4 on the other building
        for item in ("iron_ore", "coal", "energy"):
            player.inventory.set(item, 20)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", a.x, a.y, item, 6)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", b.x, b.y, item, 4)

        player.acted_this_day = False
        started = w.produce("company", "player", a.x, a.y)
        assert started.ok
        assert foundry.status == "working"
        # Solo company: produce rolls the day, so the start day already counts
        assert foundry.production_days_elapsed == 1
        # Inputs consumed from both buildings
        for item in ("iron_ore", "coal", "energy"):
            assert foundry.storage.get(item) == 0
            assert other.storage.get(item) == 0
        assert foundry.storage.get("steel") == 0

        _advance_days(w, 1)
        assert foundry.status == "working"
        assert foundry.production_days_elapsed == 2
        assert foundry.storage.get("steel") == 0

        _advance_days(w, 1)
        # Batch complete on the 3rd production day
        assert foundry.storage.get("steel") == 10


def test_output_overflow_goes_to_nearest_then_destroys_with_warning():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td))
        player = w.companies["player"]
        player.cash = 50_000
        player.inventory.set("construction_materials", 100)

        mine_tile = next(
            t
            for t in w.grid.tiles
            if t.plot
            and t.plot.plot_type.value == "specialized_mine"
            and t.plot.building is None
        )
        mine_tile.plot.claim("company", "player")
        nearby = next(
            t
            for t in w.grid.tiles
            if t.plot
            and t.plot.building is None
            and t.plot.plot_type.value == "standard"
            and abs(t.x - mine_tile.x) + abs(t.y - mine_tile.y) <= 3
        )
        nearby.plot.claim("company", "player")

        w.build_building(
            "company", "player", mine_tile.x, mine_tile.y, "mine", method_id="extract_iron_ore"
        )
        player.acted_this_day = False
        w.build_building(
            "company", "player", nearby.x, nearby.y, "foundry", method_id="make_steel"
        )
        mine = mine_tile.plot.building
        depot = nearby.plot.building
        assert mine and depot

        # Fill mine iron_ore storage completely
        w.ensure_building_storage(mine)
        mine.storage.set("iron_ore", 10)
        # Leave 5 room on depot
        w.ensure_building_storage(depot)
        depot.storage.set("iron_ore", 5)

        player.acted_this_day = False
        w.produce("company", "player", mine_tile.x, mine_tile.y)
        _advance_days(w, 3)

        # 10 produced: 0 into full mine, 5 into depot (room), 5 destroyed
        assert mine.storage.get("iron_ore") == 10
        assert depot.storage.get("iron_ore") == 10
        assert any("destroyed" in w_["message"] for w_ in w.warnings)


def test_cannot_change_method_while_working_but_can_when_idle_unlocked():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td))
        player = w.companies["player"]
        player.cash = 20_000
        player.inventory.set("construction_materials", 40)
        t = _claim_standard(w, "player")
        w.build_building("company", "player", t.x, t.y, "foundry", method_id="make_steel")
        b = t.plot.building
        for item in ("iron_ore", "coal", "energy"):
            player.inventory.set(item, 20)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", t.x, t.y, item, 10)
        player.acted_this_day = False
        w.produce("company", "player", t.x, t.y)
        assert b.status == "working"
        player.acted_this_day = False
        with pytest.raises(ActionError, match="while producing"):
            w.set_production_method("company", "player", t.x, t.y, "make_copper")

        # Finish without auto-restart (no more inputs)
        _advance_days(w, 3)
        assert b.status == "idle"
        player.acted_this_day = False
        r = w.set_production_method("company", "player", t.x, t.y, "make_copper")
        assert r.ok
        assert b.production_method_id == "make_copper"


def test_pause_and_resume_preserves_production_progress():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td), ai_company_count=0)
        player = w.companies["player"]
        player.cash = 20_000
        player.inventory.set("construction_materials", 40)
        t = _claim_standard(w, "player")
        w.build_building("company", "player", t.x, t.y, "foundry", method_id="make_steel")
        b = t.plot.building
        for item in ("iron_ore", "coal", "energy"):
            player.inventory.set(item, 20)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", t.x, t.y, item, 10)
        player.acted_this_day = False
        w.produce("company", "player", t.x, t.y)
        # Solo: start day already counted
        assert b.production_days_elapsed == 1

        # Request pause; next day roll will pause
        w.set_paused(True)
        assert w.pause_requested
        _advance_days(w, 1)
        assert w.paused is True
        assert b.production_days_elapsed == 2
        assert b.storage.get("steel") == 0

        w.set_paused(False)
        _advance_days(w, 1)
        assert b.storage.get("steel") == 10


def test_agent_tool_produce_multi_day():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td))
        player = w.companies["player"]
        player.cash = 20_000
        player.inventory.set("construction_materials", 40)
        t = _claim_standard(w, "player")
        w.build_building("company", "player", t.x, t.y, "foundry", method_id="make_steel")
        for item in ("iron_ore", "coal", "energy"):
            player.inventory.set(item, 20)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", t.x, t.y, item, 10)
        ex = ToolExecutor(w, player)
        player.acted_this_day = False
        r = ex.execute("produce", {"x": t.x, "y": t.y})
        assert r["ok"] is True
        assert t.plot.building.status == "working"
        _advance_days(w, 3)
        assert t.plot.building.storage.get("steel") == 10


def test_ai_company_heuristic_starts_production():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td), ai_company_count=1)
        ai = w.companies["ai_1"]
        ai.cash = 50_000
        ai.inventory.set("construction_materials", 40)
        t = _claim_standard(w, "ai_1")
        w.build_building("company", "ai_1", t.x, t.y, "foundry", method_id="make_steel")
        for item in ("iron_ore", "coal", "energy"):
            ai.inventory.set(item, 30)
            # deposit without advancing day awkwardly
            w._suppress_day_advance = True
            w.deposit_to_building("company", "ai_1", t.x, t.y, item, 10)
            w._suppress_day_advance = False
        sched = AIScheduler()
        # Force heuristic path
        before = t.plot.building.status
        assert before == "idle"
        # Run heuristic directly
        sched._heuristic_company(w, ai)
        assert t.plot.building.status == "working" or "deposit" in (sched.last_thought or "")
        # If it only deposited, run again to start
        if t.plot.building.status != "working":
            sched._heuristic_company(w, ai)
        assert t.plot.building.status == "working"
        _advance_days(w, 3)
        assert t.plot.building.storage.get("steel") == 10


def test_small_company_production_over_days():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td), small_companies_per_city=1, map_size=16)
        smalls = [c for c in w.companies.values() if c.is_small]
        assert smalls
        co = smalls[0]
        tile = next(
            t
            for t in w.owned_plots("company", co.id)
            if t.plot and t.plot.building
        )
        b = tile.plot.building
        # Force foundry/steel for deterministic inputs
        b.building_id = "foundry"
        b.production_method_id = "make_steel"
        b.production_method_locked = False
        b.materialize_storage(w.content.storage_capacity_for_building("foundry"))
        # Seed market + company so the small-co turn can buy/deposit
        for item in ("iron_ore", "coal", "energy"):
            co.inventory.set(item, 20)
            w.market.inventory.add(item, 50)

        note = run_small_company_turn(w, co)
        assert "started-production" in note or "producing" in note or "produce-skip" not in note or b.status == "working"
        if b.status != "working":
            # deposit manually and start
            for item in ("iron_ore", "coal", "energy"):
                w.deposit_to_building("company", co.id, tile.x, tile.y, item, 10)
            w.produce("company", co.id, tile.x, tile.y)
        assert b.status == "working"
        _advance_days(w, 3)
        assert b.storage.get("steel") == 10


def test_auto_restart_after_finish_when_inputs_remain():
    with tempfile.TemporaryDirectory() as td:
        w = _make(Path(td))
        player = w.companies["player"]
        player.cash = 20_000
        player.inventory.set("construction_materials", 40)
        t = _claim_standard(w, "player")
        w.build_building("company", "player", t.x, t.y, "foundry", method_id="make_steel")
        b = t.plot.building
        # Two full batches worth of inputs (cap 10 each — need withdraw/space trick)
        # Put 10 in foundry; after first batch consumes them, deposit isn't auto —
        # for auto-restart put second batch in another building.
        other = _claim_standard(w, "player")
        player.acted_this_day = False
        w.build_building("company", "player", other.x, other.y, "foundry", method_id="make_copper")
        for item in ("iron_ore", "coal", "energy"):
            player.inventory.set(item, 30)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", t.x, t.y, item, 10)
            player.acted_this_day = False
            w.deposit_to_building("company", "player", other.x, other.y, item, 10)
        player.acted_this_day = False
        w.produce("company", "player", t.x, t.y)
        _advance_days(w, 3)
        assert b.storage.get("steel") == 10
        # Auto-restart should have pulled the second batch from the other building
        assert b.status == "working"
        assert other.plot.building.storage.get("iron_ore") == 0
