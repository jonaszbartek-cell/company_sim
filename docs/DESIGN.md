# company_sim — Design Document

**Status:** Draft v0.2 (correct game concept)  
**Date:** 2026-09-27  
**Repo:** [jonaszbartek-cell/company_sim](https://github.com/jonaszbartek-cell/company_sim)  
**Drive summary:** https://docs.google.com/document/d/1aBNTdoioWOKuH9K8Hlti4h6Qy_2pxBaL9Lo3oTWhCEE/edit  
**Note:** v0.1 incorrectly described a geopolitical country sim. This version replaces it.

---

## 1. What we are building

A **company economic simulator**:

- The player runs a company.
- The economy has **goods**, **production methods**, and **demand**.
- There is a **simplified city + population** layer that consumes goods and supplies labor.
- **Competitor companies are controlled by a local LLM** that talks to the game engine through tools.
- The LLM stack must run on a **budget PC** (local inference, no cloud required for AI rivals).

This doc defines the technical and systems design so we can implement incrementally without inventing gameplay you have not specified yet.

---

## 2. Design principles (from your master instructions)

1. Working and playable first.
2. Simple, maintainable code.
3. Easy to add/change mechanics and balance data.
4. No overengineering.
5. Do not invent gameplay beyond what you describe; mark open items explicitly.
6. After each meaningful step, keep the project runnable.

---

## 3. Player fantasy (high level)

You manage a company in a small city economy: buy/hire inputs, choose production, sell goods into market demand shaped by population, and compete with other firms whose managers are local AI agents.

Exact win/lose conditions, eras, and content lists are **not defined yet** and will come from later prompts.

---

## 4. Core systems (planned)

Systems below are the ones your brief implies. Detail and balance come later.

### 4.1 Company

A company owns:

- Cash
- Inventory of goods
- Facilities / production lines (or equivalent capacity)
- Employees (or labor contracts)
- Orders / contracts (if/when added)
- Identity used by AI or player (name, strategy notes)

Player controls one company. Other companies are AI-controlled.

### 4.2 Goods

Goods are data-defined commodities (raw, intermediate, finished, possibly services later).

Each good has at least:

- `id`, display name
- unit
- whether it spoils / storage rules (later, if needed)
- tags for demand and production

Balance values live in data files, not buried in logic.

### 4.3 Production methods

A production method is a recipe:

- inputs (goods + quantities per cycle)
- labor requirement
- outputs (goods + quantities)
- time / throughput
- required facility or tech (when those exist)

The engine resolves production in discrete sim steps so results are deterministic and debuggable.

### 4.4 Market demand & prices

Simplified market:

- Population (and maybe businesses) generate **demand** for consumer goods.
- Companies offer **supply** from inventory / production.
- Price emerges from a simple supply–demand rule (exact formula TBD with you).
- Companies buy inputs from the same market or from direct trades (TBD).

Assumption for MVP design: **one shared city market** with posted buy/sell interest, not a full order-book exchange.

### 4.5 City & population (simplified)

City is a light simulation, not a full city-builder:

- Population count (and later maybe segments: workers, dependents)
- Employment / unemployment
- Wage pressure (optional early)
- Consumption basket → demand for goods
- Happiness / migration only if you later ask for it

No district micro-management in MVP unless you request it. A single-city aggregate is enough to drive demand and labor.

### 4.6 Time / simulation loop

**Recommended default: turn-based (or tick-based) days.**

Why: local LLMs are slow on budget PCs. Discrete turns let rival AIs think between turns instead of every frame, keep the economy deterministic, and make debugging possible.

Alternative (only if you prefer): real-time with paused “AI decision windows.” Heavier and harder to keep fair on weak hardware.

### 4.7 Competitor AI (local LLM + tools)

Each rival company has an LLM agent with:

- A short system prompt (role, goals, constraints)
- A **small tool set** that talks only to the game engine
- A compact state summary (not the whole world dump)

Agents never mutate state directly. Tools request actions; the engine validates and applies them.

---

## 5. Local LLM on a budget PC

### 5.1 Constraints we design for

Assumption (adjust if your machine differs):

- 8–16 GB system RAM
- Integrated GPU or entry discrete GPU (or CPU-only)
- No requirement for cloud API keys for rival AI

### 5.2 Inference approach

| Piece | Recommendation | Why |
|-------|----------------|-----|
| Runtime | [Ollama](https://ollama.com) or llama.cpp server | Simple local OpenAI-compatible HTTP API |
| Model size | ~1.5B–7B params, Q4_K_M / Q5 quant | Fits budget RAM; tool use still workable |
| Suggested starter models | Qwen2.5-3B-Instruct, Llama-3.2-3B-Instruct, Phi-3.5/4-mini (whichever tools best on your machine) | Small, instruct-tuned, OK JSON/tool habits |
| Context | Tight summaries (few KB), not full history every call | Speed + quality on small models |
| Scheduling | At most one AI company deciding at a time; queue others | Avoid RAM/CPU spikes |

### 5.3 Tool design for small models

Keep tools few, typed, and forgiving:

Examples (names indicative, not final):

1. `get_company_status` — cash, inventory, employees, facilities
2. `get_market_overview` — prices, demand pressure, top goods
3. `set_production` — choose method + intensity for a line
4. `place_buy_order` / `place_sell_order` — market actions
5. `hire_workers` / `fire_workers` — labor adjustments
6. `get_rival_public_info` — public prices/production hints only

Rules:

- Engine rejects illegal actions with clear errors the model can read.
- Prefer enums and numbers over free text for actions.
- One decision bundle per turn (plan), not dozens of chatty calls.
- Hard timeout + fallback: if the model fails/times out, company holds previous plan or uses a tiny scripted heuristic so the game never softlocks.

### 5.4 Separation of concerns

```text
┌──────────────────┐     tools/HTTP      ┌─────────────────────┐
│  Game Engine     │◄───────────────────►│  LLM Runner         │
│  (sim + rules)   │                     │  (Ollama client)    │
└────────┬─────────┘                     └──────────▲──────────┘
         │                                          │
         ▼                                          │
┌──────────────────┐                     ┌──────────┴──────────┐
│  Save / Data     │                     │  Local model files  │
│  goods, recipes  │                     │  via Ollama/llama   │
└──────────────────┘                     └─────────────────────┘
```

Game logic does not embed model weights. LLM is an optional AI driver behind the same action API the UI uses.

---

## 6. Technical foundation (proposal)

Repo is currently empty aside from docs. We need a stack before code.

### 6.1 Recommended stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | **TypeScript (Node)** or **Python 3.11+** | Fast to iterate; excellent for tool APIs and data files |
| UI (MVP) | Simple **local web UI** (Vite + browser) or lightweight desktop shell later | Company sims are panel/table heavy; 3D engine not required for MVP |
| Sim core | Pure deterministic module (no UI framework inside) | Easy tests; AI and UI both call the same API |
| AI bridge | HTTP to Ollama (`/api/chat` with tools) | Standard, local, replaceable |
| Data | JSON/YAML for goods, recipes, city presets | Balance without recompiling |
| VCS | This GitHub repo | Already created — do not create another |

**Assumption:** start with **TypeScript + Vite web UI + Node sim server** OR **Python + simple web UI**. Both are fine; see open decision A.

**Not recommended for MVP:** Unity/Unreal (heavy), multiplayer netcode, cloud-only LLM dependency.

### 6.2 Project layout (target)

```text
company_sim/
  docs/DESIGN.md
  data/                 # goods, production methods, city presets
  src/
    sim/                # economy, market, city, company, turn loop
    ai/                 # LLM client, prompts, tool adapters
    ui/                 # player panels
    app/                # wire-up, save/load
  tests/
  README.md
```

Exact folder names can shift slightly with the chosen language.

### 6.3 Action API (shared by player UI and LLM)

All gameplay commands go through one validated action layer, e.g.:

- `StartNewGame(config)`
- `AdvanceTurn()`
- `CompanySetProduction(companyId, ...)`
- `CompanyBuy(companyId, goodId, qty, maxPrice)`
- `CompanySell(...)`
- `CompanyHire(...)`

Player UI and LLM tools are two front-ends to the same actions. That keeps AI honest and rules centralized.

---

## 7. MVP scope (first playable)

**MVP = one city, few goods, a handful of recipes, player company + 1–2 LLM rivals, turn advance, readable UI.**

Included:

1. New game → load data definitions
2. Turn loop: production → market resolve → city consume/update → AI rivals decide → player acts (order TBD with you)
3. Player can inspect market, inventory, cash, set production, buy/sell
4. At least one local LLM rival using tools
5. Save/load game state
6. Fail-soft AI (timeout → hold)

Excluded from MVP unless you ask:

- Complex logistics / multi-city
- Full 2D city map building
- Deep politics / marketing / R&D trees
- Multiplayer
- Polished art

---

## 8. Data-driven content example (illustrative only)

Illustrative shape — **not final game content**:

```yaml
goods:
  - id: wheat
  - id: flour
  - id: bread
  - id: labor   # or model labor separately

production_methods:
  - id: mill_flour
    inputs: { wheat: 10, labor: 2 }
    outputs: { flour: 8 }
    duration_turns: 1
  - id: bake_bread
    inputs: { flour: 5, labor: 3 }
    outputs: { bread: 6 }
    duration_turns: 1

city_preset:
  population: 5000
  base_demand:
    bread: 0.4   # per capita factors, exact model TBD
```

Final goods/recipes wait for your content instructions.

---

## 9. Implementation stages

| Stage | Deliverable | Playable? |
|-------|-------------|-----------|
| S0 | Design doc approved + stack chosen | n/a |
| S1 | Sim core: goods, inventory, recipes, turn advance (no AI) | yes (debug/CLI or bare UI) |
| S2 | Market + city demand/labor loop | yes |
| S3 | Player UI for inspect + actions | yes |
| S4 | Action API + LLM tool bridge + 1 rival | yes |
| S5 | Save/load, AI queue polish, more data | yes |
| S6+ | Content, balance, map/visuals per your prompts | yes |

---

## 10. Testing approach

- Unit tests for market clearing, production consumption, turn order.
- Fixture games with scripted (non-LLM) rival policies.
- Manual playtest checklist per stage.
- AI integration test: mock LLM responses → ensure tools apply correctly; optional live Ollama test when installed.

---

## 11. Risks

| Risk | Mitigation |
|------|------------|
| Small models ignore tools / invent illegal moves | Strict schema, retries, engine validation, heuristic fallback |
| AI turns too slow | One rival per turn slice; smaller model; cached market summary |
| Economy softlocks (no food, no labor) | Early warnings; MVP tunables in data; Owner/debug commands |
| Scope creep into city-builder | Keep city aggregate until you explicitly expand |

---

## 12. Open decisions (need your input)

These materially affect architecture. Please answer when you can:

**A. Stack preference**

1. TypeScript (Vite UI + Node sim), or  
2. Python (sim + simple web UI), or  
3. Godot 4 (if you want a game-engine editor / 2D map early)

Recommendation: **1 or 2** for fastest LLM-tool iteration on a budget PC.

**B. Time model**

1. Turn-based days (recommended), or  
2. Real-time with pause

**C. Hardware target**

Approx RAM / GPU so we can pick a default model size (e.g. 8 GB RAM CPU-only vs 6 GB VRAM).

**D. MVP map**

1. Numbers/panels only (fastest), or  
2. Simple 2D city schematic from day one

**E. Player vs AI count (MVP)**

Confirm: 1 human company + N LLM companies (suggest N=1 or 2 for MVP).

---

## 13. Explicit non-decisions (waiting for you)

Per your instructions, **not invented yet**:

- Full goods list and production tree
- Exact price formula
- Win/lose / scenarios
- Visual style
- Facility types, tech tree, marketing, debt, stocks, etc.
- Whether labor is a market good or a separate employment pool

We will implement those when you specify them.

---

## 14. Immediate next step after you answer §12

1. Lock stack + time model.
2. Scaffold runnable empty game loop (advance turn, print/show state).
3. Add minimal data (placeholder goods only as temporary stubs, clearly marked).
4. Stop and wait for your first content/mechanics prompt before expanding economy design.

---

## Appendix — Repo status

- GitHub repo already exists: `company_sim` (do not create another).
- Current tree: `README.md`, `docs/DESIGN.md` only.
- No engine or game code yet.
