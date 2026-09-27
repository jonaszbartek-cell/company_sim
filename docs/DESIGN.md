# company_sim — Design Document

**Status:** Draft v0.4 (map rules locked)  
**Date:** 2026-09-27  
**Repo:** [jonaszbartek-cell/company_sim](https://github.com/jonaszbartek-cell/company_sim)

---

## 1. Game concept (Owner-defined)

A **real-time company economic simulator** on a **2D grid map**:

- Grid layout is **determined at game start**.
- Cells are **city**, **road**, or **plot** (`standard` / `specialized`).
- Generator **guarantees every plot has road access** (adjacent to road or city).
- **Adjacent owned plots can be merged** into a larger parcel (mechanical bonuses).
- **Cities and companies** can build roads (onto empty/unowned plot cells).
- Companies build **buildings** on owned plots and choose **production methods** (content TBD).
- Trade: company↔company, company↔city, company↔market (market TBD).
- **Population** exists (formulas TBD).
- **1 player** + up to **~20 AI companies** + **~5 LLM cities**, one local LLM switching entities.
- Python + Web UI → later one exe that also launches the LLM.
- Target: **RTX 3050**; first visuals: simple 2D.
- Real-time with **pause**.
- Player starts with **cash + starter plot + inventory**.

Goods / production method catalog: **TBD later**.

---

## 2. Locked technical decisions

| Topic | Decision |
|-------|----------|
| Language / UI | Python backend + Web UI |
| Distribution | Single exe launches game + LLM child process |
| Time model | Real-time + pause |
| GPU target | RTX 3050 |
| AI | One LLM, many entities (companies + cities) |
| Map | Square grid, generated at start |
| Plot types | `standard`, `specialized` (+ roads/cities as tile kinds) |
| Road access | Invariant: every plot adjacent to road or city |
| Plot merge | Adjacent owned plots → parcel; bonus scales with size |
| Road builders | Cities **and** companies |
| Player start | Cash + free starter plot + inventory |
| Content (goods/recipes) | Later |

---

## 3. Map generation (current approach)

1. Place city cores.
2. Lay a road lattice (stride configurable, default every 3rd row/col).
3. Carve Manhattan corridors between cities.
4. Remaining cells → `standard` / `specialized` plots.
5. Repair pass: any plot lacking access gets a spur road; assert invariant.

Late expansion: cities/companies may convert **unowned** plots (or empty hinterland) into roads; new road-adjacent empty cells become plots.

### 3.1 Parcels

- Buying a plot registers a 1-cell parcel.
- `merge_plots` joins adjacent owned parcels.
- PLACEHOLDER bonus: `throughput *= 1 + 0.05 * (parcel_size - 1)`.

---

## 4. Real-time + LLM architecture

Unchanged from v0.3: fixed tick sim; LLM worker async; never block the tick loop; compact per-entity context; fail-soft timeouts.

---

## 5. MVP stages

| Stage | Goal | Status |
|-------|------|--------|
| S0 Design + shell | Runnable tick + canvas | done |
| S1 Map gen + road access + merge + starter | this revision | in progress |
| S2 Production methods (data-driven) | waiting on content | pending |
| S3 Trades | pending | |
| S4 LLM worker | pending | |
| S5 Packaging exe+llama | pending | |

---

## 6. What I need next

Not blocking for map/code:

1. First **goods + production methods + building types** list (when ready).
2. What **specialized** plots do differently (bonus to certain recipes? only certain buildings?).
3. Exact parcel bonuses (replace PLACEHOLDER +5%/cell).
4. Road build costs / permissions (can you pave over your own empty plot?).

I will keep PLACEHOLDER values until you specify.
