"""HTTP + WebSocket API for the web UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from company_sim.actions import ActionError
from company_sim.ai.scheduler import AIScheduler
from company_sim.world import World, WorldConfig

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class BuyPlotBody(BaseModel):
    x: int
    y: int


class BuildBody(BaseModel):
    x: int
    y: int
    building_id: str = "foundry"


class PauseBody(BaseModel):
    paused: bool


class RoadBody(BaseModel):
    x: int
    y: int


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


def create_app() -> FastAPI:
    world = World.new_game(WorldConfig())
    scheduler = AIScheduler()
    clients: set[WebSocket] = set()
    stop_event = asyncio.Event()

    async def sim_loop() -> None:
        tick_hz = world.config.tick_hz
        dt = 1.0 / tick_hz
        while not stop_event.is_set():
            world.tick(dt)
            scheduler.update(world)
            await _broadcast(
                clients,
                {
                    "type": "state",
                    "state": world.to_public_dict(),
                    "ai": scheduler.last_thought,
                    "ai_mode": scheduler.llm_mode,
                },
            )
            await asyncio.sleep(dt)

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
        return world.player_company_id

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return {
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
        result = world.set_paused(body.paused)
        return {"ok": result.ok, "message": result.message}

    @app.post("/api/player/buy_plot")
    def buy_plot(body: BuyPlotBody) -> dict[str, Any]:
        try:
            result = world.buy_plot("company", _player(), body.x, body.y)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/build")
    def build(body: BuildBody) -> dict[str, Any]:
        try:
            result = world.build_building(
                "company", _player(), body.x, body.y, body.building_id
            )
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/produce")
    def produce(body: ProduceBody) -> dict[str, Any]:
        try:
            result = world.produce("company", _player(), body.x, body.y)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/build_road")
    def build_road(body: RoadBody) -> dict[str, Any]:
        try:
            result = world.company_build_road(_player(), body.x, body.y)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/merge_plots")
    def merge_plots(body: MergeBody) -> dict[str, Any]:
        try:
            result = world.merge_plots(
                "company", _player(), body.x1, body.y1, body.x2, body.y2
            )
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/market/sell")
    def market_sell(body: MarketOrderBody) -> dict[str, Any]:
        try:
            result = world.post_sell("company", _player(), body.item_id, body.quantity, body.price)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/market/buy_order")
    def market_buy_order(body: MarketOrderBody) -> dict[str, Any]:
        try:
            result = world.post_buy("company", _player(), body.item_id, body.quantity, body.price)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/market/buy")
    def market_buy(body: MarketBuyBody) -> dict[str, Any]:
        try:
            result = world.buy_from_market("company", _player(), body.item_id, body.quantity)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/pass")
    def pass_turn() -> dict[str, Any]:
        try:
            result = world.pass_turn("company", _player())
            return {"ok": result.ok, "message": result.message}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.get("/api/market")
    def get_market() -> dict[str, Any]:
        return world.market.to_public_dict()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        clients.add(ws)
        try:
            await ws.send_json(
                {"type": "state", "state": world.to_public_dict(), "ai": scheduler.last_thought}
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
