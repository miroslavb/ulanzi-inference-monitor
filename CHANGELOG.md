# Changelog

## 1.1.0

Bug-fix release from on-device feedback.

- **Ring gauge double segment (fix):** the progress arc used `stroke-dasharray`
  with `pathLength="100"`, but the D200H's SVG renderer ignores `pathLength` — so
  the normalised dash was read in real user units and tiled a spurious SECOND arc.
  Now drawn as an explicit `<path … A …>` arc (one definite start/end), renderer-agnostic.
- **Transient "usage HTTP 4xx" on tiles (fix):** the agent now keeps a per-provider
  last-good cache. When a probe briefly fails — e.g. Claude's OAuth token 401s while
  Claude Code rotates it — the tile shows the last good value marked `stale` (amber dot
  on the switch key) instead of an error card. Only a never-succeeded provider shows an error.
- **Nous showed "Free" (fix):** the hermes `nous-portal.json` token is the *hermes-agent
  free-tier* identity (and was logged out/expired), so the old probe mislabeled the real
  account as Free. The probe no longer infers "Free" from the stale JWT. Plan & balance now
  come from `INF_NOUS_PLAN` / `INF_NOUS_BALANCE` overrides (authoritative) or the live
  `GET /api/oauth/account` **only when a valid token exists**. The agent NEVER calls the Nous
  refresh endpoint (single-use; only hermes may rotate it — reuse revokes the whole session).
  The balance tile now shows the plan as its caption.

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
