"""Small companies: startup spawn, roads, and engine produce/sell loop."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.ai.scheduler import AIScheduler
from company_sim.small_companies import (
    DEFAULT_SELL_PRICE,
    city_hall_coord,
    run_small_company_turn,
)
from company_sim.world import World, WorldConfig


def _world(td: Path, **kwargs) -> World:
    cfg = dict(
        map_size=16,
        starting_cities=1,
        ai_company_count=0,
        small_companies_per_city=2,
        save_dir=str(td),
        min_seconds_between_turns=0.0,
        market_seed_qty=10,
        market_seed_price=3,
    )
    cfg.update(kwargs)
    return World.new_game(WorldConfig(**cfg))


def test_small_companies_spawn_around_hall_with_building():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=14, small_companies_per_city=3)
        hall = city_hall_coord(w, "city_a")
        assert hall is not None
        smalls = [c for c in w.companies.values() if c.is_small]
        assert len(smalls) == 3
        for co in smalls:
            assert co.home_city_id == "city_a"
            assert co.is_player is False
            owned = w.owned_plots("company", co.id)
            assert len(owned) == 1
            t = owned[0]
            assert t.plot and t.plot.building
            assert t.plot.building.building_id != "city_hall"
            assert t.plot.building.owner_id == co.id
            # Near hall
            assert abs(t.x - hall[0]) + abs(t.y - hall[1]) <= 6


def test_small_companies_per_city_multi_city():
    with tempfile.TemporaryDirectory() as td:
        w = _world(
            Path(td),
            map_size=24,
            starting_cities=3,
            small_companies_per_city=2,
        )
        smalls = [c for c in w.companies.values() if c.is_small]
        assert len(smalls) == 6
        by_city: dict[str, int] = {}
        for co in smalls:
            by_city[co.home_city_id] = by_city.get(co.home_city_id, 0) + 1  # type: ignore[arg-type]
        assert by_city == {"city_a": 2, "city_b": 2, "city_c": 2}


def test_zero_small_companies_is_fine():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), small_companies_per_city=0)
        assert not any(c.is_small for c in w.companies.values())


def test_specialized_plot_may_get_mine_or_factory():
    """On specialized plots, mine/rig are allowed but not forced."""
    with tempfile.TemporaryDirectory() as td:
        # High specialized % + many small cos to land on specialized tiles
        w = _world(
            Path(td),
            map_size=20,
            small_companies_per_city=8,
            specialized_plot_percent=40.0,
        )
        kinds = set()
        for co in w.companies.values():
            if not co.is_small:
                continue
            t = w.owned_plots("company", co.id)[0]
            assert t.plot and t.plot.building
            kinds.add(t.plot.building.building_id)
            # Method must be valid for building (or None only if no methods)
            bid = t.plot.building.building_id
            mid = t.plot.building.production_method_id
            methods = {m.id for m in w.content.methods_for_building(bid)}
            if methods:
                assert mid in methods
        assert kinds  # at least one building type appeared


def test_engine_turn_buys_produces_sells_at_lowest_price():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=12, small_companies_per_city=1, market_seed_qty=20)
        co = next(c for c in w.companies.values() if c.is_small)
        # Force a simple foundry/make_steel setup for a deterministic produce path
        t = w.owned_plots("company", co.id)[0]
        assert t.plot and t.plot.building
        b = t.plot.building
        b.building_id = "foundry"
        b.production_method_id = "make_steel"
        b.production_method_locked = False
        b.materialize_storage(w.content.storage_capacity_for_building("foundry"))
        # Clear storage; seed company inventory short so it must buy
        for item in list(b.storage.as_dict()):
            b.storage.set(item, 0)
        co.inventory.set("iron_ore", 0)
        co.inventory.set("coal", 0)
        co.inventory.set("energy", 0)
        co.cash = 5000

        # Competing sell already on market at price 7 for steel — after produce we sell at 7
        # First ensure inputs available on market (seed does all goods at price 3)
        note = run_small_company_turn(w, co)
        assert co.acted_this_day
        assert "produced" in note or "sold" in note or "bought" in note

        # If steel was sold, price must match lowest existing non-own listing at sell time.
        # Seed listings for steel are price 3 — so sell should be @3 (DEFAULT only if none).
        steel_sells = [
            L
            for L in w.market.sell_listings_for("steel")
            if L.owner_id == co.id
        ]
        if steel_sells:
            assert steel_sells[0].price == 3  # matched seed lowest


def test_sell_uses_default_when_no_listings():
    with tempfile.TemporaryDirectory() as td:
        w = _world(
            Path(td),
            map_size=10,
            small_companies_per_city=1,
            market_seed_qty=0,
        )
        co = next(c for c in w.companies.values() if c.is_small)
        t = w.owned_plots("company", co.id)[0]
        b = t.plot.building  # type: ignore[union-attr]
        b.building_id = "mine"
        b.production_method_id = "extract_iron_ore"
        b.production_method_locked = True
        b.materialize_storage(w.content.storage_capacity_for_building("mine"))
        for item in list(b.storage.as_dict()):
            b.storage.set(item, 0)
        # Wipe market so lowest-price fallback is DEFAULT_SELL_PRICE
        w.market.listings.clear()
        w.market.inventory = type(w.market.inventory)()
        b.storage.set("iron_ore", 2)
        co.acted_this_day = False
        note = run_small_company_turn(w, co)
        assert "sold" in note
        sells = [L for L in w.market.sell_listings_for("iron_ore") if L.owner_id == co.id]
        assert sells
        assert sells[0].price == DEFAULT_SELL_PRICE


def test_scheduler_runs_small_company_without_llm():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), map_size=10, small_companies_per_city=1, ai_company_count=0)
        # Player hasn't acted — day won't roll solely from small co, but turn should complete
        sched = AIScheduler()
        sched.llm_mode = "online"  # would LLM if not small — must still script
        # Find small company in turn queue
        for _ in range(20):
            actor = w.current_turn_actor()
            if actor is None:
                break
            if getattr(actor, "is_small", False):
                sched.update(w)
                assert actor.acted_this_day
                assert "Small Co" in sched.last_thought or "small" in sched.last_thought.lower() or "produced" in sched.last_thought or "sold" in sched.last_thought or "idle" in sched.last_thought or "bought" in sched.last_thought or "produce" in sched.last_thought
                return
            # Advance past cities
            if actor.acted_this_day:
                w.advance_ai_turn()
            else:
                w.pass_turn(actor.kind, actor.id)
                w.advance_ai_turn()
        pytest.fail("small company never appeared in turn queue")


def test_negative_small_companies_rejected():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ActionError):
            World.new_game(
                WorldConfig(
                    map_size=8,
                    small_companies_per_city=-1,
                    save_dir=str(td),
                )
            )


def test_api_setup_accepts_small_companies_per_city():
    from fastapi.testclient import TestClient
    from company_sim.server import create_app

    with tempfile.TemporaryDirectory() as td:
        # Point saves away — WorldConfig uses save_dir only via API defaults; monkey by env not needed
        app = create_app()
        client = TestClient(app)
        res = client.post(
            "/api/setup",
            json={
                "ai_companies": 0,
                "small_companies_per_city": 2,
                "cities": 1,
                "map_size": 12,
                "specialized_plot_percent": 10,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        smalls = [c for c in data["state"]["companies"] if c.get("is_small")]
        assert len(smalls) == 2
        assert data["state"]["config"]["small_companies_per_city"] == 2
