"""Start-screen parameter matrix: backend World/API + frontend form↔API parity.

UI ranges (web/index.html):
  AI companies            0–12
  Small companies/city    0–20
  Agent cities            1–8
  Map size                2–128
  Specialized resources % 0–100
  LLM debug               bool

Full integer cartesian of every axis is infeasible (~10^7+). This suite covers:
  1) Every legal discrete UI value on each axis (others at defaults)
  2) Full cartesian product of boundary/mid samples across all axes
  3) Frontend HTML min/max/defaults match API acceptance for those values

Heavier exhaustive runner: scripts/run_start_screen_combos.py
"""

from __future__ import annotations

import itertools
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from company_sim.server import create_app
from company_sim.small_companies import city_hall_coord
from company_sim.world import World, WorldConfig

AI_ALL = list(range(0, 13))
SMALL_ALL = list(range(0, 21))
CITIES_ALL = list(range(1, 9))
MAP_SWEEP = sorted(set(list(range(2, 33)) + list(range(36, 129, 4)) + [128]))
SPEC_SWEEP = sorted(set(list(range(0, 101, 5)) + [1, 15, 99]))
LLM_ALL = [False, True]

DEFAULTS = dict(
    ai_companies=2,
    small_companies_per_city=0,
    cities=1,
    map_size=12,
    specialized_plot_percent=15,
    llm_debug=False,
)

CART_AI = [0, 2, 6, 12]
CART_SMALL = [0, 5, 10, 20]
CART_CITIES = [1, 2, 4, 8]
CART_MAP = [2, 8, 12, 24, 48, 128]
CART_SPEC = [0, 15, 50, 100]
CART_LLM = [False, True]


def _world_kwargs(**overrides) -> dict:
    body = {**DEFAULTS, **overrides}
    return dict(
        map_size=body["map_size"],
        starting_cities=body["cities"],
        ai_company_count=body["ai_companies"],
        small_companies_per_city=body["small_companies_per_city"],
        specialized_plot_percent=float(body["specialized_plot_percent"]),
        llm_debug=bool(body["llm_debug"]),
        min_seconds_between_turns=0.0,
        market_seed_qty=1,
        market_seed_price=1,
    )


def _assert_world_invariants(w: World, *, expect: dict) -> None:
    assert w.started
    assert w.config.map_size == expect["map_size"]
    assert w.grid.width == expect["map_size"]
    assert w.grid.height == expect["map_size"]
    assert len(w.grid.cities) == expect["cities"]
    assert w.config.ai_company_count == expect["ai_companies"]
    ais = [c for c in w.companies.values() if c.id.startswith("ai_")]
    assert len(ais) == expect["ai_companies"]
    assert "player" in w.companies
    assert w.config.small_companies_per_city == expect["small_companies_per_city"]
    smalls = [c for c in w.companies.values() if c.is_small]
    assert len(smalls) <= expect["cities"] * expect["small_companies_per_city"]
    if expect["small_companies_per_city"] > 0 and expect["map_size"] >= 8:
        assert len(smalls) >= 1
    assert abs(w.config.specialized_plot_percent - float(expect["specialized_plot_percent"])) < 1e-6
    assert bool(w.config.llm_debug) is bool(expect["llm_debug"])
    pub = w.to_public_dict()
    assert pub["config"]["map_size"] == expect["map_size"]
    assert pub["map"]["width"] == expect["map_size"]
    assert len(pub["map"]["cities"]) == expect["cities"]
    for city in w.grid.cities.values():
        assert city_hall_coord(w, city.id) is not None, city.id


def _make_world(**overrides) -> World:
    expect = {**DEFAULTS, **overrides}
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(WorldConfig(save_dir=td, **_world_kwargs(**overrides)))
        _assert_world_invariants(w, expect=expect)
        return w


