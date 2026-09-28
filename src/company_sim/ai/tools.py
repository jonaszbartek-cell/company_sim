"""LLM tools → World Action API.

Tool schemas are kept small for local budget-PC models.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from company_sim.actions import ActionError
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
                        "description": "Optional filter by item id (iron_ore, coal, energy, steel, …)",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_plots_for_sale",
            "description": "List plots owned by others you might buy via propose_plot_buy (value, owner, coords).",
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
            "name": "propose_plot_buy",
            "description": "Direct proposal to buy a plot from its owner (escrows cash until accept/reject).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Owner key e.g. city:city_a"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "price": {"type": "integer"},
                },
                "required": ["to", "x", "y", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_plot_sell",
            "description": "Direct proposal to sell a plot you own (locks plot until accept/reject).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "price": {"type": "integer"},
                },
                "required": ["to", "x", "y", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_building",
            "description": (
                "Build on a plot you own. Mine needs specialized_mine; Rig needs "
                "specialized_well. For mine/rig pass method_id at build (locked after)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "building_id": {"type": "string"},
                    "method_id": {
                        "type": "string",
                        "description": "Production method (required choice for mine/rig; locked after build)",
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
            "name": "destroy_building",
            "description": "Destroy your building; returns storage + 10% of build materials (floored).",
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
            "name": "produce",
            "description": "Run one production batch using goods in the building's storage (not personal inventory).",
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
            "name": "deposit_to_building",
            "description": "Move goods from your inventory into building storage (cap 10 per allowed item).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["x", "y", "item_id", "quantity"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "withdraw_from_building",
            "description": "Move goods from building storage into your inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["x", "y", "item_id", "quantity"],
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
            "name": "get_catalog",
            "description": "Look up shared economy catalogs: goods_index, buildings, or production_methods (all agents can see everything).",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "goods | buildings | methods | good",
                    },
                    "id": {
                        "type": "string",
                        "description": "Optional item/building/method id when section=good or for filtering",
                    },
                },
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
            "description": "Standard buy: take goods now from lowest-price sell listings.",
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
            "name": "retract_sell",
            "description": "Retract your sell listing; remaining goods return only to you.",
            "parameters": {
                "type": "object",
                "properties": {"listing_id": {"type": "integer"}},
                "required": ["listing_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retract_buy",
            "description": "Retract your buy listing; remaining escrowed cash returns to you.",
            "parameters": {
                "type": "object",
                "properties": {"listing_id": {"type": "integer"}},
                "required": ["listing_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_sell",
            "description": "Direct sell proposal to another agent (goods reserved until accept/reject).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "price": {"type": "integer"},
                },
                "required": ["to", "item_id", "quantity", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_buy",
            "description": "Direct buy proposal to another agent (cash reserved until accept/reject).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "item_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "price": {"type": "integer"},
                },
                "required": ["to", "item_id", "quantity", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_proposals",
            "description": "List pending direct proposals involving you.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_proposal",
            "description": "Accept a direct proposal addressed to you.",
            "parameters": {
                "type": "object",
                "properties": {"proposal_id": {"type": "integer"}},
                "required": ["proposal_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_proposal",
            "description": "Reject (recipient) or cancel (proposer) a pending direct proposal.",
            "parameters": {
                "type": "object",
                "properties": {"proposal_id": {"type": "integer"}},
                "required": ["proposal_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_government_contract",
            "description": "CITY only. Post a government contract listing required resources; all companies may bid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirements": {
                        "type": "object",
                        "description": "Map of item_id → quantity, e.g. {\"iron_ore\": 5, \"coal\": 3}",
                        "additionalProperties": {"type": "integer"},
                    }
                },
                "required": ["requirements"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bid_government_contract",
            "description": "COMPANY only. Bid a total price to fulfill a city's open government contract.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "integer"},
                    "price": {"type": "integer", "description": "Total cash for the whole basket"},
                },
                "required": ["contract_id", "price"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "award_government_contract",
            "description": "CITY only. Close bidding and award to the lowest bid; city cash is escrowed.",
            "parameters": {
                "type": "object",
                "properties": {"contract_id": {"type": "integer"}},
                "required": ["contract_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fulfill_government_contract",
            "description": "COMPANY only. Deliver all required goods for an awarded contract; receive payment.",
            "parameters": {
                "type": "object",
                "properties": {"contract_id": {"type": "integer"}},
                "required": ["contract_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_government_contracts",
            "description": "List open/awarded government contracts.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_government_contract",
            "description": "CITY only. Cancel an open or awarded (unfulfilled) contract; refund escrow.",
            "parameters": {
                "type": "object",
                "properties": {"contract_id": {"type": "integer"}},
                "required": ["contract_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_road",
            "description": (
                "Build a road on ONE side of a plot you own. "
                "Choose side: N, E, S, or W — only that plot's edge becomes a road "
                "(the adjacent plot is unchanged). Costs 1 steel (placeholder; goods are consumed). "
                "Forbidden on a combined side."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Plot x coordinate"},
                    "y": {"type": "integer", "description": "Plot y coordinate"},
                    "side": {
                        "type": "string",
                        "enum": ["N", "E", "S", "W"],
                        "description": "Which edge of THIS plot gets the road: N, E, S, or W",
                    },
                },
                "required": ["x", "y", "side"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_plots",
            "description": "Combine two adjacent owned plots (flags only). Forbidden if a road is between them.",
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


# City-only tools — player company cannot run these (cities use them via LLM).
CITY_ONLY_TOOLS = frozenset(
    {
        "post_government_contract",
        "award_government_contract",
        "cancel_government_contract",
    }
)

# Meta tools for LLM session control — not meaningful as player UI actions.
PLAYER_EXCLUDED_TOOLS = frozenset({"done"}) | CITY_ONLY_TOOLS


def tool_name(defn: dict[str, Any]) -> str:
    return str(defn["function"]["name"])


# Market / company trading tools cities cannot use.
COMPANY_ONLY_TOOLS = frozenset(
    {
        "get_market",
        "post_sell",
        "post_buy",
        "buy_from_market",
        "retract_sell",
        "retract_buy",
        "bid_government_contract",
        "fulfill_government_contract",
    }
)


def tool_definitions_for(actor: Actor) -> list[dict[str, Any]]:
    """Tool schemas exposed to the LLM for this actor's turn."""
    if actor.kind == "city":
        skip = COMPANY_ONLY_TOOLS
    else:
        skip = CITY_ONLY_TOOLS
    return [d for d in TOOL_DEFINITIONS if tool_name(d) not in skip]


