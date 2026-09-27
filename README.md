# company_sim

Real-time company economic simulator (Python + Web UI).

Rival companies and cities will be driven by a **local LLM** (one model, many entities). Target: RTX 3050-class PCs. Ship later as a single exe that also launches the LLM.

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

### What works now (scaffold)

- Real-time tick loop with pause
- 5 cities, roads, buyable plots spawned beside roads
- Buy plot / build workshop (placeholder production)
- Heuristic AI stub expanding cities and buying plots (LLM not wired yet)
- Simple 2D canvas map

### Controls

- Click a green plot → **Buy plot** → **Build workshop**
- **Pause** / Resume
