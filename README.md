# company_sim

Real-time company economic simulator (Python + Web UI).

**City** and **Company** both inherit from **Actor** and share the same Action API. AI rivals (companies + cities) can be driven by a **local LLM** with tools (one model, many minds). Target: RTX 3050-class PCs.

## Docs

- [docs/DESIGN.md](docs/DESIGN.md)
- [docs/CLASSES.md](docs/CLASSES.md) — domain classes (`Actor`, `Item`, `Plot`, `Building`, …)
- [data/README.md](data/README.md) — how to add items / buildings / recipes in YAML
- [docs/LLM.md](docs/LLM.md) — enable Ollama / tool bridge

## Run (dev)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m company_sim --no-browser
```

Open http://127.0.0.1:8765/

### Optional local LLM

```bash
export COMPANY_SIM_LLM=1
export COMPANY_SIM_LLM_MODEL=qwen2.5:3b-instruct
PYTHONPATH=src python -m company_sim
```

Without LLM env vars, AI uses heuristics (game still runs).

### What works now

- Actor base class → Company / City
- Real-time tick + pause; pre-generated map; road-access invariant
- Player: buy / build / road / merge
- LLM tools → same Action API as the UI (Ollama-compatible)

### Controls

- Click plot → Buy / Build / Build road
- Two adjacent owned plots → Merge with last
- Pause / Resume