def player_company_tool_definitions() -> list[dict[str, Any]]:
    """Tool schemas a player company can run (same set as company AI agents)."""
    return [d for d in TOOL_DEFINITIONS if tool_name(d) not in PLAYER_EXCLUDED_TOOLS]


def player_tool_catalog() -> list[dict[str, Any]]:
    """Flattened catalog for the web UI / API."""
    out: list[dict[str, Any]] = []
    for defn in player_company_tool_definitions():
        fn = defn["function"]
        params = fn.get("parameters") or {}
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": params.get("properties") or {},
                "required": list(params.get("required") or []),
            }
        )
    return out


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

    pending_inbox = world.proposals.pending_addressed_to(actor.kind, actor.id)
    pending_n = len(pending_inbox)

    return (
        f"Day {world.day}. You are {actor.kind} '{actor.name}' (id={actor.id}).\n"
        f"Cash: {actor.cash} | Inventory: {actor.inventory.as_dict()}\n"
        f"Owned plots ({len(owned)}):\n"
        + ("\n".join(owned_lines) if owned_lines else "  (none)")
        + "\n"
        + (
            f"Pending proposals addressed to you: {pending_n}. "
            "Call list_proposals then accept_proposal or reject_proposal first.\n"
            if pending_n
            else "Pending proposals addressed to you: 0.\n"
        )
        + "RULE: reply with tool calls only (no prose). "
        + (
            "City: list_proposals → accept/reject → done. "
            if actor.kind == "city"
            else (
                "Companies with no land: list_plots_for_sale then ONE propose_plot_buy then done. "
                "Empty owned plot: build_building then done. "
                "Otherwise: get_status → act → done. "
            )
        )
        + "1-3 tools then done."
    )


