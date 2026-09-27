# company_sim — Design Document

**Status:** Draft v0.1  
**Date:** 2026-09-27  
**Repo:** `jonaszbartek-cell/company_sim`  
**Source of truth today:** Google Drive shared sim (`01_WORLD_STATE`, `02_PROCEDURES`)  
**Drive mirror (summary):** https://docs.google.com/document/d/1Fed_YxfYqSoqpCEXZVdn8YJPHoMSefO5wuhrznvaq1E/edit

---

## 1. Problem

The geopolitical multi-agent simulation already runs, but it is operated by hand:

- World state lives in Google Docs (`01_WORLD_STATE` snapshots).
- Turn rules live in `02_PROCEDURES`.
- Country agents negotiate in chat; the Owner approves; a World Governor agent recalculates and rewrites docs.

That works for playtests, but it is slow, error-prone, hard to audit, and impossible to resume cleanly after mistakes. **company_sim** is the software product that turns this into a durable, rule-backed game engine with AI actors and a human Owner in the loop.

---

## 2. Product vision

An AI-driven turn-based geopolitical simulation where:

1. **Owner (human)** picks who acts, approves/rejects packages, and issues special events.
2. **World Governor (system + LLM adjudicator)** applies deterministic resource math and judges soft outcomes (ACTION / MILITARY).
3. **Country agents (LLMs)** negotiate, propose TRADE / ACTION / MILITARY, and react to flags.

MVP goal: run a full multi-country campaign with the same feel as the current Drive game, without manually editing world-state docs.

---

## 3. Current reference model (from live play)

### 3.1 Roles

| Role | Who | Responsibility |
|------|-----|----------------|
| Owner | Human | Chooses next country; approve/reject actions; issue events (e.g. ESC food-shortage cut) |
| World Governor | Engine + LLM | Turn-start calc; trade confirm; action/military resolution; flags; state updates |
| Country | LLM agent per polity | Diplomacy, trade offers, action proposals |

### 3.2 Countries (current campaign)

USA, EU, China, Russia, Iran, Israel (extendable).

Alliances / blocs observed in play: e.g. ESC (Iran / Russia / China) under shared events.

### 3.3 Per-country state schema

```text
Country
├── military
│   ├── technology: number
│   ├── stockpiles: { ground, navy, air_missile, defense }
│   └── production_per_turn: { ground, navy, air_missile, defense }
└── economy
    ├── cash, cash_income
    ├── resources: { oil, energy, food, steel, electronics }
    ├── income:     same keys /turn
    └── expenditure: same keys /turn
```

Military stockpiles are **single-use**: spent units are removed when used. There is no reusable hardware inventory.

### 3.4 Turn procedure (canonical)

From `02_PROCEDURES`:

1. Owner selects the acting country.
2. Turn-start: `resources_new = resources_old + income − expenditure`; military stockpiles `+= production`.
3. Persist updated country slice into world state.
4. Country communicates with others.
5. Country prepares package: **TRADE** (optional), **ACTION** (required intent), **MILITARY** (optional).
6. Country reports package to Owner.
7. Owner approves or rejects.
8. If approved, Governor executes and updates world state.
9. If any resource stockpile ≤ 0, Governor flags Owner.
10. Wait for Owner to pick the next country.

### 3.5 Sub-procedures

**Trade**

- Report: parties, resources both ways, cash amount, who pays.
- Governor confirms with counterparty country agent.
- On yes: transfer resources/cash; update both countries.

**Action**

- Free-text intent → Governor judges effectiveness (observed bands: WEAK / WEAK–MODERATE / MODERATE / HIGHLY EFFECTIVE).
- Returns narrative + concrete state deltas (often income/infra tweaks, small stockpile recovery).
- May affect actor and/or others.

**Military**

- Report: attacker, target, method, stockpiles spent.
- Governor weighs attack type, spent force, attacker tech, defender stockpiles/defense, situation.
- Spent attacker stockpiles always removed; defender damage / income hits / defense attrition as judged.

### 3.6 Events & flags

Owner may inject global modifiers (example: ESC food shortage → halve production and non-food income for ESC countries).

Flags always surface stockpile ≤ 0 and other thin resources (Air 0, Cash thin, etc.).

---

## 4. Goals & non-goals

### Goals (MVP)

- Structured world state (DB / JSON), versioned every settlement.
- Deterministic turn-start resource & production math.
- Owner console: pick turn, approve/reject, inject events.
- Country agent loop with tool access to public state + private notes.
- Governor pipeline: trade settlement, action resolution, military resolution.
- Full audit log of every calc and LLM judgment.
- Import path from existing Drive `01_WORLD_STATE` text into structured state.

### Non-goals (MVP)

- Real-time simultaneous turns.
- Pixel map / 3D combat.
- Open multiplayer matchmaking.
- Perfect economic equilibrium modeling.
- Fully autonomous Owner (human stays in the loop).

