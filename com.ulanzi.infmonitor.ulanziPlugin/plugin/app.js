// Main service for the Inference Monitor Ulanzi plugin.
//
// Shows usage limits / balances for the inference providers you use, read from a
// single `inf-agent` running on the box that holds your credentials. Mirrors the
// System Monitor plugin's interface model:
//
//   * "Provider Switch" (cycler) — one key; each press selects the next provider.
//   * "Provider Tile"   (metric) — renders the ACTIVE provider. Slot = primary or
//     secondary: for limit providers (Claude / Ollama Cloud) that's session / week;
//     for balance providers (OpenRouter / Nous) it's balance / spend.
//
// One agent returns ALL providers in one snapshot, so there is a single
// ProviderSampler; the switch just moves `currentIndex` within that list. Each
// key renders independently and is keyed by the stable actionid (D200H-safe).

import path from 'path';
import { fileURLToPath } from 'url';
import { UlanziApi } from './common-node/index.js';
import ProviderSampler from './monitor/ProviderSampler.js';
import { tileDataUri, switchTileDataUri } from './monitor/render.js';
import { readTileSettings, readSwitchSettings, DEFAULT_MS, DEFAULT_AGENT } from './monitor/settings.js';
import { loadAgentUrl, saveAgentUrl } from './monitor/persist.js';
import { MDI_LITE } from './monitor/mdi-lite.js';

const PLUGIN_UUID = 'com.ulanzi.ulanzistudio.infmonitor';
const MIN_MS = 2000, MAX_MS = 60000;

const $UD = new UlanziApi();

// --- single data source ------------------------------------------------------
// Studio-restart resilience: start from the last persisted agent address, not
// the localhost default — Studio does not reliably re-deliver key settings to
// the backend after a restart (the PI shows them; the backend never gets them).
const PERSIST_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), 'monitor', '.agent-url.json');
const sampler = new ProviderSampler(loadAgentUrl(PERSIST_FILE) || DEFAULT_AGENT);
let currentIndex = 0;          // which provider in sampler.providers is active

// --- instances ---------------------------------------------------------------
const tiles = {};      // actionid -> { id, context, active, slot, theme, agentUrl, refresh }
const switches = {};   // actionid -> { id, context, active, theme, agentUrl, refresh }
let refreshMs = DEFAULT_MS;
let timer = null;

$UD.connect(PLUGIN_UUID);
$UD.onConnected(() => {
  $UD.logMessage('Inference Monitor plugin connected', 'info');
  startTimer();
  // Fetch once up front so keys show data without waiting a full interval.
  sampler.sample().finally(paint);
});

function decode(ctx) {
  const dec = $UD.decodeContext(ctx);
  return { id: dec.actionid || ctx, key: dec.key, uuid: dec.uuid || '' };
}
function isSwitch(uuid) { return String(uuid).endsWith('.provswitch'); }

// Any key may carry the agent address; the latest non-empty one wins.
// Every applied change is persisted so the next plugin start survives a Studio
// restart that fails to re-deliver the stored settings.
function applyAgentUrl(url) {
  if (!url) return;
  const before = sampler.url;
  sampler.setUrl(url);
  if (sampler.url !== before) saveAgentUrl(PERSIST_FILE, url);
}

// Studio sometimes re-adds keys after a restart WITHOUT their stored params.
// For those, actively ask Studio for the saved settings (reply arrives as
// didReceiveSettings → upsert). Ask at most once per actionid so a genuinely
// empty (never-configured) key can't cause a request loop.
const settingsRequested = new Set();
function pullSettingsIfMissing(jsn, parsed) {
  if (parsed.agentUrl) return;                       // params arrived fine
  const { id } = decode(jsn.context);
  if (settingsRequested.has(id)) return;
  settingsRequested.add(id);
  try { $UD.getSettings(jsn.context); } catch (e) { /* fail-open */ }
}