def system_prompt_for(actor: Actor) -> str:
    base = (
        "CRITICAL: Respond ONLY by calling tools. Never write plans, markdown, or prose. "
        "Each turn: call 1-3 tools, then call done. "
    )
    if actor.kind == "city":
        return (
            base
            + "You administer a city. You CANNOT use the market. "
            "FIRST each turn: list_proposals — if any plot_buy/goods proposals are addressed to you, "
            "accept_proposal (plot_buy price >= 80) or reject_proposal, then done. "
            "Only after clearing pending proposals: post_government_contract / award_government_contract, "
            "propose_plot_sell, build_road (side N/E/S/W, costs 1 steel), or merge_plots. "
            "Do NOT propose_plot_buy for plots you already own."
        )
    return (
        base
        + "You run a company. Goal: strongest firm. "
        "Buy land with propose_plot_buy (cities own plots at start) — one plot offer per turn is enough, then done. "
        "After you own a plot: build_building, set_production_method, deposit_to_building, produce, withdraw, trade. "
        "Use propose_sell/propose_buy for direct goods deals. "
        "Accept or reject pending proposals addressed to you (list_proposals). "
        "Build roads with build_road (side N/E/S/W, costs 1 steel)."
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

        if name == "list_unowned_plots" or name == "list_plots_for_sale" or name == "get_market_overview":
            limit = int(args.get("limit", 8))
            candidates = []
            for t in self.world.grid.tiles:
                if not t.plot or not t.plot.owner_id:
                    continue
                if t.plot.owned_by(kind, aid):
                    continue
                if t.plot.reserved_proposal_id is not None:
                    continue
                candidates.append(t)
            candidates.sort(key=lambda t: t.plot.value if t.plot else 9999)
            return {
                "ok": True,
                "message": "plots",
                "data": {
                    "plots": [
                        {
                            "x": t.x,
                            "y": t.y,
                            "value": t.plot.value if t.plot else None,
                            "plot_type": t.plot.plot_type.value if t.plot else None,
                            "owner": f"{t.plot.owner_kind}:{t.plot.owner_id}" if t.plot else None,
                            "city_id": t.city_id,
                            "roads": t.plot.roads if t.plot else None,
                            "combined": {s: pid for s, pid in t.plot.combined.items() if pid}
                            if t.plot
                            else None,
                        }
                        for t in candidates[:limit]
                    ],
                    "road_build_cost": self.world.config.road_build_cost,
                    "road_build_steel": self.world.config.road_build_steel,
                },
            }

        if name == "propose_plot_buy":
            r = self.world.propose_plot_buy(
                kind,
                aid,
                str(args["to"]),
                int(args["x"]),
                int(args["y"]),
                int(args["price"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "propose_plot_sell":
            r = self.world.propose_plot_sell(
                kind,
                aid,
                str(args["to"]),
                int(args["x"]),
                int(args["y"]),
                int(args["price"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "buy_plot":
            return {
                "ok": False,
                "message": "buy_plot removed — use propose_plot_buy then accept_proposal",
            }

        if name == "build_building":
            building_id = str(args.get("building_id", "foundry"))
            method_id = args.get("method_id")
            r = self.world.build_building(
                kind,
                aid,
                int(args["x"]),
                int(args["y"]),
                building_id,
                method_id=str(method_id) if method_id else None,
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "destroy_building":
            r = self.world.destroy_building(kind, aid, int(args["x"]), int(args["y"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "produce":
            r = self.world.produce(kind, aid, int(args["x"]), int(args["y"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "deposit_to_building":
            r = self.world.deposit_to_building(
                kind,
                aid,
                int(args["x"]),
                int(args["y"]),
                str(args["item_id"]),
                int(args["quantity"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "withdraw_from_building":
            r = self.world.withdraw_from_building(
                kind,
                aid,
                int(args["x"]),
                int(args["y"]),
                str(args["item_id"]),
                int(args["quantity"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "set_production_method":
            r = self.world.set_production_method(
                kind, aid, int(args["x"]), int(args["y"]), str(args["method_id"])
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "get_catalog":
            section = str(args.get("section") or "goods").lower()
            cid = args.get("id")
            content = self.world.content
            if section in ("good", "goods", "item", "items"):
                if cid:
                    try:
                        card = content.good_card(str(cid))
                    except KeyError:
                        return {"ok": False, "message": f"Unknown item: {cid}"}
                    return {"ok": True, "message": "good", "data": card}
                return {
                    "ok": True,
                    "message": "goods_index",
                    "data": {"goods_index": content.goods_index},
                }
            if section in ("building", "buildings"):
                if cid:
                    if not content.buildings.has(str(cid)):
                        return {"ok": False, "message": f"Unknown building: {cid}"}
                    b = content.buildings.get(str(cid))
                    return {
                        "ok": True,
                        "message": "building",
                        "data": {
                            **b.to_public_dict(),
                            "methods": list(content.methods_by_building.get(b.id, [])),
                            "storage_capacity": content.storage_capacity_for_building(b.id),
                        },
                    }
                return {
                    "ok": True,
                    "message": "buildings",
                    "data": {
                        "buildings": content.to_public_dict()["buildings"],
                    },
                }
            if section in ("method", "methods", "production", "production_methods"):
                if cid:
                    try:
                        m = content.production.get(str(cid))
                    except KeyError:
                        return {"ok": False, "message": f"Unknown method: {cid}"}
                    return {"ok": True, "message": "method", "data": m.to_public_dict()}
                return {
                    "ok": True,
                    "message": "methods",
                    "data": {"production_methods": content.production.to_public_dict()},
                }
            return {
                "ok": False,
                "message": "section must be goods|buildings|methods|good",
            }

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

        if name == "retract_sell":
            r = self.world.retract_sell(kind, aid, int(args["listing_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "retract_buy":
            r = self.world.retract_buy(kind, aid, int(args["listing_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "propose_sell":
            r = self.world.propose_sell(
                kind,
                aid,
                str(args["to"]),
                str(args["item_id"]),
                int(args["quantity"]),
                int(args["price"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "propose_buy":
            r = self.world.propose_buy(
                kind,
                aid,
                str(args["to"]),
                str(args["item_id"]),
                int(args["quantity"]),
                int(args["price"]),
            )
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "list_proposals":
            r = self.world.list_proposals(kind, aid)
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "accept_proposal":
            r = self.world.accept_proposal(kind, aid, int(args["proposal_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "reject_proposal":
            r = self.world.reject_proposal(kind, aid, int(args["proposal_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "post_government_contract":
            reqs = args.get("requirements") or {}
            if not isinstance(reqs, dict):
                return {"ok": False, "message": "requirements must be an object"}
            r = self.world.post_government_contract(kind, aid, {str(k): int(v) for k, v in reqs.items()})
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "bid_government_contract":
            r = self.world.bid_government_contract(kind, aid, int(args["contract_id"]), int(args["price"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "award_government_contract":
            r = self.world.award_government_contract(kind, aid, int(args["contract_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "fulfill_government_contract":
            r = self.world.fulfill_government_contract(kind, aid, int(args["contract_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "list_government_contracts":
            r = self.world.list_government_contracts(kind, aid)
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "cancel_government_contract":
            r = self.world.cancel_government_contract(kind, aid, int(args["contract_id"]))
            return {"ok": r.ok, "message": r.message, "data": r.data}

        if name == "build_road":
            r = self.world.build_road(kind, aid, int(args["x"]), int(args["y"]), str(args["side"]))
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
