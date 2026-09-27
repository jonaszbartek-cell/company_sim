# Actor + LLM bridge

## Actor hierarchy

```text
Actor (cash, inventory, id, name, acted_this_day)
├── Company  (is_player)
└── City     (center, population, territory)
```

## Engine loop

1. Refresh `saves/world.txt`, `market.txt`, `agents/*.txt`, `mailboxes/*.txt`
2. LLM loads **world + market + this agent file + this agent's mailboxes**
3. Tools call the World Action API (economy + `send_message`)
4. Agent marked acted → next AI agent
5. When **all companies** acted → `day += 1`

Wall-clock gap between turns: `WorldConfig.min_seconds_between_turns` (slow only).

## Mail (AGENT↔AGENT / AGENT↔USER)

Startup builds one text mailbox per unordered pair (`C(n,2)` files under `saves/mailboxes/`).

| Tool | Purpose |
|------|---------|
| `list_contacts` | Who you can message |
| `read_mail` | Read your threads (optional filter) |
| `send_message` | Append to the shared pair mailbox |

Player UI uses the same Action API (`POST /api/player/message`).

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
| `list_contacts` / `read_mail` / `send_message` | Mail |
| `pass_turn` / `done` | End turn |

All tools go through `ToolExecutor` → World actions (same validation as the player UI).
