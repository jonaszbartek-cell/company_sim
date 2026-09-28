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
                        "description": "Map of item_id → quantity, e.g. {\"iron\": 5, \"coal\": 3}",
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
                "(the adjacent plot is unchanged). Forbidden on a combined side."
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
            "You CANNOT use the market. To buy goods, post_government_contract with required "
            "resources, then award_government_contract (lowest company bid wins). "
            "Sell plots via propose_plot_sell, buy via propose_plot_buy (accept/reject), build edge roads on owned plots, combine adjacent plots without roads between. "
            "Stay within cash. Use only the provided tools. Be concise."
        )
    return (
        "You run a company. Become the strongest firm: "
        "buy plots via propose_plot_buy (cities own land at start), build foundries, trade on the market, and bid on city government contracts. "
        "When awarded a contract, gather the goods and fulfill_government_contract to get paid. "
        "You may send_message, propose_sell/propose_buy (goods), and propose_plot_buy/propose_plot_sell. Always accept or reject pending proposals addressed to you. "
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
