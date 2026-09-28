"""Players and agents choose a production method at build; change when unlocked."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from company_sim.actions import ActionError
from company_sim.ai.tools import ToolExecutor
from company_sim.world import World, WorldConfig


def test_player_and_agent_choose_method_at_build_and_change_when_allowed():
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(
            WorldConfig(
                map_size=8,
                starting_cities=1,
                ai_company_count=0,
                save_dir=str(td),
                min_seconds_between_turns=0.0,
                specialized_plot_percent=30.0,
            )
        )
        player = w.companies["player"]
        player.cash = 20_000
        player.inventory.set("construction_materials", 80)

        std = next(t for t in w.grid.tiles if t.plot.plot_type.value == "standard")
        std.plot.claim("company", "player")

        # Choose method at build via World API (player HTTP uses the same call)
        built = w.build_building(
            "company",
            "player",
            std.x,
            std.y,
            "foundry",
            method_id="make_copper",
        )
        assert built.ok
        assert built.data["production_method_id"] == "make_copper"
        assert built.data["production_method_locked"] is False
        assert std.plot.building.production_method_id == "make_copper"

        # Change anytime when unlocked
        player.acted_this_day = False
        changed = w.set_production_method(
            "company", "player", std.x, std.y, "make_steel"
        )
        assert changed.ok
        assert std.plot.building.production_method_id == "make_steel"

        # Agent tool path: build with method_id
        mine = next(
            t for t in w.grid.tiles if t.plot.plot_type.value == "specialized_mine"
        )
        mine.plot.claim("company", "player")
        player.acted_this_day = False
        ex = ToolExecutor(w, player)
        agent_build = ex.execute(
            "build_building",
            {
                "x": mine.x,
                "y": mine.y,
                "building_id": "mine",
                "method_id": "extract_coal",
            },
        )
        assert agent_build["ok"] is True
        assert agent_build["data"]["production_method_id"] == "extract_coal"
        assert mine.plot.building.production_method_locked is True

        # Locked buildings reject later changes
        player.acted_this_day = False
        locked = ex.execute(
            "set_production_method",
            {"x": mine.x, "y": mine.y, "method_id": "extract_iron_ore"},
        )
        assert locked["ok"] is False
        assert "locked" in locked["message"].lower()

        # Agent can still change unlocked foundry anytime
        player.acted_this_day = False
        again = ex.execute(
            "set_production_method",
            {"x": std.x, "y": std.y, "method_id": "make_aluminum"},
        )
        assert again["ok"] is True
        assert std.plot.building.production_method_id == "make_aluminum"
