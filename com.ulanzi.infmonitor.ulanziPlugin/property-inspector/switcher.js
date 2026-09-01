// Property Inspector for the Provider Switch action. Provider choices arrive
// from the plugin's sampler and are also refreshed directly for immediate setup.

const DEFAULT_AGENT = 'http://127.0.0.1:9890';
let savedProviderIds = null; // null = all providers (backward compatible)
let providers = [];
let providerFetchTimer = null;

function buildSettings() {
  return {
    agentUrl: (document.querySelector('#agentUrl').value || '').trim(),
    theme: document.querySelector('#theme').value === 'light' ? 'light' : 'dark',
    refresh: parseInt(document.querySelector('#refresh').value, 10) || 5000,
    // Do not turn old/all-provider settings into an empty allow-list before the
    // agent list has arrived.
    providerIds: providers.length
      ? [...document.querySelectorAll('#providerList input:checked')].map((el) => el.value)
      : savedProviderIds,
  };
}
function saveNow() { $UD.sendParamFromPlugin(buildSettings()); }
const saveDebounced = (typeof Utils !== 'undefined' && Utils.debounce) ? Utils.debounce(saveNow) : saveNow;

function selectedProviderIds() {
  return Array.isArray(savedProviderIds) ? new Set(savedProviderIds) : new Set(providers.map((p) => p.id));
}

function renderProviders(message) {
  const list = document.querySelector('#providerList');
  if (!providers.length) {
    list.innerHTML = `<div class="provider-empty">${message || 'Connecting to the agent…'}</div>`;
    return;
  }
  const selected = selectedProviderIds();
  list.innerHTML = '';
  for (const p of providers) {
    const row = document.createElement('label');
    row.className = 'provider-choice' + (p.ok === false ? ' offline' : '');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.value = p.id;
    box.checked = selected.has(p.id);
    box.addEventListener('change', () => {
      // A switch with no choices cannot select a provider, so keep one selected.
      if (![...list.querySelectorAll('input:checked')].length) box.checked = true;
      savedProviderIds = [...list.querySelectorAll('input:checked')].map((el) => el.value);
      saveNow();
    });
    row.append(box, document.createTextNode(p.name + (p.ok === false ? ' (unavailable)' : '')));
    list.append(row);
  }
}

function providersUrl(value) {
  let raw = String(value || '').trim();
  if (!raw) return null;
  if (!/^https?:\/\//i.test(raw)) raw = 'http://' + raw;
  const url = new URL(raw);
  if (!url.pathname || url.pathname === '/') url.pathname = '/providers';
  return url.toString();
}

async function refreshProviderChoices() {
  let url;
  try { url = providersUrl(document.querySelector('#agentUrl').value); } catch (e) { renderProviders('Enter a valid agent address.'); return; }
  if (!url) return;
  try {
    const response = await fetch(url, { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || !Array.isArray(data.providers)) throw new Error('agent response has no providers');
    providers = data.providers.filter((p) => p && p.id).map((p) => ({ id: p.id, name: p.name || p.id, ok: p.ok !== false }));
    renderProviders();
  } catch (e) {
    if (!providers.length) renderProviders('Could not load providers — the plugin will retry.');
  }
}

function scheduleProviderRefresh() {
  clearTimeout(providerFetchTimer);
  providerFetchTimer = setTimeout(refreshProviderChoices, 250);
}

function load(p) {
  p = p || {};
  savedProviderIds = Array.isArray(p.providerIds) ? p.providerIds.filter((id) => typeof id === 'string' && id) : null;
  document.querySelector('#agentUrl').value = p.agentUrl || DEFAULT_AGENT;
  document.querySelector('#theme').value = p.theme === 'light' ? 'light' : 'dark';
  document.querySelector('#refresh').value = String(p.refresh || 5000);
  renderProviders();
  scheduleProviderRefresh();
}

$UD.connect();

$UD.onConnected(() => {
  document.querySelector('.uspi-wrapper').classList.remove('hidden');
  if (!document.querySelector('#agentUrl').value) document.querySelector('#agentUrl').value = DEFAULT_AGENT;
  scheduleProviderRefresh();
  document.querySelector('#agentUrl').addEventListener('input', () => { saveDebounced(); scheduleProviderRefresh(); });
  document.querySelector('#theme').addEventListener('change', saveNow);
  document.querySelector('#refresh').addEventListener('change', saveNow);
});

$UD.onAdd((jsn) => { if (jsn && jsn.param) load(jsn.param); });
$UD.onParamFromApp((jsn) => { if (jsn && jsn.param) load(jsn.param); });
$UD.onSendToPropertyInspector((jsn) => {
  const payload = (jsn && (jsn.payload || jsn.param)) || {};
  if (payload.type !== 'providers' || !Array.isArray(payload.providers)) return;
  providers = payload.providers.filter((p) => p && p.id).map((p) => ({ id: p.id, name: p.name || p.id, ok: p.ok !== false }));
  renderProviders();
});
