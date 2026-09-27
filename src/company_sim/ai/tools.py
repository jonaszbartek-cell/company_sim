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
            "name": "get_market",
            "description": "View market sell/buy listings and market inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Optional filter by item id (iron, coal, energy, steel)",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_unowned_plots",
            "description": "List nearby unowned plots (price, type, coords).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max plots (default 8)"},
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
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
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
                    "building_id": {"type": "string"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "produce",
            "description": "Run one production batch on your building at (x,y).",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_production_method",
            "description": "Choose which production method a building runs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "method_id": {"type": "string"},
                },
                "required": ["x", "y", "method_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_sell",
            "description": "Post a sell order: goods move to market inventory until bought.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "price": {"type": "integer", "description": "Cash per unit"},
                },
                "required": ["item_id", "quantity", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_buy",
            "description": "Post a buy order at a max price (cash escrowed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "price": {"type": "integer"},
                },
                "required": ["item_id", "quantity", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buy_from_market",
            "description": "Buy goods now from the lowest-price sell listings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["item_id", "quantity"],
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
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_plots",
            "description": "Merge two adjacent plots you own into one parcel.",
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
            "name": "list_contacts",
            "description": "List other agents/user you can message (mailbox pairs).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_mail",
            "description": "Read your mail. Optionally filter to one counterpart (id or kind:id).",
            "parameters": {
                "type": "object",
                "properties": {
                    "with_whom": {
                        "type": "string",
                        "description": "Optional recipient like 'player', 'ai_1', or 'company:ai_2'",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a short message to another agent or the player (shared mailbox file).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient id, name, or kind:id (e.g. player, ai_2, city:city_a)",
                    },
                    "body": {"type": "string", "description": "Message text (max 500 chars)"},
                },
                "required": ["to", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pass_turn",
            "description": "Do nothing this turn but mark yourself as having acted today.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "End your turn with a short note. Call after your actions.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
]


def build_actor_context(world: World, actor: Actor) -> str:
    """Compact extra hint (file bundle already has full agent/world/market)."""
    owned = world.owned_plots(actor.kind, actor.id)
    owned_lines = []
    for t in owned[:12]:
        b = "none"
        if t.plot and t.plot.building:
            b = f"{t.plot.building.building_id}/{t.plot.building.status}"
        ptype = t.plot.plot_type.value if t.plot else "?"
        owned_lines.append(f"  ({t.x},{t.y}) {ptype} building={b}")
    if len(owned) > 12:
        owned_lines.append(f"  ... +{len(owned) - 12} more")

    return (
        f"Day {world.day}. You are {actor.kind} '{actor.name}' (id={actor.id}).\n"
        f"Cash: {actor.cash} | Inventory: {actor.inventory.as_dict()}\n"
        f"Owned plots ({len(owned)}):\n"
        + ("\n".join(owned_lines) if owned_lines else "  (none)")
        + "\nLoop: buy plot → build → buy inputs → produce → sell. Negotiate via send_message. Goal: strongest company.\n"
        "Prefer 1-3 actions then call done."
    )


def system_prompt_for(actor: Actor) -> str:
    if actor.kind == "city":
        return (
            "You administer a city of normal roads and plots. "
            "Claim municipal plots, build workshops, post market orders, keep territory healthy. "
            "You may send_message to companies (including the player) to coordinate. "
            "Stay within cash. Use only the provided tools. Be concise."
        )
    return (
        "You run a company. Become the strongest firm: "
        "buy plots, build foundries, buy inputs from the market, produce steel, sell at profit. "
        "You may send_message to other companies, the city, or the player to negotiate. "
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
                    "day": self.world.day,
                    "acted_this_day": self.actor.acted_this_day,
                    "owned_plot_count": len(owned),
                    "owned_plots": [
                        {
                            "x": t.x,
                            "y": t.y,
                            "plot_id": t.plot.id if t.plot else None,
                            "plot_type": t.plot.plot_type.value if t.plot else None,
                            "building": t.plot.building.to_public_dict()
                            if t.plot and t.plot.building
                            else None,
                        }
                        for t in owned[:20]
                    ],
                },
            }

        if name == "get_market":
            data = self.world.market.to_public_dict()
            item_id = args.get("item_id")
            if item_id:
                data["sell_listings"] = [L for L in data["sell_listings"] if L["item_id"] == item_id]
                data["buy_listings"] = [L for L in data["buy_listings"] if L["item_id"] == item_id]
            return {"ok": True, "message": "market", "data": data}

        if name == "list_unowned_plots" or name == "get_market_overview":
            limit = int(args.get("limit", 8))
            unowned = []
            for t in self.world.grid.tiles:
                if t.kind != TileKind.PLOT or not t.plot or t.plot.owner_id is not None:
                    continue
                if not self.world.grid.is_road_access(t.x, t.y):
                    continue
                if kind == "city" and t.city_id != aid:
                    continue
                unowned.append(t)
            unowned.sort(key=lambda t: t.plot.price if t.plot else 9999)
            return {
                "ok": True,
                "message": "plots",
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

        if name == "produce":
            r = self.world.produce(kind, aid, int(args["x"]), int(args["y"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "set_production_method":
            r = self.world.set_production_method(
                kind, aid, int(args["x"]), int(args["y"]), str(args["method_id"])
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "post_sell":
            r = self.world.post_sell(
                kind, aid, str(args["item_id"]), int(args["quantity"]), int(args["price"])
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "post_buy":
            r = self.world.post_buy(
                kind, aid, str(args["item_id"]), int(args["quantity"]), int(args["price"])
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "buy_from_market":
            r = self.world.buy_from_market(kind, aid, str(args["item_id"]), int(args["quantity"]))
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

        if name == "pass_turn":
            r = self.world.pass_turn(kind, aid)
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "list_contacts":
            contacts = self.world.mail().list_contacts(kind, aid)
            return {"ok": True, "message": "contacts", "data": {"contacts": contacts}}

        if name == "read_mail":
            with_whom = args.get("with_whom")
            r = self.world.read_mail(kind, aid, str(with_whom) if with_whom else None)
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "send_message":
            r = self.world.send_message(kind, aid, str(args["to"]), str(args["body"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "done":
            self.done_note = str(args.get("note", "done"))
            return {"ok": True, "message": self.done_note}

        return {"ok": False, "message": f"Unknown tool: {name}"}
