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
    providerIds: providers.length ? ProviderOrder.selected(providers, savedProviderIds) : savedProviderIds,
  };
}
function saveNow() { $UD.sendParamFromPlugin(buildSettings()); }
const saveDebounced = (typeof Utils !== 'undefined' && Utils.debounce) ? Utils.debounce(saveNow) : saveNow;

function renderProviders(message) {
  const list = document.querySelector('#providerList');
  if (!providers.length) {
    list.innerHTML = `<div class="provider-empty">${message || 'Connecting to the agent…'}</div>`;
    return;
  }
  const rows = ProviderOrder.rows(providers, savedProviderIds);
  const selectedCount = rows.filter((row) => row.selected).length;
  list.innerHTML = '';
  let section = '';
  for (const p of rows) {
    const nextSection = p.selected ? 'Cycle order' : 'Available providers';
    if (nextSection !== section) {
      const heading = document.createElement('div');
      heading.className = 'provider-section';
      heading.textContent = nextSection;
      list.append(heading);
      section = nextSection;
    }

    const row = document.createElement('div');
    row.className = 'provider-choice' + (p.selected ? ' selected' : ' available') + (p.ok === false ? ' offline' : '');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.id = 'provider-' + p.id.replace(/[^a-z0-9_-]/gi, '-');
    box.value = p.id;
    box.checked = p.selected;
    const label = document.createElement('label');
    label.htmlFor = box.id;
    const order = document.createElement('span');
    order.className = 'provider-order';
    order.textContent = p.selected ? String(p.order) + '.' : '+';
    const name = document.createElement('span');
    name.className = 'provider-name';
    name.textContent = p.name + (p.ok === false ? ' (unavailable)' : '');
    label.append(order, name);

    box.addEventListener('change', () => {
      savedProviderIds = ProviderOrder.toggle(providers, savedProviderIds, p.id, box.checked);
      renderProviders();
      saveNow();
    });

    const actions = document.createElement('div');
    actions.className = 'provider-actions';
    if (p.selected) {
      const up = document.createElement('button');
      up.type = 'button'; up.textContent = '↑'; up.title = 'Move ' + p.name + ' up';
      up.disabled = p.order === 1;
      up.addEventListener('click', () => {
        savedProviderIds = ProviderOrder.move(providers, savedProviderIds, p.id, -1);
        renderProviders(); saveNow();
      });
      const down = document.createElement('button');
      down.type = 'button'; down.textContent = '↓'; down.title = 'Move ' + p.name + ' down';
      down.disabled = p.order === selectedCount;
      down.addEventListener('click', () => {
        savedProviderIds = ProviderOrder.move(providers, savedProviderIds, p.id, 1);
        renderProviders(); saveNow();
      });
      actions.append(up, down);
    }
    // Keep input and label adjacent: uspi.css intentionally hides the native
    // checkbox and paints its visible state through `input + label`.
    row.append(box, label, actions);
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
  document.querySelector('#resetProviderOrder').addEventListener('click', () => {
    if (!providers.length) return;
    savedProviderIds = ProviderOrder.all(providers);
    renderProviders();
    saveNow();
  });
});

$UD.onAdd((jsn) => { if (jsn && jsn.param) load(jsn.param); });
$UD.onParamFromApp((jsn) => { if (jsn && jsn.param) load(jsn.param); });
$UD.onSendToPropertyInspector((jsn) => {
  const payload = (jsn && (jsn.payload || jsn.param)) || {};
  if (payload.type !== 'providers' || !Array.isArray(payload.providers)) return;
  providers = payload.providers.filter((p) => p && p.id).map((p) => ({ id: p.id, name: p.name || p.id, ok: p.ok !== false }));
  renderProviders();
});
