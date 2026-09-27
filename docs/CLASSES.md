# Class model (domain)

## Core loop

```text
Agent (Company | City)
  cash, inventory, acted_this_day
  └── owned Plots (via world)
        └── Building (idle|working, chosen production method)
              └── ProductionMethod → Items

Market
  inventory + indexed buy/sell Listings
```

## Implemented

| Class | Role | Notes |
|-------|------|-------|
| `Actor` / `Company` / `City` | Agents | 1 player + 2 AI cos + 1 city |
| `Item` + catalog | Goods | `data/items.yaml` |
| `Inventory` | Stock by item id | agents + market |
| `BuildingDefinition` + `Building` | Types / instances | status idle\|working |
| `ProductionMethod` | Recipes | `data/production_methods.yaml` |
| `Plot` / `Parcel` | Land + merge size | location on Tile `(x,y)` |
| `Market` / `Listing` | Indexed orders | lowest-price buys |
| `MailboxStore` | Pairwise text mail | C(n,2) files at startup |
| `ProposalBook` / `DirectProposal` | Direct trades | goods/cash reserved |
| `GamePersistence` | Text saves | world / market / agents / mail / proposals |
| `World` | Day loop + actions | |
| `GameContent` | YAML load + validate | |

## Seed content

- Items: **iron, coal, energy, steel**
- Building: **foundry**
- Method: **make_steel** (1+1+1 → 1 steel)

## Later

| Class | When |
|-------|------|
| `Contract` / negotiate | Direct deals between agents |
| Population demand | City consumption |
| Specialized plot bonuses | |

See `data/README.md` for extending YAML content.
