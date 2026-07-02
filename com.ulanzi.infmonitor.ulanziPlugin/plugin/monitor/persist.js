// persist.js — remember the last working agent address across Studio restarts.
//
// Why: Ulanzi Studio does not reliably re-deliver stored key settings to the
// plugin's Node backend after a Studio restart (the Property Inspector still
// *shows* the saved address, but the backend never receives it). Without this,
// the sampler falls back to DEFAULT_AGENT (127.0.0.1) and the deck shows
// "agent off" until the user re-saves any setting. Observed live 2026-07-02.
//
// The file lives next to the plugin code and is written only when the applied
// address actually changes. Everything is fail-open: a read/write error must
// never break the plugin (worst case we just fall back to the default).

import fs from 'fs';

export function loadAgentUrl(file) {
  try {
    const j = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (j && typeof j.agentUrl === 'string' && j.agentUrl.trim()) return j.agentUrl.trim();
  } catch (e) { /* missing or corrupt — fall through */ }
  return '';
}

export function saveAgentUrl(file, url) {
  try {
    fs.writeFileSync(file, JSON.stringify({ agentUrl: String(url), savedAt: new Date().toISOString() }) + '\n');
    return true;
  } catch (e) { return false; }
}
