"""Engine-driven small companies: spawn at start, simple market produce loop."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from company_sim.actors import Company
from company_sim.buildings import Building
from company_sim.items import Inventory
from company_sim.plots import PlotType
from company_sim.roads import connect_points_mst, connect_star, manhattan, seed_all_side_roads

if TYPE_CHECKING:
    from company_sim.world import World

DEFAULT_SELL_PRICE = 25
SMALL_COMPANY_CASH = 800


def city_hall_coord(world: World, city_id: str) -> tuple[int, int] | None:
    for tile in world.grid.tiles:
        plot = tile.plot
        if not plot or not plot.building:
            continue
        b = plot.building
        if b.building_id == "city_hall" and b.owner_id == city_id:
            return (b.anchor_x if b.anchor_x is not None else tile.x,
                    b.anchor_y if b.anchor_y is not None else tile.y)
    return None


def _candidate_plots_near_hall(
    world: World, city_id: str, hall: tuple[int, int], count: int
) -> list[tuple[int, int]]:
    """Empty city-owned plots nearest the hall (expanding Manhattan rings)."""
    hx, hy = hall
    ranked: list[tuple[int, int, int, int]] = []
    for tile in world.grid.tiles:
        plot = tile.plot
        if not plot or not plot.owned_by("city", city_id):
            continue
        if plot.building is not None:
            continue
        dist = manhattan((tile.x, tile.y), hall)
        if dist == 0:
            continue
        ranked.append((dist, tile.x + tile.y, tile.x, tile.y))
    ranked.sort()
    return [(x, y) for _, _, x, y in ranked[:count]]


def _pick_building_and_method(
    world: World, plot_type: PlotType, rng: random.Random
) -> tuple[str, str | None]:
    """Random buildable building allowed on this plot + random method.

    On specialized plots mine/rig are eligible but not required — they sit in
    the same random pool as factories that allow the plot type.
    """
    buildable = [
        b
        for b in world.buildings.all()
        if b.buildable and b.allows_plot_type(plot_type)
    ]
    if not buildable:
        # Fallback: any factory that allows standard (should not happen)
        buildable = [b for b in world.buildings.all() if b.buildable]
    bdef = rng.choice(buildable)
    methods = world.content.methods_for_building(bdef.id)
    method_id = rng.choice(methods).id if methods else None
    return bdef.id, method_id


def _place_free_building(
    world: World,
    company: Company,
    x: int,
    y: int,
    building_id: str,
    method_id: str | None,
) -> Building:
    bdef = world.buildings.get(building_id)
    building = Building(
        building_id=building_id,
        owner_kind="company",
        owner_id=company.id,
        production_method_id=method_id,
        production_method_locked=bool(bdef.locks_production_method),
        status="idle",
        storage=Inventory(),
        anchor_x=x,
        anchor_y=y,
    )
    building.materialize_storage(world.content.storage_capacity_for_building(building_id))
    world.grid.place_building_on_group(x, y, building)
    return building


def spawn_small_companies(world: World, *, rng: random.Random | None = None) -> list[Company]:
    """Claim plots around each city hall, build random industry, return new companies."""
    per_city = int(world.config.small_companies_per_city)
    if per_city <= 0:
        return []
    rng = rng or random.Random()
    created: list[Company] = []
    for city in world.grid.cities.values():
        hall = city_hall_coord(world, city.id)
        if hall is None:
            continue
        sites = _candidate_plots_near_hall(world, city.id, hall, per_city)
        for i, (x, y) in enumerate(sites):
            cid = f"small_{city.id}_{i + 1}"
            company = Company(
                id=cid,
                name=f"Small Co {city.name} #{i + 1}",
                is_player=False,
                is_small=True,
                home_city_id=city.id,
                cash=SMALL_COMPANY_CASH,
                inventory=Inventory(
                    {
                        "iron_ore": 8,
                        "coal": 8,
                        "energy": 8,
                        "steel": 0,
                        "construction_materials": 10,
                    }
                ),
            )
            tile = world.grid.get(x, y)
            assert tile.plot is not None
            tile.plot.claim("company", company.id)
            building_id, method_id = _pick_building_and_method(
                world, tile.plot.plot_type, rng
            )
            _place_free_building(world, company, x, y, building_id, method_id)
            world.companies[company.id] = company
            created.append(company)
    return created


def wire_startup_roads(world: World) -> dict[str, object]:
    """Seed City Hall side-roads, then connect small companies and halls.

    Order:
      1. Every City Hall plot gets roads on all four sides (N/E/S/W)
      2. Side-road paths from each hall to its small companies
      3. Side-road paths linking all halls (Manhattan MST)
    Shared boundaries may be marked on both plots (double-sided OK).
    """
    halls: list[tuple[int, int]] = []
    hall_by_city: dict[str, tuple[int, int]] = {}
    for city in world.grid.cities.values():
        coord = city_hall_coord(world, city.id)
        if coord is None:
            continue
        halls.append(coord)
        hall_by_city[city.id] = coord
        # 1) City Hall starts with every side roaded
        seed_all_side_roads(world.grid, coord[0], coord[1])

    # 2) Hall → each small company
    spoke_paths = 0
    for company in world.companies.values():
        if not company.is_small or not company.home_city_id:
            continue
        hall = hall_by_city.get(company.home_city_id)
        if hall is None:
            continue
        owned = world.owned_plots("company", company.id)
        if not owned:
            continue
        site = (owned[0].x, owned[0].y)
        paths = connect_star(world.grid, hall, [site])
        spoke_paths += len(paths)

    # 3) Hall → hall
    hall_paths = connect_points_mst(world.grid, halls)
    return {
        "halls": len(halls),
        "spoke_paths": spoke_paths,
        "hall_network_paths": len(hall_paths),
    }


def _company_building_tile(world: World, company_id: str):
    for t in world.owned_plots("company", company_id):
        if t.plot and t.plot.building:
            return t
    return None


def _lowest_sell_price(world: World, item_id: str, exclude_owner_id: str) -> int:
    sells = [
        s
        for s in world.market.sell_listings_for(item_id)
        if not (s.owner_kind == "company" and s.owner_id == exclude_owner_id)
    ]
    if sells:
        return int(sells[0].price)
    return DEFAULT_SELL_PRICE


def run_small_company_turn(world: World, company: Company) -> str:
    """Buy inputs → deposit → produce → withdraw → sell at lowest market price."""
    if not company.is_small:
        return f"{company.name}: not a small company"
    tile = _company_building_tile(world, company.id)
    if tile is None or not tile.plot or not tile.plot.building:
        return f"{company.name}: no building"
    b = tile.plot.building
    x, y = tile.x, tile.y
    if not b.production_method_id:
        return f"{company.name}: no method"

    try:
        method = world.production.get(b.production_method_id)
    except KeyError:
        return f"{company.name}: unknown method"

    world._suppress_day_advance = True  # type: ignore[attr-defined]
    notes: list[str] = []
    try:
        world.ensure_building_storage(b)
        # Buy + deposit missing inputs
        for item_id, need in method.inputs.items():
            have = b.storage.get(item_id)
            missing = max(0, int(need) - have)
            if missing <= 0:
                continue
            inv_have = company.inventory.get(item_id)
            still = missing - inv_have
            if still > 0:
                try:
                    world.buy_from_market("company", company.id, item_id, still)
                    notes.append(f"bought {item_id}")
                except Exception:
                    pass
            deposit_qty = min(missing, company.inventory.get(item_id))
            if deposit_qty > 0:
                try:
                    world.deposit_to_building(
                        "company", company.id, x, y, item_id, deposit_qty
                    )
                    notes.append(f"deposit {item_id}")
                except Exception:
                    pass

        # Produce if inputs present
        try:
            world.produce("company", company.id, x, y)
            notes.append("produced")
        except Exception as exc:
            notes.append(f"produce-skip ({exc})")

        # Withdraw all outputs present in storage and sell
        for item_id in list(method.outputs.keys()):
            qty = b.storage.get(item_id)
            if qty <= 0:
                continue
            try:
                world.withdraw_from_building("company", company.id, x, y, item_id, qty)
            except Exception:
                continue
            sell_qty = company.inventory.get(item_id)
            if sell_qty <= 0:
                continue
            price = _lowest_sell_price(world, item_id, company.id)
            try:
                world.post_sell("company", company.id, item_id, sell_qty, price)
                notes.append(f"sold {sell_qty}x {item_id}@{price}")
            except Exception as exc:
                notes.append(f"sell-skip ({exc})")
    finally:
        world._suppress_day_advance = False  # type: ignore[attr-defined]
        if not company.acted_this_day:
            company.mark_acted()
            world._maybe_advance_day()

    return f"{company.name}: " + (", ".join(notes) if notes else "idle")


__all__ = [
    "DEFAULT_SELL_PRICE",
    "city_hall_coord",
    "spawn_small_companies",
    "wire_startup_roads",
    "run_small_company_turn",
]
