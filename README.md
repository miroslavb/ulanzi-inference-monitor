# Ulanzi Inference Monitor

Live **usage limits** and **balances** for your inference providers, drawn on your
Ulanzi deck keys — a sibling of [ulanzi-system-monitor](https://github.com/miroslavb/ulanzi-system-monitor)
that reuses the same interface model (a **cycler key** + tiles that follow the
active selection).

**Latest release:** [v1.5.0](https://github.com/miroslavb/ulanzi-inference-monitor/releases/tag/v1.5.0)
ships both the [Ulanzi Studio plugin](https://github.com/miroslavb/ulanzi-inference-monitor/releases/download/v1.5.0/com.ulanzi.infmonitor.ulanziPlugin-1.5.0.zip)
and the [standalone inf-agent](https://github.com/miroslavb/ulanzi-inference-monitor/releases/download/v1.5.0/inf-agent-1.5.0.zip).

One key cycles the provider; two tiles show its main numbers, with an optional
third monthly tile for providers that expose it:

| Provider | Kind | Primary tile | Secondary tile |
|----------|------|--------------|----------------|
| **Claude** (Anthropic) | limits | Session (5h) % + reset | Week (7d) % + reset |
| **OpenAI** (Codex) | limits | Short window % or plan | Long window % + reset |
| **Ollama Cloud** | limits | Session (5h) % | Week (7d) % |
| **OpenCode Go** | limits | Rolling 5h % + reset | Week % + reset (monthly on a third tile) |
| **OpenRouter** | balance | Balance ($) | Spend today / week |
| **Nous** | balance | Free / tier | Rate limit (rpm/tpm) |

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Provider │  │  ◐ 8%    │  │  ◔ 2%    │
│  Switch  │  │ SESSION  │  │  WEEK    │     ← Claude selected
│ 🤖 Claude│  │ ↻ 4h 15m │  │ ↻ 5d 23h │
│   1/6 8% │  └──────────┘  └──────────┘
└──────────┘   press switch →  $8.29 / today $0.02   ← OpenRouter selected
```

## Architecture

```
 host with your keys (hermes NUC)              machine running Ulanzi Studio
┌───────────────────────────────┐            ┌──────────────────────────────┐
│ inf-agent.py                   │  HTTP      │ Inference Monitor plugin       │
│  reads .claude/.codex/.hermes  │  (Tailscale)│  ProviderSampler → /providers │
│  GET /providers  → all providers├───────────▶│  Switch key cycles providers  │
│  refreshes every 60s           │            │  Tiles render the active one  │
└───────────────────────────────┘            └──────────────────────────────┘
```

The **agent** does all provider-specific work and lives where the credentials
already are; the **plugin** just polls one endpoint and renders. See
[`agent/README.md`](agent/README.md) for the JSON contract and per-provider sources.

## Setup

### 1. Run the agent on the host with your keys

```bash
cd agent
python3 inf-agent.py            # listens on 0.0.0.0:9890
# or install as a service — see agent/README.md
```

Verify: `curl http://localhost:9890/providers | python3 -m json.tool`

### 2. Install the plugin in Ulanzi Studio

```bash
./pack.sh                       # builds dist/com.ulanzi.infmonitor.ulanziPlugin-<ver>.zip
```

Double-click the `.zip` (or import it in Ulanzi Studio). Then on the deck:

1. Drop a **Provider Switch** key. In its settings put the agent address —
   `http://127.0.0.1:9890` if Studio runs on the same box, otherwise the agent
   host's Tailscale address, e.g. `http://100.x.y.z:9890`.
2. Drop two **Provider Tile** keys next to it; set one to **Primary** and one to
   **Secondary**.
3. In the switch settings, tick only the providers that this key should cycle.
   Older switch settings continue to include all providers. Press the key to cycle
   the chosen providers; the tiles follow the selection.

OpenCode Go exposes three windows. Add a third **Provider Tile** and set it to
**Monthly** to show its monthly limit; that slot also shows OpenRouter's monthly
spend when available.

(You can also set the agent address on a Provider Tile, so a lone tile works
without a switch — the most recently configured address wins.)

## Notes & limitations

- **Claude** session/week come from the Anthropic OAuth `usage` endpoint using the
  token Claude Code keeps fresh; the agent only **reads** it (never refreshes, so
  it can't disturb your Claude Code login). On token expiry the tile shows an error
  until Claude Code refreshes.
- **OpenAI** usage comes from the same read-only ChatGPT usage endpoint used by
  Codex (`/backend-api/wham/usage`). The agent reads `/root/.codex/auth.json` but
  never refreshes or writes it. Window labels follow the durations OpenAI actually
  returns (for example `5H` and `WEEK`); accounts with only a weekly window show
  the plan on the first tile and the weekly gauge on the second. If the endpoint
  is briefly unavailable, the newest local Codex rate-limit snapshot is shown as
  stale until live polling recovers.
- **Ollama Cloud** exposes live session and weekly fractions at its authenticated
  `GET /api/usage` endpoint. The endpoint does not include reset timestamps, so
  its gauges intentionally do not invent a countdown. Plan/renewal metadata still
  comes from `POST /api/me` when available.
- **OpenCode Go** reads its key (prefer `OPENCODE_GO_API_KEY`, otherwise OpenCode's
  local `auth.json`) and uses `GET /zen/go/v1/usage` for rolling 5-hour, weekly,
  and monthly percentages and reset times. A rejected key or missing subscription
  is isolated to that provider and does not interrupt the other tiles.
- **Nous** rate limits/tier come from the portal JWT (no network call). Real plan +
  purchased balance are read **live** from the portal account API by delegating to
  hermes's own `get_nous_portal_account_info()` (run in the hermes venv) — hermes owns
  the single-use token refresh + persistence + locking, so the agent **never** calls the
  Nous refresh endpoint itself (reuse revokes the whole session). Configure via
  `INF_NOUS_HELPER_PY` / `INF_NOUS_HELPER_CWD` (defaults point at this box's hermes), cached
  `INF_NOUS_LIVE_TTL` (60s). If hermes has no Nous session, it falls back to the
  `INF_NOUS_PLAN` / `INF_NOUS_BALANCE` env values; restore live with `hermes auth add nous`.
- **Dialagram** is intentionally not included (no balance API; subscription
  inactive). Add providers by extending `agent/inf-agent.py` (`PROBES`).
- Secure the agent with `INF_AGENT_TOKEN` and/or bind it to your Tailscale IP if the
  host is reachable beyond the tailnet.

## Layout

```
agent/inf-agent.py         provider probes + HTTP endpoint (stdlib only)
agent/inf-agent.service    systemd unit
com.ulanzi.infmonitor.ulanziPlugin/
  plugin/app.js            main loop: sampler + cycler + paint
  plugin/monitor/ProviderSampler.js   polls /providers (no-wedge fetch)
  plugin/monitor/render.js            ring-gauge & value-card tiles + switch tile
  plugin/monitor/settings.js          PI settings
  property-inspector/      tile + switch config UIs
pack.sh                    build the plugin + agent zips into dist/
```

Reuses the device API (`plugin/common-node`), PI framework (`libs/`) and MDI icon
subset from ulanzi-system-monitor.
