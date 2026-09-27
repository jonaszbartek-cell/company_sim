# Class model (domain)

## Core loop

```text
Plot (land)
  └── Building instance (e.g. Foundry)   ← BuildingDefinition from data/buildings.yaml
        └── ProductionMethod (e.g. Make Steel)  ← data/production_methods.yaml
              uses Item ids (iron, coal, energy → steel)  ← data/items.yaml

Actor (Company | City)
  └── Inventory of Items
```

## Implemented

| Class | Role | Data file |
|-------|------|-----------|
| `Actor` / `Company` / `City` | Economic agents | — |
| `Item` + `ItemCatalog` | Goods | `data/items.yaml` |
| `Inventory` | Stock by item id | — |
| `BuildingDefinition` + `BuildingCatalog` | Buildable types | `data/buildings.yaml` |
| `Building` | Instance on a plot | — |
| `ProductionMethod` + catalog | Recipes | `data/production_methods.yaml` |
| `Plot` / `Parcel` | Land + merge bonuses | — |
| `GameContent` | Loads + validates all YAML | `data/*` |
| `Tile` / `GridMap` | Spatial grid | — |

## Seed content (now)

- Items: **iron, coal, energy, steel**
- Building: **foundry**
- Method: **make_steel** (1+1+1 → 1 steel)

## Suggested later (not built yet)

| Class | When |
|-------|------|
| `TradeOffer` / `Trade` | Direct trading |
| `Market` | Shared buy/sell board |
| Population / demand basket | City consumption |
| `Contract` | Standing supply deals |

See `data/README.md` for how to extend YAML content.