---

## 5. System architecture

```text
┌──────────────────────────────────────────────────────────┐
│                     Owner Console (Web)                   │
│  pick turn · approve packages · events · view flags/log  │
└───────────────┬───────────────────────────▲──────────────┘
                │                           │
                ▼                           │
┌───────────────────────┐     ┌─────────────┴──────────────┐
│     Turn Orchestrator │────▶│     World State Store      │
│  FSM: idle→start→dip  │     │  countries, flags, events  │
│  →propose→approve→    │     │  immutable turn snapshots  │
│  settle→flag→idle     │     └─────────────▲──────────────┘
└───────────┬───────────┘                   │
            │                               │
   ┌────────┴────────┐                      │
   ▼                 ▼                      │
┌────────────┐  ┌──────────────┐   ┌───────┴────────┐
│ Country    │  │ World        │   │ Rules Engine   │
│ Agents     │  │ Governor     │──▶│ (deterministic │
│ (1 / nation│  │ (LLM + tools)│   │  resource math)│
└────────────┘  └──────────────┘   └────────────────┘
```

### 5.1 Turn orchestrator (FSM)

States: `IDLE` → `TURN_START` → `DIPLOMACY` → `PROPOSAL` → `OWNER_REVIEW` → `SETTLE` → `FLAGS` → `IDLE`

Illegal transitions rejected; every transition appends an audit event.

### 5.2 Rules engine (deterministic)

Pure functions, no LLM:

- Turn-start resource equation
- Production accrual
- Trade transfer (after both sides confirmed)
- Stockpile ≤ 0 clamping + flag emission
- Event modifiers (e.g. production multipliers)

Unit-tested; golden fixtures from real Drive turns (EU settle 2026-09-26, China settle, ESC cut, etc.).

### 5.3 World Governor (LLM + tools)

LLM only where judgment is required:

- ACTION effectiveness & deltas
- MILITARY outcome
- Optional: summarizing flags for Owner

Constrained by tool schema: may only propose typed patches (`PatchOp[]`) that the rules engine validates before apply.

### 5.4 Country agents

Each country agent receives:

- Public world snapshot (all countries’ public stats)
- Own private scratchpad / doctrine
- Recent turn log
- Tools: `propose_trade`, `propose_action`, `propose_military`, `message_country`, `read_state`

Agents cannot mutate state directly.

---

## 6. Data model (proposed)

```ts
type ResourceKey = "oil" | "energy" | "food" | "steel" | "electronics";
type MilKey = "ground" | "navy" | "air_missile" | "defense";

interface CountryState {
  id: string;                 // "usa" | "eu" | ...
  name: string;
  military: {
    technology: number;
    stockpiles: Record<MilKey, number>;
    production: Record<MilKey, number>;
  };
  economy: {
    cash: number;
    cashIncome: number;
    resources: Record<ResourceKey, number>;
    income: Record<ResourceKey, number>;
    expenditure: Record<ResourceKey, number>;
  };
  notes?: string;
  modifiers?: Modifier[];     // active event effects
}

interface WorldState {
  version: number;
  turnIndex: number;
  actingCountryId: string | null;
  phase: TurnPhase;
  countries: Record<string, CountryState>;
  flags: Flag[];
  policies: Policy[];         // e.g. food export locks
  updatedAt: string;
}

interface TurnSnapshot {
  id: string;
  label: string;              // "EU turn settled 2026-09-26"
  before: WorldState;
  after: WorldState;
  package?: ActionPackage;
  ownerDecision?: "approved" | "rejected";
  governorReport?: string;
  createdAt: string;
}

interface ActionPackage {
  countryId: string;
  trade?: TradeDeal[];
  action?: { description: string };
  military?: {
    targetId: string;
    method: string;
    spent: Partial<Record<MilKey, number>>;
  };
}
```

Storage: Postgres (or SQLite for local MVP) + JSONB for state blobs; append-only `turn_snapshots` and `audit_events`.

---

## 7. API surface (MVP)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/world` | Current world state |
| GET | `/world/history` | Snapshot list |
| GET | `/world/history/:id` | One snapshot |
| POST | `/turns/start` | Owner picks country → run turn-start calc |
| POST | `/turns/package` | Country agent submits package |
| POST | `/turns/decide` | Owner approve/reject |
| POST | `/turns/settle` | Governor execute + persist |
| POST | `/events` | Owner injects global event |
| GET | `/flags` | Open flags |
| WS/SSE | `/stream` | Live phase + log updates |

Auth: single Owner account for MVP; agent calls use service tokens scoped to one country.

---

## 8. LLM design

### Country system prompt skeleton

- You are the government of {COUNTRY}.
- Optimize long-term survival and relative power under Owner oversight.
- Never invent numbers not present in state; propose trades with exact integers.
- Always include ACTION; TRADE recommended; MILITARY optional.
- Report in structured JSON matching `ActionPackage`.

