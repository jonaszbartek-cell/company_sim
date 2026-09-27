# Actor + LLM bridge

## Actor hierarchy

```text
Actor (cash, inventory, id, name, acted_this_day)
├── Company  (is_player)
└── City     (center, population, territory)
```

## Engine loop

1. Refresh `saves/world.txt`, `saves/market.txt`, `saves/agents/*.txt`
2. LLM loads **world + market + this agent file**
3. Tools call the World Action API
4. Agent marked acted → next AI agent
5. When **all companies** acted → `day += 1`

Wall-clock gap between turns: `WorldConfig.min_seconds_between_turns` (slow only).

## Local LLM

```bash
ollama serve
ollama pull qwen2.5:3b-instruct

export COMPANY_SIM_LLM=1
export COMPANY_SIM_LLM_MODEL=qwen2.5:3b-instruct
PYTHONPATH=src python -m company_sim
```

Without `COMPANY_SIM_LLM=1`, AI uses heuristics (game still runs).

### Tools

| Tool | Purpose |
|------|---------|
| `get_status` | Own cash / inventory / plots |
| `get_market` | Listings + market inventory |
| `list_unowned_plots` | Nearby unowned plots |
| `buy_plot` / `build_building` / `produce` | Core loop |
| `post_sell` / `post_buy` / `buy_from_market` | Market |
| `set_production_method` | Choose recipe |
| `build_road` / `merge_plots` | Map |
| `pass_turn` / `done` | End turn |

All tools go through `ToolExecutor` → World actions (same validation as the player UI).
