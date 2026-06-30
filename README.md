# Ulanzi Inference Monitor

Live **usage limits** and **balances** for your inference providers, drawn on your
Ulanzi deck keys — a sibling of [ulanzi-system-monitor](https://github.com/miroslavb/ulanzi-system-monitor)
that reuses the same interface model (a **cycler key** + tiles that follow the
active selection).

One key cycles the provider; two tiles show its numbers:

| Provider | Kind | Primary tile | Secondary tile |
|----------|------|--------------|----------------|
| **Claude** (Anthropic) | limits | Session (5h) % + reset | Week (7d) % + reset |
| **Ollama Cloud** | limits | Plan | Renews in… |
| **OpenRouter** | balance | Balance ($) | Spend today / week |
| **Nous** | balance | Free / tier | Rate limit (rpm/tpm) |

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Provider │  │  ◐ 8%    │  │  ◔ 2%    │
│  Switch  │  │ SESSION  │  │  WEEK    │     ← Claude selected
│ 🤖 Claude│  │ ↻ 4h 15m │  │ ↻ 5d 23h │
│   1/4 8% │  └──────────┘  └──────────┘
└──────────┘   press switch →  $8.29 / today $0.02   ← OpenRouter selected
```

## Architecture

```
 host with your keys (hermes NUC)              machine running Ulanzi Studio
┌───────────────────────────────┐            ┌──────────────────────────────┐
│ inf-agent.py                   │  HTTP      │ Inference Monitor plugin       │
│  reads .claude / .hermes creds │  (Tailscale)│  ProviderSampler → /providers │
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
3. Press the switch to cycle Claude → OpenRouter → Nous → Ollama Cloud. The tiles
   follow the selection.

(You can also set the agent address on a Provider Tile, so a lone tile works
without a switch — the most recently configured address wins.)

## Notes & limitations

- **Claude** session/week come from the Anthropic OAuth `usage` endpoint using the
  token Claude Code keeps fresh; the agent only **reads** it (never refreshes, so
  it can't disturb your Claude Code login). On token expiry the tile shows an error
  until Claude Code refreshes.
- **Ollama Cloud** exposes no per-window usage via any API, so its limit tiles show
  plan + renewal date rather than a session/week %.
- **Nous** rate limits/tier come from the portal JWT (no network call). The hermes
  portal token is the *agent's free-tier* identity, so the agent never infers "Free"
  from it and **never refreshes it** (Nous refresh tokens are single-use; reuse revokes
  the whole session — only hermes may rotate them). Your real plan + purchased balance
  come from `INF_NOUS_PLAN` / `INF_NOUS_BALANCE` (authoritative), or the live
  `GET /api/oauth/account` *only when a valid token exists*. Update the balance env when
  it changes, or `hermes auth add nous` to restore a live session.
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