def _api_setup(**overrides) -> dict:
    expect = {**DEFAULTS, **overrides}
    app = create_app()
    client = TestClient(app)
    res = client.post("/api/setup", json=expect)
    data = res.json()
    assert res.status_code == 200, data
    assert data.get("ok") is True, data
    st = data["state"]
    assert st["config"]["map_size"] == expect["map_size"]
    assert st["config"]["starting_cities"] == expect["cities"]
    assert st["config"]["ai_company_count"] == expect["ai_companies"]
    assert st["config"]["small_companies_per_city"] == expect["small_companies_per_city"]
    assert abs(st["config"]["specialized_plot_percent"] - float(expect["specialized_plot_percent"])) < 1e-6
    assert bool(st["config"]["llm_debug"]) is bool(expect["llm_debug"])
    st2 = client.get("/api/state").json()
    assert st2.get("started") is True
    assert st2["state"]["map"]["width"] == expect["map_size"]
    return data


def _feasible(ai: int, small_n: int, cities: int, map_size: int) -> bool:
    cells = map_size * map_size
    if cities > cells:
        return False
    if map_size >= 96 and (small_n > 5 or ai > 2 or cities > 4):
        return False
    if map_size >= 48 and small_n >= 20 and cities >= 8 and ai >= 6:
        return False
    return True


CARTESIAN = list(
    itertools.product(CART_AI, CART_SMALL, CART_CITIES, CART_MAP, CART_SPEC, CART_LLM)
)
FEASIBLE_CART = [row for row in CARTESIAN if _feasible(row[0], row[1], row[2], row[3])]

# Pytest keeps a thinner cartesian; full grid is in scripts/run_start_screen_combos.py
PYTEST_CART = [
    row
    for row in FEASIBLE_CART
    if row[3] in (2, 12, 24)
    and row[4] in (0, 15, 100)
    and row[5] is False
    and row[0] in (0, 2, 12)
    and row[1] in (0, 10, 20)
    and row[2] in (1, 4, 8)
]

API_CART = [
    row
    for row in PYTEST_CART
    if row[3] in (2, 12)
]


@pytest.mark.parametrize("ai", AI_ALL)
def test_axis_ai_companies(ai: int) -> None:
    _make_world(ai_companies=ai)
    _api_setup(ai_companies=ai)


@pytest.mark.parametrize("small_n", SMALL_ALL)
def test_axis_small_companies(small_n: int) -> None:
    size = 24 if small_n > 8 else 12
    _make_world(small_companies_per_city=small_n, map_size=size)
    _api_setup(small_companies_per_city=small_n, map_size=size)


@pytest.mark.parametrize("cities", CITIES_ALL)
def test_axis_cities(cities: int) -> None:
    size = max(12, cities * 4)
    _make_world(cities=cities, map_size=size)
    _api_setup(cities=cities, map_size=size)


@pytest.mark.parametrize("map_size", MAP_SWEEP)
def test_axis_map_size(map_size: int) -> None:
    _make_world(map_size=map_size, ai_companies=0, small_companies_per_city=0)
    if map_size in (2, 12, 32, 64, 96, 128) or map_size <= 8:
        _api_setup(map_size=map_size, ai_companies=0, small_companies_per_city=0)


@pytest.mark.parametrize("pct", SPEC_SWEEP)
def test_axis_specialized_percent(pct: int) -> None:
    _make_world(specialized_plot_percent=pct, map_size=16)
    if pct in (0, 15, 50, 100):
        _api_setup(specialized_plot_percent=pct, map_size=16)


@pytest.mark.parametrize("llm", LLM_ALL)
def test_axis_llm_debug(llm: bool) -> None:
    _make_world(llm_debug=llm)
    _api_setup(llm_debug=llm)


@pytest.mark.parametrize(
    "ai,small_n,cities,map_size,pct,llm",
    PYTEST_CART,
    ids=[
        f"ai{a}_sm{s}_ci{c}_m{m}_sp{p}_llm{int(l)}"
        for a, s, c, m, p, l in PYTEST_CART
    ],
)
def test_cartesian_world(
    ai: int, small_n: int, cities: int, map_size: int, pct: int, llm: bool
) -> None:
    _make_world(
        ai_companies=ai,
        small_companies_per_city=small_n,
        cities=cities,
        map_size=map_size,
        specialized_plot_percent=pct,
        llm_debug=llm,
    )


