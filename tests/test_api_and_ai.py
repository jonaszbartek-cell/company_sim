"""AI scheduler and HTTP API integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from company_sim.ai.scheduler import AIScheduler
from company_sim.server import create_app
from company_sim.world import World, WorldConfig


class TestAIScheduler:
    def test_round_robin_reaches_all_ai_actors(self):
        world = World.new_game(WorldConfig(ai_company_count=3, starting_cities=3))
        scheduler = AIScheduler()
        acted: set[str] = set()
        original = scheduler._heuristic

        def wrap(w, actor):
            acted.add(f"{actor.kind}:{actor.id}")
            return original(w, actor)

        scheduler._heuristic = wrap  # type: ignore[method-assign]
        expected = {f"{a.kind}:{a.id}" for a in world.iter_ai_actors()}
        # decision_interval is 8s; advance enough for every entity to fire at least once
        for i in range(len(expected) * 20):
            world.time_sec = float(i)
            scheduler.update(world)
        assert acted == expected


class TestHTTPAPI:
    def test_state_ui_and_player_actions(self):
        with TestClient(create_app()) as client:
            pause = client.post("/api/pause", json={"paused": True})
            assert pause.status_code == 200
            assert pause.json()["ok"] is True

            state = client.get("/api/state")
            assert state.status_code == 200
            body = state.json()
            assert body["ai_mode"] in {"off", "online", "fallback"}
            assert "llm" in body
            st = body["state"]
            assert st["paused"] is True
            assert st["content"]["buildings"]
            player = next(c for c in st["companies"] if c["id"] == "player")
            cash0 = player["cash"]

            index = client.get("/")
            assert index.status_code == 200
            assert b"company_sim" in index.content
            assert client.get("/static/app.js").status_code == 200
            assert client.get("/static/styles.css").status_code == 200

            starter = next(
                t
                for t in st["map"]["tiles"]
                if t["plot"] and t["plot"]["owner_id"] == "player"
            )
            built = client.post(
                "/api/player/build",
                json={"x": starter["x"], "y": starter["y"], "building_id": "foundry"},
            )
            assert built.status_code == 200
            assert built.json()["ok"] is True

            again = client.post(
                "/api/player/build",
                json={"x": starter["x"], "y": starter["y"], "building_id": "foundry"},
            )
            assert again.json()["ok"] is False

            unknown = client.post(
                "/api/player/build",
                json={"x": starter["x"], "y": starter["y"], "building_id": "nope"},
            )
            assert unknown.json()["ok"] is False

            oob = client.post("/api/player/build", json={"x": 9999, "y": 9999})
            assert oob.status_code == 200
            assert oob.json()["ok"] is False
            assert "Out of bounds" in oob.json()["message"]

            oob_buy = client.post("/api/player/buy_plot", json={"x": -1, "y": -1})
            assert oob_buy.json()["ok"] is False

            oob_merge = client.post(
                "/api/player/merge_plots",
                json={"x1": 0, "y1": 0, "x2": 9999, "y2": 9999},
            )
            assert oob_merge.status_code == 200
            assert oob_merge.json()["ok"] is False

            unowned = next(
                t
                for t in st["map"]["tiles"]
                if t["kind"] == "plot" and t["plot"] and not t["plot"]["owner_id"]
            )
            bought = client.post(
                "/api/player/buy_plot", json={"x": unowned["x"], "y": unowned["y"]}
            )
            assert bought.json()["ok"] is True

            st2 = client.get("/api/state").json()["state"]
            player2 = next(c for c in st2["companies"] if c["id"] == "player")
            assert player2["cash"] < cash0

            resume = client.post("/api/pause", json={"paused": False})
            assert resume.json()["message"] == "resumed"

    def test_websocket_receives_state(self):
        with TestClient(create_app()) as client:
            client.post("/api/pause", json={"paused": True})
            with client.websocket_connect("/ws") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "state"
                assert "map" in msg["state"]
                assert msg["state"]["player_company_id"] == "player"
