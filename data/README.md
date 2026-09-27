# Game content data (`data/`)

Edit these YAML files to add content. **Restart the game** after changes
(content is loaded at process start and cross-validated).

| File | Class | Purpose |
|------|-------|---------|
| `items.yaml` | `Item` | Goods used as inputs/outputs |
| `buildings.yaml` | `BuildingDefinition` | Constructible buildings on plots |
| `production_methods.yaml` | `ProductionMethod` | Recipes that run inside a building |

## Current seed content

- **Items:** iron, coal, energy, steel
- **Building:** foundry (cost 200)
- **Method:** `make_steel` — 1 iron + 1 coal + 1 energy → 1 steel (in foundry, 5s)

## How to add more

### New item
Append under `items:` in `items.yaml`:

```yaml
  - id: copper
    name: Copper
    category: raw
    description: Optional text
```

### New building
Append under `buildings:` in `buildings.yaml`:

```yaml
  - id: mill
    name: Mill
    build_cost: 150
    allowed_plot_types: [standard, specialized]
```

### New production method
Append under `production_methods:` — item ids and `building_id` must already exist:

```yaml
  - id: make_beams
    name: Make Beams
    building_id: foundry
    duration_sec: 8
    inputs: { steel: 2, energy: 1 }
    outputs: { beams: 1 }
```

(That example also needs a `beams` item entry.)

Broken references (unknown item/building ids) cause startup validation errors on purpose.
