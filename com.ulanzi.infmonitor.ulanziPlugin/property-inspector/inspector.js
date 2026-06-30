// Property Inspector for the Provider Tile action.
// Picks a slot (primary / secondary), theme, refresh and the agent address.

const DEFAULT_AGENT = 'http://127.0.0.1:9890';

function buildSettings() {
  return {
    slot: document.querySelector('#slot').value === 'secondary' ? 'secondary' : 'primary',
    theme: document.querySelector('#theme').value === 'light' ? 'light' : 'dark',
    refresh: parseInt(document.querySelector('#refresh').value, 10) || 5000,
    agentUrl: (document.querySelector('#agentUrl').value || '').trim(),
  };
}
function saveNow() { $UD.sendParamFromPlugin(buildSettings()); }
const saveDebounced = (typeof Utils !== 'undefined' && Utils.debounce) ? Utils.debounce(saveNow) : saveNow;

function load(p) {
  p = p || {};
  document.querySelector('#slot').value = p.slot === 'secondary' ? 'secondary' : 'primary';
  document.querySelector('#theme').value = p.theme === 'light' ? 'light' : 'dark';
  document.querySelector('#refresh').value = String(p.refresh || 5000);
  document.querySelector('#agentUrl').value = p.agentUrl || DEFAULT_AGENT;
}

$UD.connect();

$UD.onConnected(() => {
  document.querySelector('.uspi-wrapper').classList.remove('hidden');
  if (!document.querySelector('#agentUrl').value) document.querySelector('#agentUrl').value = DEFAULT_AGENT;
  document.querySelector('#slot').addEventListener('change', saveNow);
  document.querySelector('#theme').addEventListener('change', saveNow);
  document.querySelector('#refresh').addEventListener('change', saveNow);
  document.querySelector('#agentUrl').addEventListener('input', saveDebounced);
});

$UD.onAdd((jsn) => { if (jsn && jsn.param) load(jsn.param); });
$UD.onParamFromApp((jsn) => { if (jsn && jsn.param) load(jsn.param); });
