import assert from 'node:assert/strict';
import { tileDataUri, switchTileDataUri } from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/render.js';

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
assert.doesNotMatch(ollamaPrimary, /↻/); // no invented reset when the window carries none.
assert.match(ollamaSecondary, />WEEK</);
assert.match(ollamaSecondary, />61%</);

// Credit-based Ollama plans (since 2026-08-31) arrive as a balance provider.
const ollamaCredits = {
  id: 'ollama_cloud', name: 'Ollama Cloud', kind: 'balance', icon: 'cloud', ok: true, currency: 'USD',
  session: null, week: null, balance: 59.93, allowance: 60, spend_today: 0.01, spend_week: 0.07,
  spend_month: 0.07, plan: 'Pro · $60/mo', headline: '$59.93',
  month: { pct: 0.1, label: 'MONTH', resets_in: '29d 17h' },
};
const creditsPrimary = decode(tileDataUri({ provider: ollamaCredits, slot: 'primary', theme: 'dark' }));
const creditsSecondary = decode(tileDataUri({ provider: ollamaCredits, slot: 'secondary', theme: 'dark' }));
const creditsMonth = decode(tileDataUri({ provider: ollamaCredits, slot: 'tertiary', theme: 'dark' }));
const creditsSwitch = decode(switchTileDataUri({ provider: ollamaCredits, theme: 'dark', index: 0, count: 2 }));
assert.match(creditsPrimary, />BALANCE</);
assert.match(creditsPrimary, />\$59\.93</);
assert.match(creditsPrimary, /Pro · \$60\/mo/);
assert.match(creditsSecondary, />SPEND</);
assert.match(creditsSecondary, />\$0\.01</);
assert.match(creditsSecondary, /\$0\.07 this week/);
assert.match(creditsMonth, />\$0\.07</);
assert.match(creditsSwitch, />\$59\.93</);

const go = {
  id: 'opencode_go', name: 'OpenCode Go', kind: 'limit', icon: 'console', ok: true,
  month: { pct: 56.75, label: 'MONTH', resets_in: '2d 3h' },
};
const goMonth = decode(tileDataUri({ provider: go, slot: 'tertiary', theme: 'light' }));
assert.match(goMonth, />MONTH</);
assert.match(goMonth, />57%</);
assert.match(goMonth, /↻ 2d 3h/);
console.log('ok   Ollama (legacy limits + credit balance) and OpenCode Go tiles render');
