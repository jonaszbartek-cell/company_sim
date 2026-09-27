# company_sim — Design Document

**Status:** Draft v0.6  
**Date:** 2026-09-27  
**Repo:** [jonaszbartek-cell/company_sim](https://github.com/jonaszbartek-cell/company_sim)

---

## 1. Game concept

Real-time company economic simulator on a **2D grid** of **normal roads and plots only**.

### City clarification (Owner)

A **city is not a special tile or mega-building**.

A city is an **LLM agent** responsible for running a municipality. On the map, that municipality is just:

- normal **roads**
- normal **plots** (standard / specialized)
- normal **buildings** on those plots (companies or the city itself may own them)

The city agent administers a **territory** (set of cells) and acts through the same kinds of actions as companies where relevant (roads, claiming/building on plots, later trade/policy).

---

## 2. Locked decisions

| Topic | Decision |
|-------|----------|
| Stack | Python + Web UI → later one exe + local LLM |
| Time | Real-time + pause |
| GPU | RTX 3050 |
| AI | One LLM switching across ~20 companies + ~5 cities |
| Map cells | Only `road` and `plot` (+ rare empty hinterland) |
| City | LLM + territory + treasury/inventory — **not** a unique cell type |
| Plot types | `standard`, `specialized` |
| Road access | Every plot adjacent to a road |
| Merge | Adjacent owned plots → parcel bonuses |
| Road builders | Cities and companies |
| Player start | Cash + starter plot + inventory |
| Goods/recipes | TBD |

---

## 3. World model

```text
Actor (base)
├── Company — cash, inventory; may be player-controlled
└── City — cash, inventory, population, territory of normal cells

Map tiles: road | plot
Plot: type, owner (company|city|none), building?, parcel?
```

Ownership: `owner_kind` + `owner_id`. LLM tools and player UI share the World Action API.

See also [LLM.md](LLM.md) for local model wiring.

---

## 4. Map generation

1. Place city **anchors** (not special tiles).
2. Voronoi-assign every cell to nearest city → `tile.city_id`.
3. Road lattice + corridors between anchors.
4. Remaining cells → plots.
5. Assert every plot has road access.
6. Build city.territory lists from `city_id`.

---

## 5. Assumptions (changeable)

- Territory boundaries start as nearest-city voronoi; later growth/annexation TBD.
- Cities may own plots and build buildings like companies (municipal workshops for now).
- Soft UI tint shows which city administers a cell; no “C” mega-tile.

---

## 6. Need later (not blocking)

1. Specialized plot rules  
2. Parcel bonus values  
3. Goods / buildings / production methods  
4. How city population relates to buildings vs abstract stock  
5. Whether companies need city permission to build in a territory  
