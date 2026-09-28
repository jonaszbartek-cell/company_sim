# company_sim

Company economic simulator (Python + Web UI) with local LLM rivals.

**Now:** Setup screen (AI companies, cities, map size). Cities own all plots at start; companies buy land via direct proposals. Edge roads + combine flags. Day turns, market, text saves.

## Docs

- [docs/DESIGN.md](docs/DESIGN.md)
- [docs/CLASSES.md](docs/CLASSES.md)
- [data/README.md](data/README.md)
- [docs/LLM.md](docs/LLM.md)

## Run (dev)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m company_sim --no-browser
```

Open http://127.0.0.1:8765/ — choose companies / cities / map size, then Start.

### Optional local LLM

```bash
export COMPANY_SIM_LLM=1
export COMPANY_SIM_LLM_MODEL=qwen2.5:3b-instruct
PYTHONPATH=src python -m company_sim
```

### What works now

- Setup: AI company count, city count, plots-per-side; files created on start
- Cities own all territory plots; companies start with none
- Edge roads (N/E/S/W on owned plots); combine flags (no road between)
- Plot buy/sell as direct proposals with accept/reject
- Goods propose_sell / propose_buy with accept/reject
- Market (companies only) + city government contracts
- Day advances when all companies have acted
- Text saves under `saves/` for LLM context

### Controls

- Propose buy/sell plot → Accept / Reject proposals
- Build / Produce / Road (pick side) / Combine
- Market: Buy 1 iron / Sell 1 steel
- Mail: pick contact → send message
- Pass day / Pause
