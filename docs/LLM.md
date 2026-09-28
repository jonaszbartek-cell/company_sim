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
| `list_plots_for_sale` | Plots owned by others (for plot buy proposals) |
| `propose_plot_buy` / `propose_plot_sell` | Direct plot deals (escrow / lock) |
| `build_building` / `produce` | Core loop |
| `post_sell` / `post_buy` / `buy_from_market` | Market |
| `retract_sell` / `retract_buy` | Cancel own market orders |
| `propose_sell` / `propose_buy` | Direct goods AGENT↔AGENT proposals |
| `list_proposals` / `accept_proposal` / `reject_proposal` | Resolve any direct proposal |
| `set_production_method` | Choose recipe |
| `build_road` (side N/E/S/W) / `merge_plots` | Edge roads (cost 1 steel) + combine flags |
| `list_contacts` / `read_mail` / `send_message` | Mail |
| `post_government_contract` / `award` / `cancel` | CITY procurement |
| `bid_government_contract` / `fulfill_government_contract` | COMPANY fulfillment |
| `list_government_contracts` | View open/awarded contracts |
| `pass_turn` / `done` | End turn |

**Cities cannot use the market** — only government contracts for goods. Cities and companies both use plot proposals (accept/reject).

All tools go through `ToolExecutor` → World actions (same validation as the player UI).