// --- add / update ------------------------------------------------------------
function upsert(jsn) {
  const { id, uuid } = decode(jsn.context);
  if (isSwitch(uuid)) {
    if (!switches[id]) switches[id] = { id, context: jsn.context, active: true };
    switches[id].context = jsn.context;
    Object.assign(switches[id], readSwitchSettings(jsn.param));
    applyAgentUrl(switches[id].agentUrl);
    pullSettingsIfMissing(jsn, switches[id]);
    recomputeRefresh();
    paintSwitch(switches[id]);
  } else {
    if (!tiles[id]) tiles[id] = { id, context: jsn.context, active: true };
    tiles[id].context = jsn.context;
    Object.assign(tiles[id], readTileSettings(jsn.param));
    applyAgentUrl(tiles[id].agentUrl);
    pullSettingsIfMissing(jsn, tiles[id]);
    recomputeRefresh();
    paintTile(tiles[id]);
  }
}

$UD.onAdd((jsn) => upsert(jsn));
$UD.onParamFromPlugin((jsn) => upsert(jsn));
$UD.onParamFromApp((jsn) => upsert(jsn));
// Reply to our getSettings pull; Studio may put the payload in `param` or `settings`.
$UD.onDidReceiveSettings((jsn) => {
  if (!jsn || !jsn.context) return;
  upsert({ context: jsn.context, param: jsn.param || jsn.settings || {} });
});

$UD.onSetActive((jsn) => {
  const { id, uuid } = decode(jsn.context);
  const inst = isSwitch(uuid) ? switches[id] : tiles[id];
  if (inst) inst.active = !!jsn.active;
});

$UD.onClear((jsn) => {
  if (!jsn.param) return;
  for (const item of jsn.param) {
    const { id, uuid } = decode(item.context);
    if (isSwitch(uuid)) delete switches[id]; else delete tiles[id];
  }
});

// --- press: cycle the active provider ----------------------------------------
$UD.onRun((jsn) => {
  const { id, uuid } = decode(jsn.context);
  if (!isSwitch(uuid)) return;          // tiles do nothing on press
  const n = sampler.count();
  if (n > 0) currentIndex = (currentIndex + 1) % n;
  const sel = sampler.at(currentIndex);
  $UD.logMessage(`provider switch -> ${sel ? sel.name : '?'} (${currentIndex + 1}/${n})`, 'info');
  paint();
});

// --- sampling + painting -----------------------------------------------------
function recomputeRefresh() {
  const wanted = [...Object.values(tiles), ...Object.values(switches)].map((i) => i.refresh || DEFAULT_MS);
  const next = Math.max(MIN_MS, Math.min(MAX_MS, wanted.length ? Math.min(...wanted) : DEFAULT_MS));
  if (next !== refreshMs) { refreshMs = next; startTimer(); }
}

function startTimer() {
  if (timer) clearInterval(timer);
  timer = setInterval(tick, refreshMs);
}

async function tick() {
  try { await sampler.sample(); } catch (e) { /* never throws, but be safe */ }
  if (sampler.count() > 0) currentIndex = ((currentIndex % sampler.count()) + sampler.count()) % sampler.count();
  paint();
}

function paint() {
  for (const inst of Object.values(tiles)) paintTile(inst);
  for (const s of Object.values(switches)) paintSwitch(s);
}

function paintTile(inst) {
  if (!inst || inst.active === false) return;
  const provider = sampler.at(currentIndex);
  $UD.setBaseDataIcon(inst.context, tileDataUri({ provider, slot: inst.slot, theme: inst.theme }), '');
}

function paintSwitch(s) {
  if (!s || s.active === false) return;
  const provider = sampler.at(currentIndex);
  const iconPath = provider ? (MDI_LITE[provider.icon] || MDI_LITE.server || '') : '';
  $UD.setBaseDataIcon(s.context, switchTileDataUri({
    provider, iconPath, theme: s.theme,
    index: currentIndex, count: sampler.count(),
    offline: !sampler.ok,
  }), '');
}

// --- shutdown ----------------------------------------------------------------
function shutdown() { if (timer) clearInterval(timer); process.exit(0); }
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
