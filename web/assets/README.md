# Placeholder arts (`web/assets/`)

All game graphics live here (served as `/static/assets/...`).  
Regenerate with: `python scripts/generate_placeholder_arts.py`

```text
web/assets/
  goods/{item_id}.svg                 # flat UI icons
  buildings/
    ui/{building_id}.svg              # flat build-picker icons
    map/{building_id}/{w}x{h}.svg     # fake-3D map sprites (1..9 × 1..9)
  terrain/
    grass.svg
    grass_specialized.svg
  roads/
    mask_{0..15}.svg                  # asphalt + side lines (N=1 E=2 S=4 W=8)
```

| Folder | Style | Used for |
|--------|-------|----------|
| `goods/` | Flat modern 2D | Inventory, market, building storage |
| `buildings/ui/` | Flat modern 2D | Build picker / preview |
| `buildings/map/<id>/` | Fake-3D | Map footprint `w×h` |
| `terrain/` | Flat modern | Plot ground |
| `roads/` | Asphalt + lines | Edge roads / corners / crosses |