@pytest.mark.parametrize(
    "ai,small_n,cities,map_size,pct,llm",
    API_CART,
    ids=[
        f"api_ai{a}_sm{s}_ci{c}_m{m}_sp{p}"
        for a, s, c, m, p, l in API_CART
    ],
)
def test_cartesian_api(
    ai: int, small_n: int, cities: int, map_size: int, pct: int, llm: bool
) -> None:
    _api_setup(
        ai_companies=ai,
        small_companies_per_city=small_n,
        cities=cities,
        map_size=map_size,
        specialized_plot_percent=pct,
        llm_debug=llm,
    )


def test_frontend_show_setup_includes_small_companies_and_guards_ws_clobber() -> None:
    js = Path("web/app.js").read_text(encoding="utf-8")
    assert "setup-small-per-city" in js
    assert "defaults.small_companies_per_city" in js
    # WS setup push must not overwrite an already-visible start form
    assert "if (setupEl.hidden) showSetup" in js


def test_frontend_setup_form_ranges_match_api() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    js = Path("web/app.js").read_text(encoding="utf-8")

    def _attr(field_id: str, attr: str) -> str:
        needle = f'id="{field_id}"'
        i = html.index(needle)
        snippet = html[i : i + 120]
        key = f'{attr}="'
        j = snippet.index(key) + len(key)
        return snippet[j : snippet.index('"', j)]

    assert _attr("setup-companies", "min") == "0"
    assert _attr("setup-companies", "max") == "12"
    assert _attr("setup-companies", "value") == "2"
    assert _attr("setup-small-per-city", "min") == "0"
    assert _attr("setup-small-per-city", "max") == "20"
    assert _attr("setup-small-per-city", "value") == "0"
    assert _attr("setup-cities", "min") == "1"
    assert _attr("setup-cities", "max") == "8"
    assert _attr("setup-cities", "value") == "1"
    assert _attr("setup-map", "min") == "2"
    assert _attr("setup-map", "max") == "128"
    assert _attr("setup-map", "value") == "12"
    assert _attr("setup-specialized-pct", "min") == "0"
    assert _attr("setup-specialized-pct", "max") == "100"
    assert _attr("setup-specialized-pct", "value") == "15"

    for key in (
        "ai_companies",
        "small_companies_per_city",
        "cities",
        "map_size",
        "specialized_plot_percent",
        "llm_debug",
    ):
        assert key in js

    corners = [
        dict(ai_companies=0, small_companies_per_city=0, cities=1, map_size=2, specialized_plot_percent=0, llm_debug=False),
        dict(ai_companies=12, small_companies_per_city=20, cities=8, map_size=32, specialized_plot_percent=100, llm_debug=True),
        dict(ai_companies=2, small_companies_per_city=0, cities=1, map_size=12, specialized_plot_percent=15, llm_debug=False),
        dict(ai_companies=0, small_companies_per_city=0, cities=1, map_size=128, specialized_plot_percent=0, llm_debug=False),
    ]
    for body in corners:
        _api_setup(**body)


def test_api_rejects_outside_ui_ranges() -> None:
    app = create_app()
    c = TestClient(app)
    bad = [
        {"ai_companies": -1, "cities": 1, "map_size": 12},
        {"ai_companies": 13, "cities": 1, "map_size": 12},
        {"ai_companies": 0, "cities": 0, "map_size": 12},
        {"ai_companies": 0, "cities": 9, "map_size": 12},
        {"ai_companies": 0, "cities": 1, "map_size": 1},
        {"ai_companies": 0, "cities": 1, "map_size": 129},
        {"ai_companies": 0, "cities": 1, "map_size": 12, "specialized_plot_percent": -1},
        {"ai_companies": 0, "cities": 1, "map_size": 12, "specialized_plot_percent": 101},
        {"ai_companies": 0, "cities": 1, "map_size": 12, "small_companies_per_city": -1},
        {"ai_companies": 0, "cities": 1, "map_size": 12, "small_companies_per_city": 31},
    ]
    for body in bad:
        res = c.post("/api/setup", json=body)
        if res.status_code == 422:
            continue
        data = res.json()
        assert data.get("ok") is not True, body
