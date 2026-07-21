# inf-agent

A tiny stdlib-only Python HTTP service that reads your inference-provider
credentials on **one** host and serves a single JSON snapshot of every
provider's limits/balance. The Ulanzi **Inference Monitor** plugin polls it (like
sysmon-agent) and renders the tiles.

Run it on the box that already holds your keys — here, the hermes NUC.

## Run

```bash
python3 inf-agent.py
# -> [inf-agent] listening on 0.0.0.0:9890 providers=claude,openai,openrouter,nous,ollama_cloud interval=60s
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
// kind:"limit" (Claude, OpenAI, Ollama Cloud)
{ "id":"claude", "name":"Claude", "kind":"limit", "icon":"robot", "ok":true,
  "headline":"Max 20x",
  "session":{ "pct":8.0, "resets_at":"…", "resets_in":"4h 15m" },   // 5-hour window
  "week":   { "pct":2.0, "resets_at":"…", "resets_in":"5d 23h" } }  // 7-day window

// OpenAI/Codex currently returns account-dependent windows. A Pro account may
// expose only a weekly window; then session is null and week contains the gauge.
{ "id":"openai", "name":"OpenAI", "kind":"limit", "icon":"lightning-bolt", "ok":true,
  "headline":"Pro", "plan":"Pro", "session":null,
  "week":{ "pct":23.0, "label":"WEEK", "resets_at":1785278767, "resets_in":"5d 23h" } }

// kind:"balance" (OpenRouter, Nous)
{ "id":"openrouter", "name":"OpenRouter", "kind":"balance", "icon":"swap-horizontal",
  "ok":true, "balance":8.29, "currency":"USD",
  "spend_today":0.02, "spend_week":0.03, "spend_month":19.51, "headline":"$8.29" }
```

Ollama Cloud has **no per-window usage API**, so its `session`/`week` are `null`
and the tiles fall back to `plan` + `renews_in`. Nous reports its live plan and
balance through hermes's account helper, with rate fields decoded from the portal
JWT as a secondary detail.

## Configuration (env)

| Var | Default | Meaning |
|-----|---------|---------|
| `INF_AGENT_PORT` | `9890` | listen port |
| `INF_AGENT_BIND` | `0.0.0.0` | bind address (set the Tailscale IP to stay on the tailnet) |
| `INF_AGENT_TOKEN` | – | shared secret; require `?token=…` or `Authorization: Bearer …` |
| `INF_AGENT_INTERVAL` | `60` | seconds between provider refreshes (min 15) |
| `INF_AGENT_PROVIDERS` | `claude,openai,openrouter,nous,ollama_cloud` | which probes to run |
| `INF_CLAUDE_CREDS` | `/root/.claude/.credentials.json` | Claude OAuth credentials |
| `INF_OPENAI_CREDS` | `/root/.codex/auth.json` | Codex ChatGPT credentials (read-only) |
| `INF_OPENAI_SESSIONS` | `/root/.codex/sessions` | local Codex rollouts used only as a stale fallback |
| `INF_HERMES_ENV` | `/root/.hermes/.env` | dotenv with `OPENROUTER_API_KEY` (and optionally `OLLAMA_API_KEY`) |
| `INF_HERMES_CONFIG` | `/root/.hermes/config.yaml` | hermes config (Ollama key fallback) |
| `INF_NOUS_PORTAL` | `/root/.hermes/nous-portal.json` | Nous portal token |
| `OPENROUTER_API_KEY` / `OLLAMA_API_KEY` | – | explicit key overrides (win over file discovery) |
| `INF_NOUS_HELPER_PY` | `/root/.hermes/hermes-agent/venv/bin/python` | hermes venv python used for the live Nous account fetch |
| `INF_NOUS_HELPER_CWD` | `/root/.hermes/hermes-agent` | working dir for the helper import |
| `INF_NOUS_LIVE_TTL` | `60` | seconds to cache the live Nous account fetch |
| `INF_NOUS_PLAN` / `INF_NOUS_BALANCE` | – | Nous plan/balance fallback when hermes has no live session |

## Where the numbers come from

| Provider | Source | Notes |
|----------|--------|-------|
| **Claude** | `GET api.anthropic.com/api/oauth/usage` + `/profile` (Bearer = Claude Code OAuth token) | `five_hour.utilization` → session %, `seven_day.utilization` → week %, plus `resets_at`. The agent **reads** the token Claude Code keeps fresh and never refreshes it (so it can't clobber the credential file). On a `401` it reports `ok:false`. |
| **OpenAI** | `GET chatgpt.com/backend-api/wham/usage` (Bearer + ChatGPT account id from Codex auth) | Reads the same account-limit payload used by the official Codex CLI. The agent never refreshes or writes auth. Actual window duration controls the tile label; recent local Codex JSONL is the offline fallback. |
| **OpenRouter** | `GET /api/v1/credits` + `/api/v1/key` | balance = `total_credits − total_usage`; spend from `usage_daily/weekly/monthly`. |
| **Nous** | rate limits/tier from portal JWT; plan + balance **live** via hermes's `get_nous_portal_account_info()` (run in the hermes venv) | hermes owns the single-use token refresh/persist/locking; the agent never calls the Nous refresh endpoint. Falls back to `INF_NOUS_PLAN`/`INF_NOUS_BALANCE` if hermes has no Nous session. |
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
