# Game content data (`data/`)

Edit these YAML files to add content. **Restart the game** after changes
(content is loaded at process start and cross-validated).

| File | Class | Purpose |
|------|-------|---------|
| `items.yaml` | `Item` | Goods used as inputs/outputs / build costs |
| `buildings.yaml` | `BuildingDefinition` | Constructible buildings on plots |
| `production_methods.yaml` | `ProductionMethod` | Recipes that run inside a building |

At runtime `GameContent` builds indexes (also written to `saves/goods_index.txt` for LLMs):

- `methods_by_building` — recipes available in each building
- `produced_by` / `used_in` — which methods make / consume each good
- `goods_index` — full per-good card (made-in buildings, producers, consumers, build-cost usage)

## Placeholders (TBD later)

- All recipe I/O quantities = **1**
- Recipe `duration_sec` = **1** basic time unit (= **1 day**; a day advances when all companies have acted)
- Every building costs **100 cash** + **10 construction_materials**
- Starter inventories are temporary (include construction_materials so first buildings can be placed)

## Plot rules

- **Mine / Rig** → `specialized` plots only
- **All other buildings** → `standard` + `specialized`

## How to add more

### New item
Append under `items:` in `items.yaml` with a unique `id`.

### New building
Append under `buildings:` — set `build_cost`, `build_cost_items`, `allowed_plot_types`.

### New production method
Append under `production_methods:` — item ids and `building_id` must already exist.

Broken references (unknown item/building ids) cause startup validation errors on purpose.
