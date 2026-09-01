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
function slot(v) { return v === 'secondary' || v === 'tertiary' ? v : 'primary'; }

// `null` deliberately means "all providers" for settings saved before 1.5.0.
// An explicit array is an allow-list in the agent's stable response order.
export function providerIds(value) {
  if (!Array.isArray(value)) return null;
  const seen = new Set();
  const ids = [];
  for (const valueId of value) {
    const id = typeof valueId === 'string' ? valueId.trim() : '';
    if (!id || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  return ids;
}

export function visibleProviders(providers, ids) {
  const list = Array.isArray(providers) ? providers.filter((p) => p && p.id) : [];
  return ids == null ? list : list.filter((p) => ids.includes(p.id));
}

export function nextProviderId(providers, currentId) {
  if (!providers.length) return null;
  const i = providers.findIndex((p) => p.id === currentId);
  return providers[(i + 1 + providers.length) % providers.length].id;
}

export function readTileSettings(param = {}) {
  return {
    slot: slot(param.slot),
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
    providerIds: providerIds(param.providerIds),
  };
}
