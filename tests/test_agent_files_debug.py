"""Per-agent instruction stubs, prompt packing isolation, LLM debug traces."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from company_sim.agent_files import AgentFileStore, instructions_filename
from company_sim.server import create_app
from company_sim.world import World, WorldConfig


def _world(tmp: Path, *, llm_debug: bool = False, companies: int = 2) -> World:
    return World.new_game(
        WorldConfig(
            map_size=6,
            starting_cities=1,
            ai_company_count=companies,
            save_dir=str(tmp),
            min_seconds_between_turns=0.0,
            llm_debug=llm_debug,
        )
    )


def test_startup_creates_company_and_city_instruction_placeholders():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        instr = root / "instructions"
        assert instr.is_dir()

        expected = {
            instructions_filename("company", "player"),
            instructions_filename("company", "ai_1"),
            instructions_filename("company", "ai_2"),
            instructions_filename("city", "city_a"),
        }
        found = {p.name for p in instr.glob("*.txt")}
        assert expected == found

        company = (instr / "COMPANY_INSTRUCTIONS_ai_1.txt").read_text(encoding="utf-8")
        assert "COMPANY INSTRUCTIONS_ai_1" in company
        assert "placeholder" in company
        assert "agent: company:ai_1" in company

        city = (instr / "CITY_INSTRUCTIONS_city_a.txt").read_text(encoding="utf-8")
        assert "CITY INSTRUCTIONS_city_a" in city
        assert "placeholder" in city


def test_pack_for_agent_only_includes_that_agents_private_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        assert w.file_store is not None
        ai1 = w.companies["ai_1"]
        bundle = w.file_store.pack_for_agent(w, ai1, compact=True)

        paths = bundle.path_list()
        assert any("COMPANY_INSTRUCTIONS_ai_1" in p for p in paths)
        assert any(p.endswith("agents/ai_1.txt") or p == "agents/ai_1.txt" for p in paths)

        # Must NOT pack other agents' private instruction or agent files
        joined = "\n".join(paths)
        assert "COMPANY_INSTRUCTIONS_ai_2" not in joined
        assert "COMPANY_INSTRUCTIONS_player" not in joined
        assert "CITY_INSTRUCTIONS_city_a" not in joined
        assert "agents/ai_2.txt" not in joined
        assert "agents/player.txt" not in joined

        # Prompt body must not contain other agents' private cash headers
        assert "=== AGENT company:ai_1 ===" in bundle.prompt_text
        assert "=== AGENT company:ai_2 ===" not in bundle.prompt_text
        assert "=== AGENT company:player ===" not in bundle.prompt_text
        assert "FILE ACCESS" in bundle.prompt_text
        assert "active_agent: company:ai_1" in bundle.prompt_text


def test_pack_for_city_uses_city_instructions_only():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        city = next(iter(w.grid.cities.values()))
        bundle = w.file_store.pack_for_agent(w, city, compact=True)
        paths = "\n".join(bundle.path_list())
        assert "CITY_INSTRUCTIONS_city_a" in paths
        assert "COMPANY_INSTRUCTIONS_" not in paths
        assert "active_agent: city:city_a" in bundle.prompt_text


def test_llm_debug_writes_trace_when_enabled():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root, llm_debug=True)
        assert w.llm_debug_log is not None
        assert w.llm_debug_log.enabled
        assert (root / "llm_debug").is_dir()

        actor = w.companies["ai_1"]
        bundle = w.file_store.pack_for_agent(w, actor, compact=True)
        path = w.llm_debug_log.write_turn(
            actor_kind=actor.kind,
            actor_id=actor.id,
            day=w.day,
            system="sys",
            bundle=bundle,
            rounds=[{"assistant_content": "hi", "tool_calls": [], "tool_results": []}],
            final_note="done",
        )
        assert path is not None and path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "LLM DEBUG TRACE" in text
        assert "files packed into prompt" in text
        assert "COMPANY_INSTRUCTIONS_ai_1" in text
        assert (root / "llm_debug" / "index.log").is_file()


def test_llm_debug_disabled_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root, llm_debug=False)
        assert w.llm_debug_log is not None
        assert not w.llm_debug_log.enabled
        actor = w.companies["ai_1"]
        bundle = w.file_store.pack_for_agent(w, actor, compact=True)
        path = w.llm_debug_log.write_turn(
            actor_kind=actor.kind,
            actor_id=actor.id,
            day=w.day,
            system="sys",
            bundle=bundle,
            rounds=[],
            final_note="x",
        )
        assert path is None
        assert not (root / "llm_debug").exists() or not list((root / "llm_debug").rglob("*.txt"))


def test_setup_api_llm_debug_creates_instructions_and_exposes_endpoint(monkeypatch, tmp_path):
    import company_sim.world as world_mod

    monkeypatch.setattr(world_mod, "default_save_dir", lambda: tmp_path)

    app = create_app()
    client = TestClient(app)
    res = client.post(
        "/api/setup",
        json={
            "ai_companies": 1,
            "cities": 1,
            "map_size": 6,
            "llm_debug": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["state"]["config"]["llm_debug"] is True
    assert data["state"]["llm_debug"]["enabled"] is True
    names = data["state"]["llm_debug"]["instructions"]
    assert "COMPANY_INSTRUCTIONS_ai_1.txt" in names
    assert "CITY_INSTRUCTIONS_city_a.txt" in names
    assert (tmp_path / "instructions" / "COMPANY_INSTRUCTIONS_ai_1.txt").is_file()

    dbg = client.get("/api/llm_debug")
    assert dbg.status_code == 200
    body = dbg.json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert "COMPANY_INSTRUCTIONS_player.txt" in body["instructions"]

    w = app.state.world
    assert w is not None and w.llm_debug_log is not None
    actor = w.companies["ai_1"]
    bundle = w.file_store.pack_for_agent(w, actor)
    path = w.llm_debug_log.write_turn(
        actor_kind=actor.kind,
        actor_id=actor.id,
        day=w.day,
        system="sys",
        bundle=bundle,
        rounds=[{"assistant_content": "test", "tool_calls": [], "tool_results": []}],
        final_note="ok",
    )
    assert path is not None
    rel = str(path.relative_to(w.llm_debug_log.debug_dir))
    trace = client.get("/api/llm_debug/trace", params={"path": rel})
    assert trace.status_code == 200
    tbody = trace.json()
    assert tbody["ok"] is True
    assert "LLM DEBUG TRACE" in tbody["text"]
    assert "COMPANY_INSTRUCTIONS_ai_1" in tbody["text"]


def test_switching_actors_rebuilds_distinct_file_sets():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        store: AgentFileStore = w.file_store  # type: ignore[assignment]
        a = store.pack_for_agent(w, w.companies["ai_1"])
        b = store.pack_for_agent(w, w.companies["ai_2"])
        assert a.actor_key == "company:ai_1"
        assert b.actor_key == "company:ai_2"
        assert set(a.path_list()) != set(b.path_list())
        assert any("ai_1" in p for p in a.path_list())
        assert any("ai_2" in p for p in b.path_list())
        assert not any("ai_2.txt" in p for p in a.path_list())
        assert not any("ai_1.txt" in p for p in b.path_list())
