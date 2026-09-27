# Actor + LLM bridge

## Actor hierarchy

```text
Actor (cash, inventory, id, name)
├── Company  (is_player)
└── City     (center, population, territory)
```

Both use the same World Action API (`buy_plot`, `build_building`, `build_road`, `merge_plots`).

## Local LLM connection

Set env vars, run Ollama (or compatible server), then start the game:

```bash
# terminal 1
ollama serve
ollama pull qwen2.5:3b-instruct   # good default for RTX 3050

# terminal 2
export COMPANY_SIM_LLM=1
export COMPANY_SIM_LLM_MODEL=qwen2.5:3b-instruct
export COMPANY_SIM_LLM_URL=http://127.0.0.1:11434
PYTHONPATH=src python -m company_sim
```

Without `COMPANY_SIM_LLM=1`, AI uses the built-in heuristic (game still runs).

### Tools exposed to the model

| Tool | Purpose |
|------|---------|
| `get_status` | Own cash / inventory / plots |
| `get_market_overview` | Nearby unowned plots |
| `buy_plot` | Buy plot |
| `build_building` | Build on owned plot |
| `build_road` | Pave road |
| `merge_plots` | Merge adjacent owned plots |
| `done` | End decision |

All tools go through `ToolExecutor` → World actions (same validation as the player UI).
One LLM decision runs at a time; the realtime sim never blocks.
