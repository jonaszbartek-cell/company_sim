# company_sim — Design Document

**Status:** Draft v0.7  
**Date:** 2026-09-27  
**Repo:** [jonaszbartek-cell/company_sim](https://github.com/jonaszbartek-cell/company_sim)

---

## 1. Game concept

Company economic simulator on a **2D grid** of **roads and plots**. Goal: make the strongest company.

### Scoped cast (now)

| Role | Count |
|------|-------|
| Player company | 1 |
| AI companies | 2 |
| City agent | 1 |

A **city is not a special tile**. It is an LLM agent administering a territory of normal roads/plots/buildings.

---

## 2. Locked decisions

| Topic | Decision |
|-------|----------|
| Stack | Python + Web UI → later one exe + local LLM |
| Time | **Game days** — one day when **all companies** have acted. Slowable; not speed-up |
| Engine | LLM acts as one agent; when finished, next agent (sequential) |
| Persist | Text files: world, market, per-agent, **pairwise mailboxes** |
| Market | Indexed buy/sell listings; sell goods escrowed on market; buy takes lowest price |
| Map cells | Only `road` and `plot` (+ rare empty) |
| Plot types | `standard`, `specialized` (roads are tiles, not plots) |
| Goods | iron, coal, energy, steel + Foundry / make_steel |

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
| value | land valuation (seeded from price; future use) |
| type | `standard` \| `specialized` |
| location | **yes, but on the Tile** as `(x,y)` — keep it there, echo in agent text files |
| size | always **1** per cell; **parcel size** grows when merged |
| building | optional Building instance |
| price | buy price while unowned |

**Roads:** not plots. No size, no building. `TileKind.ROAD` only.

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

### Still later (not missing for v0.7)

- Direct negotiate / contracts between agents  
- Population demand basket  
- Specialized plot rules / parcel value formulas  

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

`saves/proposals.txt` holds pending direct proposals.

---

## 6. Map generation

1. Place city anchor(s).  
2. Voronoi territory.  
3. Road lattice.  
4. Remaining cells → plots.  
5. Assert road access.  
