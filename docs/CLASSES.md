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
| `Actor` / `Company` / `City` | Agents | 1 player + N AI cos + M cities (setup) |
| `Item` + catalog | Goods | `data/items.yaml` |
| `Inventory` | Stock by item id | agents + market |
| `BuildingDefinition` + `Building` | Types / instances | status idle\|working |
| `ProductionMethod` | Recipes | `data/production_methods.yaml` |
| `Plot` | Square land + edge roads + combine flags | plots never removed on combine |
| `Market` / `Listing` | Indexed orders | lowest-price buys |
| `MailboxStore` | Pairwise text mail | C(n,2) files at startup |
| `ProposalBook` / `DirectProposal` | Goods + plot buy/sell | accept / reject / cancel |
| `GovernmentContractBook` | City procurement | bid → award lowest → fulfill |
| `GamePersistence` | Text saves | world / market / agents / mail / proposals / gov |
| `World` | Day loop + actions | setup → equal city ownership |
| `GameContent` | YAML load + validate | |

## Seed content

- Items: **iron_ore, coal, energy, steel**
- Building: **foundry**
- Method: **make_steel** (1+1+1 → 1 steel)

## Later

| Class | When |
|-------|------|
| Population demand | City consumption |
| Specialized plot bonuses | |

See `data/README.md` for extending YAML content.
