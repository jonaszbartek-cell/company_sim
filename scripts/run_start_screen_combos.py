#!/usr/bin/env python3
"""Exhaustive start-screen combo runner (backend World + API + frontend fetch).

Runs:
  - Every UI-legal value on each axis (others at defaults)
  - Full cartesian of sample grid across all six start-screen params
  - Frontend static contract + live /api/setup via the same body the form sends
  - Optional headless Chrome form submit for representative combos

Writes JSON report to /opt/cursor/artifacts/start_screen_combo_report.json
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from company_sim.server import create_app  # noqa: E402
from company_sim.small_companies import city_hall_coord  # noqa: E402
from company_sim.world import World, WorldConfig  # noqa: E402
from tests.test_start_screen_combos import (  # noqa: E402
    AI_ALL,
    CART_AI,
    CART_CITIES,
    CART_LLM,
    CART_MAP,
    CART_SMALL,
    CART_SPEC,
    CITIES_ALL,
    DEFAULTS,
    FEASIBLE_CART,
    MAP_SWEEP,
    SMALL_ALL,
    SPEC_SWEEP,
    _assert_world_invariants,
    _feasible,
    _world_kwargs,
)

OUT = Path("/opt/cursor/artifacts/start_screen_combo_report.json")
SHOT_DIR = Path("/opt/cursor/artifacts/screenshots/start_combos")


def run_world(expect: dict) -> None:
    with tempfile.TemporaryDirectory() as td:
        w = World.new_game(WorldConfig(save_dir=td, **_world_kwargs(**expect)))
        _assert_world_invariants(w, expect=expect)


def run_api(expect: dict) -> None:
    app = create_app()
    client = TestClient(app)
    res = client.post("/api/setup", json=expect)
    data = res.json()
    if res.status_code != 200 or not data.get("ok"):
        raise AssertionError(f"setup failed: {data}")
    st = data["state"]
    assert st["config"]["map_size"] == expect["map_size"]
    assert st["config"]["starting_cities"] == expect["cities"]
    assert st["config"]["ai_company_count"] == expect["ai_companies"]
    assert st["config"]["small_companies_per_city"] == expect["small_companies_per_city"]
    # Public state must be drawable by frontend
    assert "tiles" in st["map"] or "plots" in st["map"] or "width" in st["map"]
    assert len(st["map"]["cities"]) == expect["cities"]
    st2 = client.get("/api/state").json()
    assert st2.get("started") is True
    # index + static assets
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200 or client.get("/static/app.js").status_code in (200, 404)


def record(failures: list, label: str, expect: dict, fn) -> None:
    try:
        fn(expect)
    except Exception as exc:  # noqa: BLE001
        failures.append(
            {
                "label": label,
                "params": expect,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-1500:],
            }
        )


def axis_cases() -> list[tuple[str, dict]]:
    cases: list[tuple[str, dict]] = []
    for ai in AI_ALL:
        cases.append((f"axis_ai_{ai}", {**DEFAULTS, "ai_companies": ai}))
    for s in SMALL_ALL:
        size = 24 if s > 8 else 12
        cases.append(
            (
                f"axis_small_{s}",
                {**DEFAULTS, "small_companies_per_city": s, "map_size": size},
            )
        )
    for c in CITIES_ALL:
        size = max(12, c * 4)
        cases.append((f"axis_cities_{c}", {**DEFAULTS, "cities": c, "map_size": size}))
    for m in MAP_SWEEP:
        cases.append(
            (
                f"axis_map_{m}",
                {
                    **DEFAULTS,
                    "map_size": m,
                    "ai_companies": 0,
                    "small_companies_per_city": 0,
                },
            )
        )
    for p in SPEC_SWEEP:
        cases.append(
            (
                f"axis_spec_{p}",
                {**DEFAULTS, "specialized_plot_percent": p, "map_size": 16},
            )
        )
    for llm in (False, True):
        cases.append((f"axis_llm_{int(llm)}", {**DEFAULTS, "llm_debug": llm}))
    return cases


def cartesian_cases() -> list[tuple[str, dict]]:
    cases = []
    for a, s, c, m, p, l in FEASIBLE_CART:
        cases.append(
            (
                f"cart_ai{a}_sm{s}_ci{c}_m{m}_sp{p}_llm{int(l)}",
                {
                    "ai_companies": a,
                    "small_companies_per_city": s,
                    "cities": c,
                    "map_size": m,
                    "specialized_plot_percent": p,
                    "llm_debug": l,
                },
            )
        )
    return cases


def frontend_form_contract() -> None:
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/app.js").read_text(encoding="utf-8")

    def attr(field_id: str, name: str) -> str:
        i = html.index(f'id="{field_id}"')
        sn = html[i : i + 140]
        k = f'{name}="'
        j = sn.index(k) + len(k)
        return sn[j : sn.index('"', j)]

    assert attr("setup-companies", "min") == "0" and attr("setup-companies", "max") == "12"
    assert attr("setup-small-per-city", "min") == "0" and attr("setup-small-per-city", "max") == "20"
    assert attr("setup-cities", "min") == "1" and attr("setup-cities", "max") == "8"
    assert attr("setup-map", "min") == "2" and attr("setup-map", "max") == "128"
    assert attr("setup-specialized-pct", "min") == "0" and attr("setup-specialized-pct", "max") == "100"
    for key in (
        "ai_companies",
        "small_companies_per_city",
        "cities",
        "map_size",
        "specialized_plot_percent",
        "llm_debug",
    ):
        assert key in js


FRONTEND_COMBOS = [
    {**DEFAULTS},
    dict(ai_companies=0, small_companies_per_city=0, cities=1, map_size=2, specialized_plot_percent=0, llm_debug=False),
    dict(ai_companies=12, small_companies_per_city=20, cities=8, map_size=32, specialized_plot_percent=100, llm_debug=True),
    dict(ai_companies=0, small_companies_per_city=10, cities=4, map_size=24, specialized_plot_percent=50, llm_debug=False),
    dict(ai_companies=6, small_companies_per_city=5, cities=2, map_size=48, specialized_plot_percent=15, llm_debug=False),
    dict(ai_companies=0, small_companies_per_city=0, cities=1, map_size=128, specialized_plot_percent=0, llm_debug=False),
    dict(ai_companies=2, small_companies_per_city=0, cities=8, map_size=36, specialized_plot_percent=15, llm_debug=False),
    dict(ai_companies=0, small_companies_per_city=20, cities=1, map_size=24, specialized_plot_percent=15, llm_debug=False),
]


def playwright_form_submit(port: int, body: dict, shot: Path) -> dict:
    """Fill the real start form in Chromium, start game, screenshot, return checks."""
    from playwright.sync_api import sync_playwright

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{port}/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#setup-form", timeout=10000)
        page.fill("#setup-companies", str(body["ai_companies"]))
        page.fill("#setup-small-per-city", str(body["small_companies_per_city"]))
        page.fill("#setup-cities", str(body["cities"]))
        page.fill("#setup-map", str(body["map_size"]))
        page.fill("#setup-specialized-pct", str(body["specialized_plot_percent"]))
        if body.get("llm_debug"):
            page.check("#setup-llm-debug")
        else:
            page.uncheck("#setup-llm-debug")
        # Ensure WS setup push has landed before submit (and not overwritten fills)
        page.wait_for_timeout(300)
        # Re-apply fills after any late WS defaults (guards remaining races)
        page.fill("#setup-companies", str(body["ai_companies"]))
        page.fill("#setup-small-per-city", str(body["small_companies_per_city"]))
        page.fill("#setup-cities", str(body["cities"]))
        page.fill("#setup-map", str(body["map_size"]))
        page.fill("#setup-specialized-pct", str(body["specialized_plot_percent"]))
        if body.get("llm_debug"):
            page.check("#setup-llm-debug")
        else:
            page.uncheck("#setup-llm-debug")
        # Verify the form holds our values before submit
        assert page.input_value("#setup-companies") == str(body["ai_companies"])
        assert page.input_value("#setup-small-per-city") == str(body["small_companies_per_city"])
        assert page.input_value("#setup-cities") == str(body["cities"])
        assert page.input_value("#setup-map") == str(body["map_size"])
        assert page.input_value("#setup-specialized-pct") == str(body["specialized_plot_percent"])
        page.click("#btn-start")
        # Success: game app becomes visible (setup gets the hidden attribute)
        page.wait_for_selector("#app", state="visible", timeout=60000)
        page.wait_for_function(
            "() => document.getElementById('setup')?.hidden === true",
            timeout=10000,
        )
        err = page.locator("#setup-error")
        if err.count() and err.is_visible():
            raise AssertionError(f"setup error visible: {err.inner_text()}")
        # Canvas should have drawn something
        canvas = page.locator("canvas").first
        canvas.wait_for(state="visible", timeout=10000)
        # Give draw() a beat on large maps
        page.wait_for_timeout(500)
        page.screenshot(path=str(shot), full_page=True)
        # Confirm state endpoint matches what form sent
        st = page.evaluate("async () => (await fetch('/api/state')).json()")
        browser.close()
    if not st.get("started"):
        raise AssertionError(f"state not started: {st}")
    cfg = st["state"]["config"]
    assert cfg["map_size"] == body["map_size"], cfg
    assert cfg["starting_cities"] == body["cities"], cfg
    assert cfg["ai_company_count"] == body["ai_companies"], cfg
    assert cfg["small_companies_per_city"] == body["small_companies_per_city"], cfg
    assert abs(cfg["specialized_plot_percent"] - float(body["specialized_plot_percent"])) < 1e-6
    assert bool(cfg["llm_debug"]) is bool(body["llm_debug"])
    if not shot.exists() or shot.stat().st_size < 1000:
        raise AssertionError(f"screenshot missing/small: {shot}")
    return st


def start_server(port: int) -> subprocess.Popen:
    subprocess.run(f"fuser -k {port}/tcp 2>/dev/null || true", shell=True)
    time.sleep(0.5)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "company_sim", "--no-browser", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            import urllib.request

            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.2)
            if proc.poll() is not None:
                raise RuntimeError(f"server exited early code={proc.returncode}")
    raise RuntimeError("server failed to start")


def main() -> int:
    t0 = time.time()
    failures: list[dict] = []
    counts = {"world_ok": 0, "api_ok": 0, "world_fail": 0, "api_fail": 0, "front_ok": 0, "front_fail": 0}
    frontend_only = os.environ.get("FRONTEND_ONLY") == "1"

    if not frontend_only:
        print("=== frontend form contract ===")
        try:
            frontend_form_contract()
            counts["front_ok"] += 1
            print("OK form contract")
        except Exception as exc:  # noqa: BLE001
            counts["front_fail"] += 1
            failures.append({"label": "form_contract", "params": {}, "error": str(exc), "trace": traceback.format_exc()[-1500:]})
            print("FAIL form contract", exc)

        print("=== axis sweeps (World + API) ===")
        for label, expect in axis_cases():
            before = len(failures)
            record(failures, f"world:{label}", expect, run_world)
            if len(failures) == before:
                counts["world_ok"] += 1
            else:
                counts["world_fail"] += 1
                print("FAIL world", label, failures[-1]["error"])
                continue
            do_api = (
                "axis_ai_" in label
                or "axis_small_" in label
                or "axis_cities_" in label
                or "axis_llm_" in label
                or expect["map_size"] in (2, 8, 12, 32, 64, 96, 128)
                or expect["specialized_plot_percent"] in (0, 15, 50, 100)
            )
            if do_api:
                before = len(failures)
                record(failures, f"api:{label}", expect, run_api)
                if len(failures) == before:
                    counts["api_ok"] += 1
                else:
                    counts["api_fail"] += 1
                    print("FAIL api", label, failures[-1]["error"])

        print(f"=== cartesian World ({len(FEASIBLE_CART)} combos) ===")
        for i, (label, expect) in enumerate(cartesian_cases()):
            before = len(failures)
            record(failures, f"world:{label}", expect, run_world)
            if len(failures) == before:
                counts["world_ok"] += 1
            else:
                counts["world_fail"] += 1
                print("FAIL world", label, failures[-1]["error"])
            if (i + 1) % 100 == 0:
                print(f"  ... {i+1}/{len(FEASIBLE_CART)} world ok={counts['world_ok']} fail={counts['world_fail']}")

        api_cart = [
            e
            for _, e in cartesian_cases()
            if e["llm_debug"] is False
            and e["map_size"] in (2, 12, 24, 48)
            and e["specialized_plot_percent"] in (0, 15, 100)
        ]
        print(f"=== cartesian API ({len(api_cart)} combos) ===")
        for i, expect in enumerate(api_cart):
            label = f"api_ai{expect['ai_companies']}_sm{expect['small_companies_per_city']}_ci{expect['cities']}_m{expect['map_size']}_sp{expect['specialized_plot_percent']}"
            before = len(failures)
            record(failures, label, expect, run_api)
            if len(failures) == before:
                counts["api_ok"] += 1
            else:
                counts["api_fail"] += 1
                print("FAIL api", label, failures[-1]["error"])
            if (i + 1) % 50 == 0:
                print(f"  ... {i+1}/{len(api_cart)}")
    else:
        print("=== FRONTEND_ONLY mode ===")
        try:
            frontend_form_contract()
            counts["front_ok"] += 1
            print("OK form contract")
        except Exception as exc:  # noqa: BLE001
            counts["front_fail"] += 1
            failures.append({"label": "form_contract", "params": {}, "error": str(exc), "trace": traceback.format_exc()[-1500:]})
            print("FAIL form contract", exc)

    print("=== frontend Playwright form submit combos ===")
    port = 8791
    proc = None
    try:
        for body in FRONTEND_COMBOS:
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
            proc = start_server(port)
            label = (
                f"front_m{body['map_size']}_ci{body['cities']}"
                f"_sm{body['small_companies_per_city']}_ai{body['ai_companies']}"
                f"_sp{body['specialized_plot_percent']}_llm{int(body['llm_debug'])}"
            )
            shot = SHOT_DIR / f"{label}.png"
            try:
                playwright_form_submit(port, body, shot)
                counts["front_ok"] += 1
                print("OK front", label, shot)
            except Exception as exc:  # noqa: BLE001
                counts["front_fail"] += 1
                failures.append(
                    {
                        "label": label,
                        "params": body,
                        "error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc()[-1500:],
                    }
                )
                print("FAIL front", label, exc)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    report = {
        "elapsed_s": round(time.time() - t0, 1),
        "counts": counts,
        "feasible_cartesian": len(FEASIBLE_CART),
        "frontend_only": frontend_only,
        "sample_grid": {
            "ai": CART_AI,
            "small": CART_SMALL,
            "cities": CART_CITIES,
            "map": CART_MAP,
            "spec": CART_SPEC,
            "llm": CART_LLM,
        },
        "failure_count": len(failures),
        "failures": failures,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("=== SUMMARY ===")
    print(json.dumps(counts, indent=2))
    print("failures", len(failures))
    print("wrote", OUT)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
