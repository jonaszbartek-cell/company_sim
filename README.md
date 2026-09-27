# company_sim

Company economic simulator (Python + Web UI) with local LLM rivals.

**Now:** 1 player + 2 AI companies + 1 city agent. Day-based turns, indexed market, text-file saves for LLM context.

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

Open http://127.0.0.1:8765/

### Optional local LLM

```bash
export COMPANY_SIM_LLM=1
export COMPANY_SIM_LLM_MODEL=qwen2.5:3b-instruct
PYTHONPATH=src python -m company_sim
```

### What works now

- Agent base → Company / City
- Day advances when all companies have acted (slowable AI turns)
- Market: sell/buy orders, retract, standard buy (lowest price); cash only moves on fill
- Direct proposals: agent↔agent sell/buy offers with escrow (no duplicate goods/cash)
- Produce action on foundries (iron+coal+energy → steel)
- Text saves under `saves/` (world, market, proposals, per-agent, pairwise mailboxes)
- Sequential LLM/heuristic engine: one agent, then the next
- Mail: AGENT↔AGENT and AGENT↔USER via `send_message` / player UI

### Controls

- Click plot → Buy / Build / Produce / Road / Merge
- Market: Buy / Sell / Buy order / Retract #
- Direct trade: propose sell/buy, accept/reject/cancel
- Mail: pick contact → send message
- Pass day / Pause
