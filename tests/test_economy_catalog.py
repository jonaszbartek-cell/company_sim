"""Economy catalog expansion: items, buildings, methods, indexes."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.content import GameContent
from company_sim.world import World, WorldConfig


def test_catalog_loads_full_economy():
    c = GameContent.load()
    assert len(c.items.all()) >= 40
    assert len(c.buildings.all()) >= 13
    assert len(c.production.all()) >= 40
    assert "iron" not in c.goods_index
    assert "iron_ore" in c.goods_index
    assert "cars" in c.goods_index
    assert "electric_cars" in c.goods_index


def test_goods_index_steel_and_energy():
    c = GameContent.load()
    steel = c.good_card("steel")
    assert steel["made_in_buildings"] == ["foundry"]
    assert "make_steel" in steel["produced_by_methods"]
    assert "make_components" in steel["used_in_methods"]
    assert "make_cars" in steel["used_in_methods"]

    energy = c.good_card("energy")
    assert set(energy["produced_by_methods"]) == {"coal_power", "gas_power", "oil_power"}
    assert energy["made_in_buildings"] == ["power_plant"]


def test_mine_rig_specialized_only_factories_wider():
    c = GameContent.load()
    assert c.buildings.get("mine").allowed_plot_types == ("specialized_mine",)
    assert c.buildings.get("rig").allowed_plot_types == ("specialized_well",)
    assert c.buildings.get("mine").locks_production_method is True
    assert c.buildings.get("rig").locks_production_method is True
    assert c.buildings.get("foundry").locks_production_method is False
    assert "standard" in c.buildings.get("foundry").allowed_plot_types
    assert "specialized_mine" in c.buildings.get("foundry").allowed_plot_types
    assert "specialized_well" in c.buildings.get("foundry").allowed_plot_types


def test_build_costs_cash_and_construction_materials():
    c = GameContent.load()
    for b in c.buildings.all():
        assert b.build_cost == 100
        assert b.build_cost_items.get("construction_materials") == 10


def test_power_recipes_have_no_energy_input():
    c = GameContent.load()
    for mid in ("coal_power", "gas_power", "oil_power"):
        m = c.production.get(mid)
        assert "energy" not in m.inputs
        assert m.outputs == {"energy": 1}


def test_make_steel_uses_iron_ore():
    c = GameContent.load()
    m = c.production.get("make_steel")
    assert m.inputs == {"iron_ore": 1, "coal": 1, "energy": 1}
    assert m.outputs == {"steel": 1}
    assert m.duration_sec == 1


def test_build_foundry_consumes_construction_materials():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_size=4,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(td),
                min_seconds_between_turns=0.0,
            )
        )
        player = w.companies["player"]
        # Use a standard plot
        tile = next(
            t
            for t in w.grid.tiles
            if t.plot and t.plot.plot_type.value == "standard"
        )
        tile.plot.claim("company", "player")
        before_cm = player.inventory.get("construction_materials")
        before_cash = player.cash
        w.build_building("company", "player", tile.x, tile.y, "foundry")
        assert player.cash == before_cash - 100
        assert player.inventory.get("construction_materials") == before_cm - 10


def test_mine_requires_specialized_plot():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_size=6,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(td),
                min_seconds_between_turns=0.0,
                specialized_plot_percent=40.0,
            )
        )
        player = w.companies["player"]
        std = next(
            t for t in w.grid.tiles if t.plot and t.plot.plot_type.value == "standard"
        )
        std.plot.claim("company", "player")
        with pytest.raises(ActionError, match="specialized|cannot be built"):
            w.build_building("company", "player", std.x, std.y, "mine")
        spec = next(
            t
            for t in w.grid.tiles
            if t.plot and t.plot.plot_type.value == "specialized_mine"
        )
        spec.plot.claim("company", "player")
        r = w.build_building(
            "company", "player", spec.x, spec.y, "mine", method_id="extract_coal"
        )
        assert r.ok
        assert r.data["production_method_id"] == "extract_coal"
        assert r.data["production_method_locked"] is True
        with pytest.raises(ActionError, match="locked"):
            w.set_production_method("company", "player", spec.x, spec.y, "extract_iron_ore")


def test_goods_index_file_written_and_packed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = World.new_game(
            WorldConfig(
                map_size=4,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(root),
                min_seconds_between_turns=0.0,
            )
        )
        assert (root / "goods_index.txt").is_file()
        text = (root / "goods_index.txt").read_text(encoding="utf-8")
        assert "=== GOODS INDEX ===" in text
        assert "iron_ore" in text
        assert "made_in:" in text
        # Compact LLM packs use a stub; full text available via get_catalog / non-compact pack
        compact = w.file_store.pack_for_agent(w, w.companies["player"], compact=True)
        assert any("economy_catalogs_stub" in p or "goods_index" in p for p in compact.path_list())
        assert "get_catalog" in compact.prompt_text
        full = w.file_store.pack_for_agent(w, w.companies["player"], compact=False)
        assert any("goods_index" in p for p in full.path_list())
        assert "GOODS INDEX" in full.prompt_text


def test_public_dict_exposes_indexes():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_size=4,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(td),
                min_seconds_between_turns=0.0,
            )
        )
        pub = w.to_public_dict()
        assert "goods_index" in pub["content"]
        assert "indexes" in pub["content"]
        assert "steel" in pub["content"]["goods_index"]
        assert "foundry" in pub["content"]["indexes"]["methods_by_building"]
