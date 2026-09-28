#!/usr/bin/env python3
"""Live LLM playtest: run several AI turns with Ollama and print tool choices."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# Must set before importing LLM client defaults used by scheduler
os.environ["COMPANY_SIM_LLM"] = "1"
os.environ["COMPANY_SIM_LLM_MODEL"] = os.environ.get(
    "COMPANY_SIM_LLM_MODEL", "qwen2.5:3b-instruct"
)
os.environ["COMPANY_SIM_LLM_TIMEOUT"] = os.environ.get("COMPANY_SIM_LLM_TIMEOUT", "180")
os.environ["COMPANY_SIM_LLM_MAX_ROUNDS"] = os.environ.get("COMPANY_SIM_LLM_MAX_ROUNDS", "6")
os.environ["COMPANY_SIM_LLM_NUM_CTX"] = os.environ.get("COMPANY_SIM_LLM_NUM_CTX", "16384")

from company_sim.ai.llm_client import LLMClient, LLMConfig
from company_sim.ai.scheduler import AIScheduler
from company_sim.world import World, WorldConfig


def main() -> None:
    cfg = LLMConfig.from_env()
    client = LLMClient(cfg)
    print("=== LLM CONNECTIVITY ===")
    print(
        f"enabled={cfg.enabled} model={cfg.model} url={cfg.base_url} "
        f"num_ctx={cfg.num_ctx} max_rounds={cfg.max_tool_rounds}"
    )
    print(f"available={client.available()}")
    if not client.available():
        raise SystemExit("Ollama not reachable — aborting")

    td = Path(tempfile.mkdtemp(prefix="llm_play_"))
    print(f"save_dir={td}")

    world = World.new_game(
        WorldConfig(
            map_size=8,
            starting_cities=1,
            ai_company_count=2,
            save_dir=str(td),
            min_seconds_between_turns=0.0,
            player_starting_cash=20_000,
            market_seed_qty=100,
            market_seed_price=1,
            llm_debug=True,
        )
    )
    # Give AI companies cash + construction materials so they can buy/build
    for aid in ("ai_1", "ai_2"):
        c = world.companies[aid]
        c.cash = 20_000
        c.inventory.set("construction_materials", 40)
        c.inventory.set("steel", 10)
        c.inventory.set("iron_ore", 5)
        c.inventory.set("coal", 5)
        c.inventory.set("energy", 5)

    # City needs steel for roads / some heuristic paths; cash for ops
    city = world.grid.cities["city_a"]
    city.cash = max(city.cash, 5_000)
    city.inventory.set("steel", 20)

    # Player passes automatically so days can advance on company acts
    world.companies["player"].acted_this_day = True

    sched = AIScheduler(llm=client)
    print(f"scheduler llm_mode={sched.llm_mode} thought={sched.last_thought}")

    turns = int(os.environ.get("COMPANY_SIM_LLM_PLAY_TURNS", "16"))
    tool_hits: list[str] = []
    print(f"\n=== RUNNING {turns} LLM TURNS ===")
    for i in range(turns):
        # Keep player marked acted so day can roll when AIs finish
        world.companies["player"].acted_this_day = True
        actor = world.current_turn_actor()
        # Skip player in turn rotation
        skips = 0
        while actor is not None and actor.id == "player" and skips < 10:
            world.advance_ai_turn()
            actor = world.current_turn_actor()
            skips += 1
        if actor is None:
            print(f"turn {i+1}: no actor")
            break
        if actor.acted_this_day:
            world.advance_ai_turn()
            continue

        day_before = world.day
        cash_before = getattr(actor, "cash", None)
        plots_before = len(world.owned_plots(actor.kind, actor.id))
        print(f"\n--- Turn {i+1}: {actor.kind}:{actor.id} ({actor.name}) day={day_before} ---")

        note = sched._run_llm_session(world, actor)
        if not actor.acted_this_day:
            try:
                world.pass_turn(actor.kind, actor.id)
            except Exception:
                actor.mark_acted()
        world.persistence.save_all(world)
        world.advance_ai_turn()
        sched.last_thought = note

        plots_after = len(world.owned_plots(actor.kind, actor.id))
        cash_after = getattr(actor, "cash", None)
        print(f"result: {note}")
        if cash_before is not None:
            print(
                f"cash: {cash_before} → {cash_after} | plots: {plots_before} → "
                f"{plots_after} | day: {day_before} → {world.day}"
            )

        dbg = world.llm_debug_log
        if dbg and dbg.last_trace_path and dbg.last_trace_path.is_file():
            text = dbg.last_trace_path.read_text(encoding="utf-8")
            print(f"trace: {dbg.last_trace_path.name} ({len(text)} chars)")
            for ln in text.splitlines():
                if any(
                    k in ln
                    for k in (
                        "TOOL",
                        "tool_calls",
                        "get_status",
                        "propose_",
                        "build_",
                        "produce",
                        "buy_",
                        "post_",
                        "done",
                        "pass_turn",
                        "deposit_",
                        "set_production",
                        "accept_",
                        "list_plots",
                    )
                ):
                    print(" ", ln[:220])
                    if "→" in ln or "tool_calls" in ln or ln.strip().startswith("- "):
                        tool_hits.append(ln.strip()[:160])

    print("\n=== WORLD SNAPSHOT ===")
    print(f"day={world.day}")
    for cid, c in world.companies.items():
        owned = world.owned_plots("company", cid)
        blds = sum(1 for t in owned if t.plot and t.plot.building)
        print(
            f"  {cid}: cash={c.cash} plots={len(owned)} buildings={blds} "
            f"inv_keys={list(c.inventory.as_dict())[:8]}"
        )
    for city_id, city_obj in world.grid.cities.items():
        owned = world.owned_plots("city", city_id)
        print(f"  city {city_id}: cash={city_obj.cash} plots={len(owned)}")
    print(f"market listings={len(world.market.listings)}")
    pending_n = sum(
        1 for p in world.proposals.proposals.values() if p.status == "pending"
    )
    print(f"proposals pending={pending_n}")
    print(f"proposals total={len(world.proposals.proposals)}")
    traces = sorted((td / "llm_debug").rglob("*.txt")) if (td / "llm_debug").exists() else []
    print(f"llm_debug traces={len(traces)}")
    for p in traces[-5:]:
        print(f"  {p.relative_to(td)}")

    executed = 0
    for p in traces:
        body = p.read_text(encoding="utf-8")
        if "→" in body and "tool_calls" not in body.split("→")[0][-20:]:
            # tool result lines look like: get_status → {...}
            for ln in body.splitlines():
                if " → " in ln and not ln.strip().startswith("assistant"):
                    executed += 1
    summary = {
        "save_dir": str(td),
        "day": world.day,
        "llm_mode": sched.llm_mode,
        "last_thought": sched.last_thought,
        "trace_count": len(traces),
        "tool_result_lines": executed,
        "companies": {
            cid: {
                "cash": c.cash,
                "plots": len(world.owned_plots("company", cid)),
                "buildings": sum(
                    1
                    for t in world.owned_plots("company", cid)
                    if t.plot and t.plot.building
                ),
            }
            for cid, c in world.companies.items()
        },
        "proposals": len(world.proposals.proposals),
    }
    (td / "playtest_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nDONE", summary)
    if executed == 0:
        raise SystemExit("FAIL: LLM produced no executable tool results")
    print("PASS: LLM executed tools")


if __name__ == "__main__":
    main()