### Governor system prompt skeleton

- You are World Governor. Prefer conservative ACTION effects (production/income boosts are weak).
- Military: force size + tech + defense → effectiveness band; always remove spent stockpiles.
- Emit only validated `PatchOp`s; narrate briefly for the turn log.

### Patch ops (examples)

```ts
type PatchOp =
  | { op: "add_resource"; countryId: string; key: ResourceKey | "cash"; delta: number }
  | { op: "set_income"; countryId: string; key: ResourceKey | "cash"; value: number }
  | { op: "add_stockpile"; countryId: string; key: MilKey; delta: number }
  | { op: "set_policy"; policy: Policy }
  | { op: "add_flag"; flag: Flag }
  | { op: "add_modifier"; countryId: string; modifier: Modifier };
```

Rules engine rejects patches that violate invariants (negative spends without stockpile, trade without confirmation, etc.).

---

## 9. UX (Owner console)

Minimal screens:

1. **World board** — country cards with cash, critical resources, mil tech, flags.
2. **Turn panel** — phase indicator, acting country, package JSON + natural-language summary, Approve / Reject.
3. **Diplomacy feed** — inter-country messages for the active turn.
4. **History** — snapshot timeline with diffs.
5. **Events** — form to apply modifiers (name, targets, multipliers, duration).

No card-heavy dashboard chrome; one composition per screen; board is the visual anchor.

---

## 10. Migration from Drive

1. Parser: ingest latest `01_WORLD_STATE` text → `WorldState` JSON.
2. Fixture pack: store historical settle docs as golden tests for parser + turn-start math.
3. Dual-run: for N turns, engine proposes updates; Owner compares to old Doc workflow.
4. Cut over: engine becomes source of truth; optional export back to Doc for archive.

Drive links:

- Procedures: `https://docs.google.com/document/d/10zPK4hDfRL59JOSNvDlEim1gZmDGGQgpYtZHUZ507pk`
- Latest settle example: `https://docs.google.com/document/d/1CbuPbrA653tFPqLmBW9IX8iOlbcnUltXJLPSZWqniNY`

---

## 11. Tech recommendations (MVP)

| Layer | Choice | Why |
|-------|--------|-----|
| App | TypeScript / Next.js | Fast Owner UI + API routes |
| State | Postgres + Drizzle | Snapshots + JSONB |
| Agents | Vercel AI SDK / OpenAI-compatible tools | Structured outputs |
| Jobs | In-process queue first | Simple; swap to Redis later |
| Deploy | Single Node host or Vercel + managed DB | Low ops |

Open questions on model providers and cost caps left for Owner decision.

---

## 12. Milestones

1. **M0 — Spec locked** (this doc + schema review)
2. **M1 — State & rules** — parser from Drive text; turn-start calc; golden tests from real turns
3. **M2 — Owner console** — view state, start turn, approve/reject, history diffs
4. **M3 — Governor settle** — trade + action + military patches with validation
5. **M4 — Country agents** — propose packages + diplomacy channel
6. **M5 — Campaign continuity** — events, modifiers, import/export, audit polish

---

## 13. Open decisions

1. **Scope naming:** keep geopolitical “countries” as the core loop, or also ship a company/department skin using the same engine?
2. **Simultaneous vs sequential diplomacy** during a turn.
3. **How hard should ACTION income buffs stay?** (current play: very weak)
4. **Military counter-use:** does defender auto-spend defense/air, or only when Owner/agent chooses?
5. **Persistence of policies** (export locks) — turn-limited or until Owner clears?
6. **Model routing:** one model for all countries vs stronger model for Governor only.

---

## 14. Next working session

- Confirm open decisions §13 (especially naming/skin).
- Implement `WorldState` TypeScript types + Drive text parser.
- Add golden fixture from EU settle 2026-09-26 and China settle 2026-09-26.
- Skeleton Next.js Owner board reading fixture JSON.

---

## Appendix A — Turn-start formula

```text
for each resource R in {oil, energy, food, steel, electronics}:
  stock[R] = stock[R] + income[R] - expenditure[R]
  if stock[R] <= 0: flag(country, R); stock[R] = 0   # continuity rule used in play

cash = cash + cashIncome   # (expenditure of cash is via trades/events, not a fixed burn)

for each mil key M:
  stockpile[M] += production[M]   # after event multipliers
```

## Appendix B — Observed effectiveness bands

From live resolves (illustrative, not yet hard-coded):

| Band | Typical delta |
|------|----------------|
| WEAK | income +1..+2; tiny stockpile recovery |
| WEAK–MODERATE | modest income infra hits on target |
| HIGHLY EFFECTIVE | large stockpile wipe / income crush / defense attrition when backed by very large force |

Exact tables TBD after Owner preference on balance.
