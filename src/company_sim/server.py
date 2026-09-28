"""HTTP + WebSocket API for the web UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from company_sim.actions import ActionError
from company_sim.ai.scheduler import AIScheduler
from company_sim.ai.tools import ToolExecutor, player_tool_catalog
from company_sim.world import World, WorldConfig

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class SetupBody(BaseModel):
    ai_companies: int = Field(default=2, ge=0, le=12)
    cities: int = Field(default=1, ge=1, le=8)
    map_size: int = Field(default=12, ge=2, le=128)
    # Percent of all plots that become specialized mine/well resource clusters
    specialized_plot_percent: float = Field(default=15.0, ge=0.0, le=100.0)
    llm_debug: bool = False


class BuildBody(BaseModel):
    x: int
    y: int
    building_id: str = "foundry"
    method_id: str | None = None


class PauseBody(BaseModel):
    paused: bool


class RoadBody(BaseModel):
    x: int
    y: int
    side: str


class MergeBody(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class ProduceBody(BaseModel):
    x: int
    y: int


class MarketOrderBody(BaseModel):
    item_id: str
    quantity: int
    price: int = 0


class MarketBuyBody(BaseModel):
    item_id: str
    quantity: int


class MessageBody(BaseModel):
    to: str
    body: str


class RetractBody(BaseModel):
    listing_id: int


class ProposeBody(BaseModel):
    to: str
    item_id: str
    quantity: int
    price: int


class PlotProposeBody(BaseModel):
    to: str
    x: int
    y: int
    price: int


class ProposalIdBody(BaseModel):
    proposal_id: int


class GovBidBody(BaseModel):
    contract_id: int
    price: int


class GovContractIdBody(BaseModel):
    contract_id: int


class ProductionMethodBody(BaseModel):
    x: int
    y: int
    method_id: str


class BuildingGoodsBody(BaseModel):
    x: int
    y: int
    item_id: str
    quantity: int


class CoordBody(BaseModel):
    x: int
    y: int


class PlayerActionBody(BaseModel):
    """Run any company agent tool by name (same ToolExecutor path as the LLM)."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


