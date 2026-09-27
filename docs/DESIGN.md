# company_sim — Design Document

**Status:** Draft v0.3 (decisions locked from Owner)  
**Date:** 2026-09-27  
**Repo:** [jonaszbartek-cell/company_sim](https://github.com/jonaszbartek-cell/company_sim)  
**Drive summary:** https://docs.google.com/document/d/1aBNTdoioWOKuH9K8Hlti4h6Qy_2pxBaL9Lo3oTWhCEE/edit

---

## 1. Game concept (Owner-defined)

A **real-time company economic simulator** on a **2D map**:

- **Cities** grow and expand by building **roads**.
- New roads create adjacent **land plots** (multiple plot types) that can be **bought**.
- Companies build **buildings** (multiple types) on owned plots.
- Inside buildings, companies choose **production methods** (inputs → outputs).
- **Trade** between: companies↔companies, companies↔cities, companies↔market (market rules TBD later).
- **Population** exists (drives demand / labor — formulas TBD).
- **1 player company**, up to **~20 AI companies**, plus **~5 cities**, all AI-driven entities managed by **one local LLM** that switches between them for performance.
- Stack: **Python + Web UI**, shipped as **one executable** that also launches the local LLM stack.
- Target hardware: **RTX 3050**-class modern budget GPU setup.
- First visuals: **very simple 2D graphics**.

---

## 2. Locked technical decisions

| Topic | Decision |
|-------|----------|
| Language / UI | Python backend + Web UI |
| Distribution | Single exe launches game UI + embedded/bundled LLM runtime |
| Time model | **Real-time** (internal fixed ticks; UI never waits on LLM) |
| GPU target | RTX 3050 (typically 4–6 GB VRAM) — leave VRAM for the model |
| AI count | 1 human company + up to ~20 LLM companies + ~5 LLM cities |
| AI scheduling | **One LLM**, round-robin / priority queue across entities |
| Map | Cities, roads, plots, buildings — simple 2D |

---

## 3. World structure

```text
Map
 ├── Cities (agents: LLM)
 │    ├── population
 │    ├── treasury / inventory (TBD)
 │    ├── expansion desire → build roads
 │    └── trade with companies
 ├── Road network
 │    └── when a road segment is built → spawn adjacent Plots
 ├── Plots (typed; buyable when available)
 │    └── owned by company or vacant
 └── Buildings (typed; on owned plots)
      └── production method slots → transform inputs to outputs

Companies (1 player + many AI)
 ├── cash, inventory, owned plots/buildings
 ├── production plans
 └── trade actions
```

### 3.1 Growth loop (spatial)

1. City population / economy grows (rules TBD).
2. City (LLM or rules + LLM intent) decides to **expand**.
3. Expansion builds **road** segment(s) outward.
4. Engine creates **plots** adjacent to new road tiles (typed by terrain/zoning rules TBD).
5. Companies **buy** plots.
6. Companies **build** buildings on plots.
7. Companies assign **production methods** and run production over real time.
8. Goods move via **trades** and (later) market.

### 3.2 Entity responsibilities

| Entity | Controlled by | Typical decisions |
|--------|---------------|-------------------|
| Player company | Human (UI) | buy plot, build, set recipe, trade |
| AI company | LLM (queued) | same action space as player |
| City | LLM (queued) | expand/roads, city trades, maybe zoning later |

---

## 4. Real-time simulation architecture

Real-time **game clock** + **fixed sim tick** (e.g. 10–20 ticks/sec logic, or 1 tick = N ms of game time).

**Critical rule:** the LLM never blocks the sim thread.

```text
┌─────────────────────────────────────────────┐
│                 Main process                 │
│  ┌─────────────┐   ┌─────────────────────┐  │
│  │ Sim loop    │   │ Web UI (static+WS)  │  │
│  │ (realtime)  │◄─►│ map + panels        │  │
│  └──────┬──────┘   └─────────────────────┘  │
│         │ actions                            │
│  ┌──────▼──────┐   ┌─────────────────────┐  │
│  │ Action API  │◄──│ AI Scheduler        │  │
│  │ (validate)  │   │ queue entities      │  │
│  └─────────────┘   └──────────┬──────────┘  │
│                               │ async        │
│                    ┌──────────▼──────────┐  │
│                    │ LLM Worker          │  │
│                    │ (llama.cpp / Ollama │  │
│                    │  subprocess)        │  │
│                    └─────────────────────┘  │
└─────────────────────────────────────────────┘
```

### 4.1 Tick responsibilities (deterministic core)

Each tick (order draft — adjustable):

1. Advance production progress on buildings.
2. Complete finished batches → inventory.
3. Resolve pending trades / deliveries that are due.
4. Update population / city needs (lightweight).
5. Apply movement/pathing if any (later).
6. Push state deltas to UI (WebSocket).
7. AI scheduler may *start* a decision job if worker idle (non-blocking).

### 4.2 AI scheduler (one model, many minds)

- Maintain a queue of entity IDs needing a decision (stale plan, timer elapsed, event-triggered).
- When LLM worker is free, dequeue one entity, build a **compact context**, call model with tools.
- Apply returned tool calls through the **same Action API** as the player.
- Cooldowns per entity so 20 companies + 5 cities don’t thrash (e.g. company rethink every N seconds of game time; cities less often).
- On timeout/parse failure: keep last plan / no-op; log error; never freeze the game.

**RTX 3050 guidance:** prefer a **3B–7B Instruct Q4** model. Game rendering stays simple 2D (Canvas) so most VRAM stays available for inference. If VRAM is tight (4 GB cards), default to ~3B and CPU offload layers as fallback.

---

## 5. Packaging: “one exe”

Goal: user double-clicks one app; game + UI + LLM come up.

Practical layout (still feels like one app):

```text
CompanySim.exe          # Python entry (PyInstaller/Nuitka) + pywebview or local browser
_internal/ or sibling/
  web/                  # UI assets
  data/                 # goods, buildings, plot types
  llm/
    llama-server.exe    # or ollama-less: llama.cpp server
    models/             # optional: download on first run
```

**Assumption:** shipping multi-GB weights *inside* the installer is optional. Default plan:

1. First launch detects GPU/RAM.
2. Downloads a recommended GGUF once (cached next to the app), **or** uses a bundled small model if we later choose to ship it.
3. Spawns `llama-server` as a child process; kills it on exit.

True single-file with a 4 GB model is painful for distribution; UX can still be “one exe to start everything.”

UI hosting options:

- **Recommended:** `pywebview` window pointed at local FastAPI/uvicorn (or stdlib http.server + websockets) so it looks like a desktop game.
- Fallback: open system browser to `http://127.0.0.1:<port>`.

---

## 6. Web UI / simple 2D

MVP visuals:

- 2D canvas (or SVG) top-down grid map: city cores, roads, plots, buildings as colored rectangles/sprites.
- Side panels: cash, inventory, selected plot/building, production controls, trade list.
- Click plot → buy / build menus.
- Pause button (real-time with pause is almost mandatory for readability).

No fancy art pipeline yet — placeholder colors and labels.

---

## 7. Data-driven definitions (to fill later)

Files under `data/` (YAML/JSON):

- `plot_types` — cost modifiers, allowed buildings
- `building_types` — build cost, size, allowed production methods
- `production_methods` — inputs, outputs, time, labor
- `goods` — ids, names, stack rules
- `city_presets` / map seeds

Engine code should not hard-code specific good names beyond tests/fixtures.

---

## 8. Action API (shared)

Examples (names indicative):

**Company:** `buy_plot`, `build_building`, `set_production_method`, `propose_trade`, `accept_trade`, `cancel_job`

**City:** `build_road`, `offer_city_trade`, `set_expansion_focus` (later)

All actions validated against world rules (ownership, cash, adjacency, etc.).

---

## 9. MVP stages (revised)

| Stage | Goal |
|-------|------|
| **S0** | Design locked + runnable empty shell (this doc + scaffold) |
| **S1** | Grid map + cities + roads + plot spawn on road build |
| **S2** | Buy plot, build building, one production method ticking in real time |
| **S3** | Player UI wired to actions + pause |
| **S4** | Simple company↔company and company↔city trade |
| **S5** | LLM worker + scheduler (1 model) driving AI companies then cities |
| **S6** | Packaging spike (exe + child llama-server) |
| **S7+** | Market rules, richer population, more content — per Owner prompts |

---

## 10. Thoughts / design notes

1. **Real-time + LLM works if decisions are asynchronous.** The sim must stay smooth while the model thinks for 1–5+ seconds on a 3050.
2. **One LLM switching entities is the right call** for 25 minds. Context must stay tiny: “you are Company X” + local facts only.
3. **Cities as LLM agents** are powerful but expensive. Give cities lower decision frequency than companies; hard-rule obvious growth when possible and let LLM choose *where/when* to expand.
4. **Roads → plots** is a clean spatial economy loop. Keep plot creation deterministic in the engine (not invented by the LLM) so the map stays consistent.
5. **Market TBD** is fine — implement direct trades first; add market as a later facade over the same goods.
6. **Pause** should exist even in real-time mode for UX and debugging.

---

## 11. What I need next (blocking / high value)

Please answer when convenient — these change early map & economic code:

1. **Grid vs free placement?** Recommendation: **square grid tiles** (city/road/plot cells) for simple 2D and path logic.
2. **Who may build roads?** Only cities, or can companies also build roads (private rails/spurs)?
3. **Player start:** cash only in a seeded city, or already own a starter plot/building?
4. **Map size / city count at new game:** always 5 cities on one map, or unlock cities over time?
5. **Pause:** confirm real-time **with pause** (strongly recommended).

Non-blocking (can assume temporarily): exact goods list, building list, price formulas, market — wait for your content prompts.

---

## 12. Current repo plan

- Keep developing on branch + PR.
- Scaffold Python package: sim tick loop, minimal grid, FastAPI/WebSocket + simple canvas UI, placeholder AI scheduler stub (no model required to run).
- No invented final content — placeholders clearly marked `PLACEHOLDER`.
