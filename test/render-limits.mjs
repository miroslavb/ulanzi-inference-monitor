import assert from 'node:assert/strict';
import { tileDataUri } from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/render.js';

function decode(uri) {
  return Buffer.from(uri.split(',')[1], 'base64').toString('utf8');
}

const ollama = {
  id: 'ollama_cloud', name: 'Ollama Cloud', kind: 'limit', icon: 'cloud', ok: true,
  session: { pct: 23.5, label: '5H' },
  week: { pct: 61, label: 'WEEK' },
};
const ollamaPrimary = decode(tileDataUri({ provider: ollama, slot: 'primary', theme: 'dark' }));
const ollamaSecondary = decode(tileDataUri({ provider: ollama, slot: 'secondary', theme: 'dark' }));
assert.match(ollamaPrimary, />5H</);
assert.match(ollamaPrimary, />24%</);
assert.doesNotMatch(ollamaPrimary, /↻/); // Ollama's endpoint does not provide reset timestamps.
assert.match(ollamaSecondary, />WEEK</);
assert.match(ollamaSecondary, />61%</);

const go = {
  id: 'opencode_go', name: 'OpenCode Go', kind: 'limit', icon: 'console', ok: true,
  month: { pct: 56.75, label: 'MONTH', resets_in: '2d 3h' },
};
const goMonth = decode(tileDataUri({ provider: go, slot: 'tertiary', theme: 'light' }));
assert.match(goMonth, />MONTH</);
assert.match(goMonth, />57%</);
assert.match(goMonth, /↻ 2d 3h/);
console.log('ok   Ollama and OpenCode Go limit gauges render without invented resets');
