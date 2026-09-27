"""LLM tools → World Action API.

Tool schemas are kept small for local budget-PC models.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from company_sim.actions import ActionError
from company_sim.map_grid import TileKind

if TYPE_CHECKING:
    from company_sim.actors import Actor
    from company_sim.world import World


# OpenAI / Ollama style tool definitions
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": "Get your cash, inventory, and owned plots/buildings summary.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "Get nearby unowned plots (price, type, coords) and a short map summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max unowned plots to list (default 8)",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buy_plot",
            "description": "Buy an unowned plot at grid coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_building",
            "description": "Build a building on a plot you own (default: foundry).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "building_id": {
                        "type": "string",
                        "description": "Building id from content catalog (e.g. foundry)",
                    },
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_road",
            "description": "Build a road on an empty or unowned plot cell (costs cash).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_plots",
            "description": "Merge two adjacent plots you own into one parcel (production bonus).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x1": {"type": "integer"},
                    "y1": {"type": "integer"},
                    "x2": {"type": "integer"},
                    "y2": {"type": "integer"},
                },
                "required": ["x1", "y1", "x2", "y2"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "End your turn/decision with a short note. Call after your actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Brief summary of what you did / plan"},
                },
                "additionalProperties": False,
            },
        },
    },
]


def build_actor_context(world: World, actor: Actor) -> str:
    """Compact text context for small local models."""
    owned = world.owned_plots(actor.kind, actor.id)
    owned_lines = []
    for t in owned[:12]:
        b = t.plot.building.building_type.value if t.plot and t.plot.building else "none"
        ptype = t.plot.plot_type.value if t.plot else "?"
        owned_lines.append(f"  ({t.x},{t.y}) {ptype} building={b}")
    if len(owned) > 12:
        owned_lines.append(f"  ... +{len(owned) - 12} more")

    extra = ""
    if actor.kind == "city":
        from company_sim.actors import City

        assert isinstance(actor, City)
        extra = (
            f"\nTerritory cells: {len(actor.territory)}"
            f"\nCenter: ({actor.center_x},{actor.center_y})"
            f"\nPopulation: {actor.population}"
        )

    return (
        f"You are {actor.kind} '{actor.name}' (id={actor.id}).\n"
        f"Game time: {world.time_sec:.1f}s\n"
        f"Cash: {actor.cash}\n"
        f"Inventory: {actor.inventory.as_dict()}\n"
        f"Road build cost: {world.config.road_build_cost}\n"
        f"Owned plots ({len(owned)}):\n"
        + ("\n".join(owned_lines) if owned_lines else "  (none)")
        + extra
        + "\nUse tools to act. Prefer 1-3 actions then call done."
    )


def system_prompt_for(actor: Actor) -> str:
    if actor.kind == "city":
        return (
            "You administer a city made of normal roads and plots (not a special tile). "
            "Grow infrastructure with roads, claim municipal plots, build workshops when useful. "
            "Stay within cash. Use only the provided tools. Be concise."
        )
    return (
        "You run a company in a real-time economic simulation. "
        "Buy plots with road access, build workshops, merge adjacent plots, extend roads if needed. "
        "Stay within cash. Use only the provided tools. Be concise."
    )


class ToolExecutor:
    """Dispatches LLM tool calls onto the shared World Action API."""

    def __init__(self, world: World, actor: Actor) -> None:
        self.world = world
        self.actor = actor
        self.done_note: str | None = None
        self.log: list[str] = []

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._dispatch(name, arguments or {})
            self.log.append(f"{name}: {result.get('message', result)}")
            return result
        except ActionError as exc:
            payload = {"ok": False, "message": exc.message}
            self.log.append(f"{name}: FAIL {exc.message}")
            return payload
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "message": str(exc)}
            self.log.append(f"{name}: ERROR {exc}")
            return payload

    def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        kind = self.actor.kind
        aid = self.actor.id

        if name == "get_status":
            owned = self.world.owned_plots(kind, aid)
            return {
                "ok": True,
                "message": "status",
                "data": {
                    "kind": kind,
                    "id": aid,
                    "name": self.actor.name,
                    "cash": self.actor.cash,
                    "inventory": dict(self.actor.inventory.as_dict()),
                    "owned_plot_count": len(owned),
                    "owned_plots": [
                        {
                            "x": t.x,
                            "y": t.y,
                            "plot_type": t.plot.plot_type.value if t.plot else None,
                            "has_building": bool(t.plot and t.plot.building),
                        }
                        for t in owned[:20]
                    ],
                },
            }

        if name == "get_market_overview":
            limit = int(args.get("limit", 8))
            unowned = []
            for t in self.world.grid.tiles:
                if t.kind != TileKind.PLOT or not t.plot or t.plot.owner_id is not None:
                    continue
                if not self.world.grid.is_road_access(t.x, t.y):
                    continue
                # Prefer territory for cities
                if kind == "city" and t.city_id != aid:
                    continue
                unowned.append(t)
            unowned.sort(key=lambda t: t.plot.price if t.plot else 9999)
            return {
                "ok": True,
                "message": "market",
                "data": {
                    "unowned_plots": [
                        {
                            "x": t.x,
                            "y": t.y,
                            "price": t.plot.price if t.plot else None,
                            "plot_type": t.plot.plot_type.value if t.plot else None,
                            "city_id": t.city_id,
                        }
                        for t in unowned[:limit]
                    ],
                    "road_build_cost": self.world.config.road_build_cost,
                },
            }

        if name == "buy_plot":
            r = self.world.buy_plot(kind, aid, int(args["x"]), int(args["y"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "build_building":
            building_id = str(args.get("building_id", "foundry"))
            r = self.world.build_building(kind, aid, int(args["x"]), int(args["y"]), building_id)
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "build_road":
            r = self.world.build_road(kind, aid, int(args["x"]), int(args["y"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "merge_plots":
            r = self.world.merge_plots(
                kind,
                aid,
                int(args["x1"]),
                int(args["y1"]),
                int(args["x2"]),
                int(args["y2"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "done":
            self.done_note = str(args.get("note", "done"))
            return {"ok": True, "message": self.done_note}

        return {"ok": False, "message": f"Unknown tool: {name}"}