def create_app() -> FastAPI:
    world: World | None = None
    scheduler = AIScheduler()
    clients: set[WebSocket] = set()
    stop_event = asyncio.Event()

    def _require_world() -> World:
        if world is None or not world.started:
            raise ActionError("Game not started — choose setup options first")
        return world

    async def sim_loop() -> None:
        while not stop_event.is_set():
            w = world
            if w is not None and w.started:
                tick_hz = w.config.tick_hz
                dt = 1.0 / tick_hz
                w.tick(dt)
                scheduler.update(w)
                await _broadcast(
                    clients,
                    {
                        "type": "state",
                        "state": w.to_public_dict(),
                        "ai": scheduler.last_thought,
                        "ai_mode": scheduler.llm_mode,
                    },
                )
                await asyncio.sleep(dt)
            else:
                await _broadcast(
                    clients,
                    {
                        "type": "setup",
                        "started": False,
                        "defaults": {
                            "ai_companies": 2,
                            "cities": 1,
                            "map_size": 12,
                            "specialized_plot_percent": 15,
                            "llm_debug": False,
                        },
                    },
                )
                await asyncio.sleep(0.5)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(sim_loop())
        try:
            yield
        finally:
            stop_event.set()
            await task

    app = FastAPI(title="company_sim", lifespan=lifespan)
    app.state.world = world
    app.state.scheduler = scheduler

    def _player() -> str:
        return _require_world().player_company_id

    def _ok(result) -> dict[str, Any]:
        return {"ok": result.ok, "message": result.message, "data": result.data}

    def _err(exc: ActionError) -> dict[str, Any]:
        return {"ok": False, "message": exc.message}

    @app.get("/api/setup")
    def get_setup() -> dict[str, Any]:
        return {
            "started": world is not None and world.started,
            "defaults": {
                "ai_companies": 2,
                "cities": 1,
                "map_size": 12,
                "specialized_plot_percent": 15,
                "llm_debug": False,
            },
            "config": None
            if world is None
            else {
                "ai_companies": world.config.ai_company_count,
                "cities": world.config.starting_cities,
                "map_size": world.config.map_size,
                "specialized_plot_percent": world.config.specialized_plot_percent,
                "llm_debug": world.config.llm_debug,
            },
        }

    @app.post("/api/setup")
    def post_setup(body: SetupBody) -> dict[str, Any]:
        nonlocal world
        if world is not None and world.started:
            return {"ok": False, "message": "Game already started"}
        try:
            world = World.new_game(
                WorldConfig(
                    map_size=body.map_size,
                    starting_cities=body.cities,
                    ai_company_count=body.ai_companies,
                    specialized_plot_percent=body.specialized_plot_percent,
                    llm_debug=bool(body.llm_debug),
                )
            )
            app.state.world = world
            return {
                "ok": True,
                "message": (
                    f"Started {body.map_size}x{body.map_size} map with "
                    f"{body.cities} cities and {body.ai_companies} AI companies"
                    + (" (LLM debug on)" if body.llm_debug else "")
                ),
                "state": world.to_public_dict(),
            }
        except ActionError as exc:
            return _err(exc)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        if world is None or not world.started:
            return {
                "started": False,
                "state": None,
                "ai": None,
                "ai_mode": None,
                "defaults": {
                    "ai_companies": 2,
                    "cities": 1,
                    "map_size": 12,
                    "specialized_plot_percent": 15,
                    "llm_debug": False,
                },
            }
        return {
            "started": True,
            "state": world.to_public_dict(),
            "ai": scheduler.last_thought,
            "ai_mode": scheduler.llm_mode,
            "llm": {
                "enabled": scheduler.llm.config.enabled,
                "model": scheduler.llm.config.model,
                "base_url": scheduler.llm.config.base_url,
            },
        }

    @app.get("/api/llm_debug")
    def get_llm_debug() -> dict[str, Any]:
        w = world
        if w is None or not w.started:
            return {"ok": False, "message": "Game not started", "enabled": False, "traces": []}
        dbg = w.llm_debug_log
        enabled = bool(w.config.llm_debug)
        instructions: list[str] = []
        if w.file_store is not None and w.file_store.instructions_dir.exists():
            instructions = sorted(p.name for p in w.file_store.instructions_dir.glob("*.txt"))
        traces = [] if dbg is None else dbg.recent_traces(40)
        return {
            "ok": True,
            "enabled": enabled,
            "instructions": instructions,
            "traces": traces,
            "last_summary": None if dbg is None else dbg.last_summary,
            "last_trace": None
            if dbg is None or dbg.last_trace_path is None
            else str(dbg.last_trace_path.relative_to(dbg.debug_dir)),
        }

    @app.get("/api/llm_debug/trace")
    def get_llm_debug_trace(path: str) -> dict[str, Any]:
        try:
            w = _require_world()
        except ActionError as exc:
            return {"ok": False, "message": exc.message, "text": None}
        dbg = w.llm_debug_log
        if dbg is None or not dbg.enabled:
            return {"ok": False, "message": "LLM debug is not enabled", "text": None}
        text = dbg.read_trace(path)
        if text is None:
            return {"ok": False, "message": f"Trace not found: {path}", "text": None}
        return {"ok": True, "path": path, "text": text}

    @app.post("/api/pause")
    def pause(body: PauseBody) -> dict[str, Any]:
        try:
            result = _require_world().set_paused(body.paused)
            return {"ok": result.ok, "message": result.message}
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/build")
    def build(body: BuildBody) -> dict[str, Any]:
        try:
            result = _require_world().build_building(
                "company",
                _player(),
                body.x,
                body.y,
                body.building_id,
                method_id=body.method_id,
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/produce")
    def produce(body: ProduceBody) -> dict[str, Any]:
        try:
            result = _require_world().produce("company", _player(), body.x, body.y)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/set_production_method")
    def set_production_method(body: ProductionMethodBody) -> dict[str, Any]:
        try:
            result = _require_world().set_production_method(
                "company", _player(), body.x, body.y, body.method_id
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/deposit_to_building")
    def deposit_to_building(body: BuildingGoodsBody) -> dict[str, Any]:
        try:
            result = _require_world().deposit_to_building(
                "company", _player(), body.x, body.y, body.item_id, body.quantity
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/withdraw_from_building")
    def withdraw_from_building(body: BuildingGoodsBody) -> dict[str, Any]:
        try:
            result = _require_world().withdraw_from_building(
                "company", _player(), body.x, body.y, body.item_id, body.quantity
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/destroy_building")
    def destroy_building(body: CoordBody) -> dict[str, Any]:
        try:
            result = _require_world().destroy_building("company", _player(), body.x, body.y)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/catalog")
    def get_catalog(section: str = "goods", id: str | None = None) -> dict[str, Any]:
        """Shared goods/buildings/methods catalogs (same data every agent can see)."""
        try:
            w = _require_world()
            ex = ToolExecutor(w, w.get_actor("company", _player()))
            args: dict[str, Any] = {"section": section}
            if id:
                args["id"] = id
            return ex.execute("get_catalog", args)
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/player/tools")
    def get_player_tools() -> dict[str, Any]:
        """List every company-agent tool the player can run from the UI."""
        return {
            "ok": True,
            "tools": player_tool_catalog(),
            "note": (
                "Player runs the same ToolExecutor as company AI agents. "
                "City-only tools (post/award/cancel government contracts) and "
                "LLM meta tool 'done' are excluded."
            ),
        }

    @app.post("/api/player/action")
    def player_action(body: PlayerActionBody) -> dict[str, Any]:
        """Dispatch a named agent tool for the player company."""
        try:
            w = _require_world()
            actor = w.get_actor("company", _player())
            allowed = {t["name"] for t in player_tool_catalog()}
            if body.name not in allowed:
                return {
                    "ok": False,
                    "message": (
                        f"Unknown or unavailable tool for player company: {body.name}. "
                        f"Use GET /api/player/tools for the list."
                    ),
                }
            executor = ToolExecutor(w, actor)
            result = executor.execute(body.name, body.arguments or {})
            # Persist after tool side-effects (ToolExecutor calls world methods that usually save)
            w.persistence.save_all(w)
            return result
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/plots_for_sale")
    def plots_for_sale(limit: int = 24) -> dict[str, Any]:
        try:
            w = _require_world()
            actor = w.get_actor("company", _player())
            executor = ToolExecutor(w, actor)
            return executor.execute("list_plots_for_sale", {"limit": limit})
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/build_road")
    def build_road(body: RoadBody) -> dict[str, Any]:
        try:
            result = _require_world().company_build_road(_player(), body.x, body.y, body.side)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/merge_plots")
    def merge_plots(body: MergeBody) -> dict[str, Any]:
        try:
            result = _require_world().merge_plots(
                "company", _player(), body.x1, body.y1, body.x2, body.y2
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/market/sell")
    def market_sell(body: MarketOrderBody) -> dict[str, Any]:
        try:
            result = _require_world().post_sell(
                "company", _player(), body.item_id, body.quantity, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/market/buy_order")
    def market_buy_order(body: MarketOrderBody) -> dict[str, Any]:
        try:
            result = _require_world().post_buy(
                "company", _player(), body.item_id, body.quantity, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/market/buy")
    def market_buy(body: MarketBuyBody) -> dict[str, Any]:
        try:
            result = _require_world().buy_from_market(
                "company", _player(), body.item_id, body.quantity
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/market/retract_sell")
    def market_retract_sell(body: RetractBody) -> dict[str, Any]:
        try:
            result = _require_world().retract_sell("company", _player(), body.listing_id)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/market/retract_buy")
    def market_retract_buy(body: RetractBody) -> dict[str, Any]:
        try:
            result = _require_world().retract_buy("company", _player(), body.listing_id)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/propose_sell")
    def propose_sell(body: ProposeBody) -> dict[str, Any]:
        try:
            result = _require_world().propose_sell(
                "company", _player(), body.to, body.item_id, body.quantity, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/propose_buy")
    def propose_buy(body: ProposeBody) -> dict[str, Any]:
        try:
            result = _require_world().propose_buy(
                "company", _player(), body.to, body.item_id, body.quantity, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/propose_plot_sell")
    def propose_plot_sell(body: PlotProposeBody) -> dict[str, Any]:
        try:
            result = _require_world().propose_plot_sell(
                "company", _player(), body.to, body.x, body.y, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/propose_plot_buy")
    def propose_plot_buy(body: PlotProposeBody) -> dict[str, Any]:
        try:
            result = _require_world().propose_plot_buy(
                "company", _player(), body.to, body.x, body.y, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/accept_proposal")
    def accept_proposal(body: ProposalIdBody) -> dict[str, Any]:
        try:
            result = _require_world().accept_proposal("company", _player(), body.proposal_id)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/reject_proposal")
    def reject_proposal(body: ProposalIdBody) -> dict[str, Any]:
        try:
            result = _require_world().reject_proposal("company", _player(), body.proposal_id)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/proposals")
    def get_proposals() -> dict[str, Any]:
        try:
            result = _require_world().list_proposals("company", _player())
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/government_contracts")
    def get_gov_contracts() -> dict[str, Any]:
        try:
            result = _require_world().list_government_contracts("company", _player())
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/bid_government_contract")
    def bid_gov(body: GovBidBody) -> dict[str, Any]:
        try:
            result = _require_world().bid_government_contract(
                "company", _player(), body.contract_id, body.price
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/fulfill_government_contract")
    def fulfill_gov(body: GovContractIdBody) -> dict[str, Any]:
        try:
            result = _require_world().fulfill_government_contract(
                "company", _player(), body.contract_id
            )
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/pass")
    def pass_turn() -> dict[str, Any]:
        try:
            result = _require_world().pass_turn("company", _player())
            return {"ok": result.ok, "message": result.message}
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/market")
    def get_market() -> dict[str, Any]:
        try:
            return _require_world().market.to_public_dict()
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/mail")
    def get_mail(with_whom: str | None = None) -> dict[str, Any]:
        try:
            result = _require_world().read_mail("company", _player(), with_whom)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.get("/api/mail/contacts")
    def mail_contacts() -> dict[str, Any]:
        try:
            contacts = _require_world().mail().list_contacts("company", _player())
            return {"ok": True, "contacts": contacts}
        except ActionError as exc:
            return _err(exc)

    @app.post("/api/player/message")
    def player_message(body: MessageBody) -> dict[str, Any]:
        try:
            result = _require_world().send_message("company", _player(), body.to, body.body)
            return _ok(result)
        except ActionError as exc:
            return _err(exc)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        clients.add(ws)
        try:
            if world is not None and world.started:
                await ws.send_json(
                    {
                        "type": "state",
                        "state": world.to_public_dict(),
                        "ai": scheduler.last_thought,
                    }
                )
            else:
                await ws.send_json(
                    {
                        "type": "setup",
                        "started": False,
                        "defaults": {
                            "ai_companies": 2,
                            "cities": 1,
                            "map_size": 12,
                            "specialized_plot_percent": 15,
                        },
                    }
                )
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


async def _broadcast(clients: set[WebSocket], payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)
