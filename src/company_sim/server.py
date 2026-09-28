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
from company_sim.world import World, WorldConfig

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class SetupBody(BaseModel):
    ai_companies: int = Field(default=2, ge=0, le=12)
    cities: int = Field(default=1, ge=1, le=8)
    map_size: int = Field(default=12, ge=2, le=40)


class BuildBody(BaseModel):
    x: int
    y: int
    building_id: str = "foundry"


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
            "defaults": {"ai_companies": 2, "cities": 1, "map_size": 12},
            "config": None
            if world is None
            else {
                "ai_companies": world.config.ai_company_count,
                "cities": world.config.starting_cities,
                "map_size": world.config.map_size,
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
                )
            )
            app.state.world = world
            return {
                "ok": True,
                "message": (
                    f"Started {body.map_size}x{body.map_size} map with "
                    f"{body.cities} cities and {body.ai_companies} AI companies"
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
                "defaults": {"ai_companies": 2, "cities": 1, "map_size": 12},
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
                "company", _player(), body.x, body.y, body.building_id
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
                        "defaults": {"ai_companies": 2, "cities": 1, "map_size": 12},
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
