# company_sim — Design Document

**Status:** Draft v0.8  
**Date:** 2026-09-28  
**Repo:** [jonaszbartek-cell/company_sim](https://github.com/jonaszbartek-cell/company_sim)

---

## 1. Game concept

Company economic simulator on a **2D grid of square plots only**. Roads live on **plot edges**. Goal: make the strongest company.

### Startup (setup screen)

Choose **AI companies**, **agent cities**, and **map size** (plots per side). On start:

- Map is divided equally (nearest-center) among cities
- **Cities own every plot** in their territory
- **Companies start with no plots**
- Save files / mailboxes / config are created

### Scoped cast

| Role | Count |
|------|-------|
| Player company | 1 |
| AI companies | N (setup) |
| City agents | M (setup) |

A **city is not a special tile**. It is an LLM agent administering territory of plots.

---

## 2. Locked decisions

| Topic | Decision |
|-------|----------|
| Stack | Python + Web UI → later one exe + local LLM |
| Time | **Game days** — one day when **all companies** have acted. Slowable; not speed-up |
| Engine | LLM acts as one agent; when finished, next agent (sequential) |
| Persist | Text files: world, market, per-agent, **pairwise mailboxes** |
| Market | Indexed buy/sell listings; sell goods escrowed on market; buy takes lowest price |
| Map cells | Square **plots only** (no road tiles) |
| Roads | Built on a **side** (N/E/S/W) of an owned plot only — neighbor unchanged; costs **1 steel** (placeholder, goods consumed) |
| Plot combine | Flag only — plots stay; adjacent + no road between; no road on combined side |
| Plot types | `standard`, `specialized` |
| Goods | iron_ore, coal, energy, steel + Foundry / make_steel |
| Plot trade | Direct `plot_buy` / `plot_sell` proposals (accept/reject) |

---

## 3. Class fields (your list + gaps)

### Agent (`Actor` → Company | City)

| Field | Notes |
|-------|-------|
| id | yes |
| cash | yes |
| inventory | yes |
| plots | owned via world lookup (not duplicated on agent) |
| **name** | needed for UI / LLM |
| **kind** | company \| city |
| **acted_this_day** | day scheduling |
| Company: **is_player** | |
| City: center, population, territory | |

### Plot

| Field | Notes |
|-------|-------|
| id | yes |
| owner | `owner_kind` + `owner_id` |
| value | land valuation |
| type | `standard` \| `specialized` |
| location | on the Tile as `(x,y)` |
| size | always **1** per cell; **group size** via combine flags |
| roads | per-side bools N/E/S/W |
| combined | per-side neighbor plot id (or none) — plots never disappear |
| building | optional Building instance |
| reserved_proposal_id | lock while a plot proposal is pending |

**Roads:** edges on plots, not separate tiles. Own the plot → choose side (N/E/S/W) → that plot's edge becomes a road (adjacent plot is unchanged). Cannot place a road on a combined side.

**Combine:** adjacent owned plots with no road between get pairwise flags. Building a road on that shared edge is forbidden.

### Building

| Field | Notes |
|-------|-------|
| id | instance id |
| building_id | type from YAML (e.g. foundry) |
| possible production methods | from catalog by `building_id` |
| chosen method | `production_method_id` |
| status | `idle` \| `working` |
| owner | kind + id (redundant with plot owner, kept for clarity) |

### Market

| Field | Notes |
|-------|-------|
| inventory | goods from open sell listings |
| listings | indexed `#id`, side buy\|sell, item, qty, price, owner |
| escrow_cash | reserved for open buy orders |

Sell → goods leave seller → sit on market until bought → cash to seller on fill.  
Buy now → fill from **lowest-price** sell listings.  
Buy order → cash escrowed; auto-match sells at `sell.price <= buy.price`.

### Still later (not missing for v0.8)

- Population demand basket  
- Specialized plot rules / group value formulas  

---

## 4. Main loop (per agent turn)

1. Buy plot  
2. Build building  
3. Buy inputs (market)  
4. Produce  
5. Sell (market)  
(+ roads, merge, pass)

Day advances when **player + both AI companies** have each made ≥1 action.

---

## 5. Engine + persistence

```text
for agent in [ai_1, ai_2, city_a]  # sequential
  save world + market + agents/* + mailboxes/*
  LLM loads world + market + agents/<this>.txt + this agent's mailboxes
  LLM tools → Action API (incl. send_message)
  mark acted → save_all → maybe advance day
  next agent
```

Every state-changing action calls `persistence.save_all` so files stay current.

### File contracts

| File | Contains | Must not contain |
|------|----------|------------------|
| `saves/world.txt` | day, map, roster ids, turn queue, plot ownership, mailbox pair count | agent cash/inventory, market listings, mail bodies |
| `saves/market.txt` | market inventory, escrow, indexed listings | agent private state, plots |
| `saves/agents/<id>.txt` | that agent's cash/inventory/plots + open listings + mail contact list | other agents' private state |
| `saves/mailboxes/<a>__<b>.txt` | shared thread for that unordered pair only | unrelated pairs |

### Trading

| Action | Goods | Cash |
|--------|-------|------|
| Market sell | Leave seller → market inventory + indexed listing | Moves only when filled |
| Retract sell | That listing’s remaining goods → owner only | — |
| Market buy order | On fill from sells at ≤ buy price | Escrowed on post; refund if fill cheaper |
| Standard buy | From lowest sell listings now | Paid immediately |
| Direct sell proposal | Reserved from proposer | On accept: buyer → seller |
| Direct buy proposal | On accept: seller → buyer | Reserved from proposer; paid on accept |

**Cities cannot use the market.** They procure via government contracts:

1. City `post_government_contract` with required resources/qty (visible to all companies)  
2. Companies `bid_government_contract` with a total price  
3. City `award_government_contract` → **lowest bid wins**; city cash escrowed  
4. Winner gathers goods → `fulfill_government_contract` → goods to city, escrow → company  

`saves/government_contracts.txt` + `saves/proposals.txt` hold these boards.

`min_seconds_between_turns` slows the wall clock between AI turns; it never compresses a day.

---

## 6. Map generation

1. Place city anchor(s).  
2. Voronoi territory.  
3. Road lattice.  
4. Remaining cells → plots.  
5. Assert road access.  
