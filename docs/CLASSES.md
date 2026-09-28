# Class model (domain)

## Core loop

```text
Agent (Company | City)
  cash, inventory, acted_this_day
  └── owned Plots (via world)
        └── Building (idle|working, chosen production method)
              ├── storage Inventory (hard slots materialized on build; plot-owner owned; cap 10)
              └── ProductionMethod → Items

Market
  inventory + indexed buy/sell Listings
```

## Implemented

| Class | Role | Notes |
|-------|------|-------|
| `Actor` / `Company` / `City` | Agents | 1 player + N AI cos + M cities (setup) |
| `Item` + catalog | Goods | `data/items.yaml` |
| `Inventory` | Stock by item id | agents + market + building storage |
| `BuildingDefinition` + `Building` | Types / instances | status idle\|working; destroy refunds floor(10%) materials |
| `ProductionMethod` | Recipes | `data/production_methods.yaml`; produce uses building storage |
| `Plot` | Square land + edge roads + combine flags | plots never removed on combine |
| `Market` / `Listing` | Indexed orders | lowest-price buys; optional market_seed |
| `MailboxStore` | Pairwise text mail | C(n,2) files at startup |
| `ProposalBook` / `DirectProposal` | Goods + plot buy/sell | accept / reject / cancel |
| `GovernmentContractBook` | City procurement | bid → award lowest → fulfill |
| `GamePersistence` | Text saves | world / market / agents / mail / proposals / gov |
| `World` | Day loop + actions | setup → equal city ownership |
| `GameContent` | YAML load + indexes | goods_index; storage slots derived from methods |

## Seed content

- **46 items** across raw / processed / finished / utility (`data/items.yaml`)
- **13 buildings** (mine → satellite / power plant)
- **47 production methods** (qty 1 placeholders; `duration_sec=1` day-unit)
- Runtime **goods_index** + reverse indexes on `GameContent` (also `saves/goods_index.txt` for LLMs)
- Building storage: **cap 10** of every good used/made by that building's methods (auto-updates with YAML)
- Build cost placeholder: **100 cash + 10 construction_materials**; destroy returns floor(10%) of materials + storage contents
- Placeholder arts under `web/assets/` (`goods/`, `buildings/map/<id>/{w}x{h}.svg`, `buildings/ui/`, `terrain/`, `roads/mask_*`)
- Combine: empty groups freely; with buildings only same type / expand onto empty; footprint stays a filled rectangle ≤9×9

## Later

| Class | When |
|-------|------|
| Population demand | City consumption |
| Specialized plot bonuses | |

See `data/README.md` for extending YAML content.
