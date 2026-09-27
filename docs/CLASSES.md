# Class model (domain)

## Implemented

| Class | Role |
|-------|------|
| `Actor` | Shared base: cash + inventory |
| `Company` / `City` | Actor subtypes |
| `Item` | Good definition (input/output) |
| `ItemCatalog` | Registry loaded from `data/items.yaml` |
| `Inventory` | Quantities by item id on an Actor |
| `ProductionMethod` | Recipe: inputs → outputs over time |
| `ProductionCatalog` | Registry from `data/production_methods.yaml` |
| `Plot` | Buyable land cell; optional building; parcel link |
| `Building` | Structure on a plot running a production method |
| `Parcel` | Merged adjacent owned plots + bonus |
| `Tile` / `GridMap` | Spatial container (road/plot cells) |

## Suggested next (when needed — don’t build early)

| Class | Why | When |
|-------|-----|------|
| **`BuildingDefinition`** | Data for build cost, size, allowed methods (not just enum) | When you add more building types |
| **`TradeOffer` / `Trade`** | Company↔company / city / market deals | When implementing trade |
| **`Market` / `MarketListing`** | Shared buy/sell board | After direct trades exist |
| **`Population` / demand basket** | City people consuming items | When demand is specified |
| **`RoadSegment`** | Only if roads gain per-segment stats (tolls, capacity) | Probably never — keep as tile kind |
| **`Contract`** | Standing supply agreements | Later content |
| **`Tech` / `Modifier`** | Buffs on actors/parcels/buildings | After core economy works |

**Recommendation:** next content step is expanding `items.yaml` + `production_methods.yaml` (and maybe `buildings.yaml` → `BuildingDefinition`). Spatial + actor systems are enough for now.
