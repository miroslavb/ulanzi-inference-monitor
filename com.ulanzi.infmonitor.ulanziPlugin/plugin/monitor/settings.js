// settings.js — normalise Property Inspector settings (pure).
//
// Two actions:
//   * Provider Tile  — one of two slots (primary / secondary) of the ACTIVE
//     provider. Place two: one primary, one secondary.
//   * Provider Switch — cycles the active provider on each press.
// Both carry the agent address so a tile works even without a switch key on the
// deck; the plugin uses the most recently configured non-empty address.

export const DEFAULT_MS = 5000;          // provider quotas move slowly — poll gently
export const DEFAULT_AGENT = 'http://127.0.0.1:9890';

function clampInt(v, lo, hi, def) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : def;
}
function theme(v) { return v === 'light' ? 'light' : 'dark'; }
function agentUrl(v) { return (v && String(v).trim()) || ''; }

export function readTileSettings(param = {}) {
  return {
    slot: param.slot === 'secondary' ? 'secondary' : 'primary',
    theme: theme(param.theme),
    agentUrl: agentUrl(param.agentUrl),
    refresh: clampInt(param.refresh, 2000, 60000, DEFAULT_MS),
  };
}

export function readSwitchSettings(param = {}) {
  return {
    theme: theme(param.theme),
    agentUrl: agentUrl(param.agentUrl),
    refresh: clampInt(param.refresh, 2000, 60000, DEFAULT_MS),
  };
}
