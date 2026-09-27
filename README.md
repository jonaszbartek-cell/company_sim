# company_sim

Real-time company economic simulator (Python + Web UI).

Rival companies and cities will be driven by a **local LLM** (one model, many entities). Target: RTX 3050-class PCs.

## Design

See [docs/DESIGN.md](docs/DESIGN.md).

## Run (dev)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m company_sim --no-browser
```

Open http://127.0.0.1:8765/

### What works now

- Real-time tick loop with **pause**
- Map generated at start: cities, road lattice, **standard/specialized** plots
- **Every plot has road access** (asserted)
- Player starts with **cash + starter plot + inventory**
- Buy plot, build workshop, **build road**, **merge adjacent owned plots** (parcel production bonus)
- Heuristic AI stub (LLM not wired yet)

### Controls

- Click plot → Buy / Build / Build road
- Click two adjacent owned plots (second click selects; first remembered) → **Merge with last**
- Pause / Resume
