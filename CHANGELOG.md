# Changelog

## 1.0.0

Initial release — sibling of ulanzi-system-monitor for inference providers.

- **inf-agent** (stdlib Python): one `GET /providers` snapshot for Claude,
  OpenRouter, Nous and Ollama Cloud, refreshed every 60s.
  - Claude: session (5h) + week (7d) utilisation % and resets, via the Anthropic
    OAuth `usage`/`profile` endpoints (reads the Claude Code token, never refreshes
    it). Plan headline (e.g. "Max 20x").
  - OpenRouter: balance (`credits`) + spend today/week/month (`key`).
  - Nous: tier, spend and rate limits decoded locally from the portal JWT (free tier).
  - Ollama Cloud: plan + billing-period renewal (no usage API exists → no session/week %).
  - Token guard (`INF_AGENT_TOKEN`), bind address, poll interval, provider list and
    credential paths all configurable via env.
- **Plugin** (reuses the System Monitor interface model):
  - **Provider Switch** cycler key — each press selects the next provider.
  - **Provider Tile** — Primary/Secondary slot renders the active provider:
    session/week ring gauges for limit providers, balance/spend value cards for
    balance providers, with graceful fallbacks (plan/renewal, rate limits).
  - Single `ProviderSampler` with the no-wedge guaranteed-settle fetch from
    RemoteSampler; per-key independent rendering keyed by stable actionid.
  - Dark/Light themes; configurable refresh (5/10/30s).
- Added `robot` + `swap-horizontal` to the MDI icon subset for provider glyphs.
