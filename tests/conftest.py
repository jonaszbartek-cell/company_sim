"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from company_sim.world import World


@pytest.fixture
def world() -> World:
    return World.new_game()
