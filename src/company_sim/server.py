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
from company_sim.map_grid import BuildingType
from company_sim.world import World, WorldConfig

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class BuyPlotBody(BaseModel):
    x: int
    y: int


class BuildBody(BaseModel):
    x: int
    y: int
    building_type: str = "workshop"


class PauseBody(BaseModel):
    paused: bool


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
            await _broadcast(clients, {"type": "state", "state": world.to_public_dict(), "ai": scheduler.last_thought})
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

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return {"state": world.to_public_dict(), "ai": scheduler.last_thought}

    @app.post("/api/pause")
    def pause(body: PauseBody) -> dict[str, Any]:
        result = world.set_paused(body.paused)
        return {"ok": result.ok, "message": result.message}

    @app.post("/api/player/buy_plot")
    def buy_plot(body: BuyPlotBody) -> dict[str, Any]:
        try:
            result = world.buy_plot(world.player_company_id, body.x, body.y)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except ActionError as exc:
            return {"ok": False, "message": exc.message}

    @app.post("/api/player/build")
    def build(body: BuildBody) -> dict[str, Any]:
        try:
            btype = BuildingType(body.building_type)
            result = world.build_building(world.player_company_id, body.x, body.y, btype)
            return {"ok": result.ok, "message": result.message, "data": result.data}
        except (ActionError, ValueError) as exc:
            msg = exc.message if isinstance(exc, ActionError) else str(exc)
            return {"ok": False, "message": msg}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        clients.add(ws)
        try:
            await ws.send_json({"type": "state", "state": world.to_public_dict(), "ai": scheduler.last_thought})
            while True:
                # Client may send commands later; keep alive by receiving
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
