# inf-agent

A tiny stdlib-only Python HTTP service that reads your inference-provider
credentials on **one** host and serves a single JSON snapshot of every
provider's limits/balance. The Ulanzi **Inference Monitor** plugin polls it (like
sysmon-agent) and renders the tiles.

Run it on the box that already holds your keys — here, the hermes NUC.

## Run

```bash
python3 inf-agent.py
# -> [inf-agent] listening on 0.0.0.0:9890 providers=claude,openrouter,nous,ollama_cloud interval=60s
```

Then from the machine running Ulanzi Studio:

```bash
curl http://<host>:9890/providers | python3 -m json.tool
```

## Endpoints

| Path | Returns |
|------|---------|
| `GET /providers` (or `/`) | `{ ts, agent_host, interval, providers: [ … ] }` |
| `GET /healthz` | `ok` |

Each `providers[]` entry:

```jsonc
// kind:"limit" (Claude, Ollama Cloud)
{ "id":"claude", "name":"Claude", "kind":"limit", "icon":"robot", "ok":true,
  "headline":"Max 20x",
  "session":{ "pct":8.0, "resets_at":"…", "resets_in":"4h 15m" },   // 5-hour window
  "week":   { "pct":2.0, "resets_at":"…", "resets_in":"5d 23h" } }  // 7-day window

// kind:"balance" (OpenRouter, Nous)
{ "id":"openrouter", "name":"OpenRouter", "kind":"balance", "icon":"swap-horizontal",
  "ok":true, "balance":8.29, "currency":"USD",
  "spend_today":0.02, "spend_week":0.03, "spend_month":19.51, "headline":"$8.29" }
```

Ollama Cloud has **no per-window usage API**, so its `session`/`week` are `null`
and the tiles fall back to `plan` + `renews_in`. Nous is a free tier — it reports
`free:true`, `tier`, `spend_total` and `rate` (rpm/tpm/rph/tph) decoded from the
portal JWT (no network call).

## Configuration (env)

| Var | Default | Meaning |
|-----|---------|---------|
| `INF_AGENT_PORT` | `9890` | listen port |
| `INF_AGENT_BIND` | `0.0.0.0` | bind address (set the Tailscale IP to stay on the tailnet) |
| `INF_AGENT_TOKEN` | – | shared secret; require `?token=…` or `Authorization: Bearer …` |
| `INF_AGENT_INTERVAL` | `60` | seconds between provider refreshes (min 15) |
| `INF_AGENT_PROVIDERS` | `claude,openrouter,nous,ollama_cloud` | which probes to run |
| `INF_CLAUDE_CREDS` | `/root/.claude/.credentials.json` | Claude OAuth credentials |
| `INF_HERMES_ENV` | `/root/.hermes/.env` | dotenv with `OPENROUTER_API_KEY` (and optionally `OLLAMA_API_KEY`) |
| `INF_HERMES_CONFIG` | `/root/.hermes/config.yaml` | hermes config (Ollama key fallback) |
| `INF_NOUS_PORTAL` | `/root/.hermes/nous-portal.json` | Nous portal token |
| `OPENROUTER_API_KEY` / `OLLAMA_API_KEY` | – | explicit key overrides (win over file discovery) |

## Where the numbers come from

| Provider | Source | Notes |
|----------|--------|-------|
| **Claude** | `GET api.anthropic.com/api/oauth/usage` + `/profile` (Bearer = Claude Code OAuth token) | `five_hour.utilization` → session %, `seven_day.utilization` → week %, plus `resets_at`. The agent **reads** the token Claude Code keeps fresh and never refreshes it (so it can't clobber the credential file). On a `401` it reports `ok:false`. |
| **OpenRouter** | `GET /api/v1/credits` + `/api/v1/key` | balance = `total_credits − total_usage`; spend from `usage_daily/weekly/monthly`. |
| **Nous** | portal JWT claims (decoded locally) | `subscription_tier`, `member_spend_usd`, `rate_limit_*`. Free tier → no `$` balance. `token_age_min` surfaces staleness. |
| **Ollama Cloud** | `POST ollama.com/api/me` | `Plan` + billing period (`SubscriptionPeriodEnd`). No usage API exists. |

## Install as a service (systemd)

```bash
sudo mkdir -p /opt/inf-agent
sudo cp inf-agent.py /opt/inf-agent/
sudo cp inf-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now inf-agent
systemctl status inf-agent
```

The agent reads credential files under `/root`, so the unit runs as root. If you
relocate the credentials, point the `INF_*` paths at readable copies and drop the
root requirement.
