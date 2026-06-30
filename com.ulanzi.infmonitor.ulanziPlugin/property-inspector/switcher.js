// Property Inspector for the Provider Switch action.
// One agent serves all providers, so this only needs the agent address + display.

const DEFAULT_AGENT = 'http://127.0.0.1:9890';

function buildSettings() {
  return {
    agentUrl: (document.querySelector('#agentUrl').value || '').trim(),
    theme: document.querySelector('#theme').value === 'light' ? 'light' : 'dark',
    refresh: parseInt(document.querySelector('#refresh').value, 10) || 5000,
  };
}
function saveNow() { $UD.sendParamFromPlugin(buildSettings()); }
const saveDebounced = (typeof Utils !== 'undefined' && Utils.debounce) ? Utils.debounce(saveNow) : saveNow;

function load(p) {
  p = p || {};
  document.querySelector('#agentUrl').value = p.agentUrl || DEFAULT_AGENT;
  document.querySelector('#theme').value = p.theme === 'light' ? 'light' : 'dark';
  document.querySelector('#refresh').value = String(p.refresh || 5000);
}

$UD.connect();

$UD.onConnected(() => {
  document.querySelector('.uspi-wrapper').classList.remove('hidden');
  if (!document.querySelector('#agentUrl').value) document.querySelector('#agentUrl').value = DEFAULT_AGENT;
  document.querySelector('#agentUrl').addEventListener('input', saveDebounced);
  document.querySelector('#theme').addEventListener('change', saveNow);
  document.querySelector('#refresh').addEventListener('change', saveNow);
});

$UD.onAdd((jsn) => { if (jsn && jsn.param) load(jsn.param); });
$UD.onParamFromApp((jsn) => { if (jsn && jsn.param) load(jsn.param); });
