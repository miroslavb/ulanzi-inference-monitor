# Changelog

## 1.3.0

Studio-restart resilience (plugin-only; agent unchanged).

Root cause (observed live 2026-07-02): after an Ulanzi Studio restart the Property
Inspector still *shows* the saved Agent address, but Studio does not re-deliver the
stored key settings to the plugin's Node backend — so the sampler silently fell back
to the `127.0.0.1:9890` default and every key showed **"agent off"** until the user
re-saved any setting by hand.

- **Persist the agent address.** Every applied address change is written to
  `plugin/monitor/.agent-url.json` (fail-open); on startup the sampler begins from
  the persisted address instead of the localhost default. A Studio restart that
  drops the settings no longer takes the deck down.
- **Actively pull missing settings.** When a key is (re-)added without its stored
  params, the plugin now calls `getSettings` and consumes the `didReceiveSettings`
  reply — at most once per key, so never-configured keys can't loop.

## 1.2.1

Nous freshness + observability (agent-only; plugin unchanged from 1.1.0).

- **Faster live refresh:** `INF_NOUS_LIVE_TTL` default 300s → **60s**, so the tile
  tracks the account API within ~1 min instead of up to 5 min. (Residual gap to the
  portal *dashboard* is Nous-side eventual consistency — `/api/oauth/account` trails
  the portal UI slightly and can't be eliminated programmatically.)
- **Freeze is now visible, not silent:** if the live fetch fails, the agent still
  serves the last-good value but now (a) logs `nous live …` outcomes to the journal
  (`journalctl -u inf-agent`), and (b) flags `stale` + `live_age_s` once the last
  successful fetch ages past `NOUS_STALE_AFTER` (3×TTL) → the switch tile shows the
  amber dot. Previously a failing helper froze the value with no indication.

## 1.2.0

- **Live Nous balance & plan (agent).** The agent now reads the real portal
  subscription + purchased credits (e.g. **Plus / $18.93 / $22-mo**) by delegating
  to hermes's own `get_nous_portal_account_info()` run in the hermes venv — the
  sanctioned path that refreshes + persists the single-use token with hermes's
  locking (the agent still NEVER calls the refresh endpoint itself). Cached
  `INF_NOUS_LIVE_TTL` (default 300s). Precedence: live > `INF_NOUS_*` env fallback >
  rate-limits. New env: `INF_NOUS_HELPER_PY`, `INF_NOUS_HELPER_CWD`, `INF_NOUS_LIVE_TTL`.
  (Plugin unchanged from 1.1.0 — this is an agent-only release; the bundled plugin
  zip is bumped for version parity.)

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
