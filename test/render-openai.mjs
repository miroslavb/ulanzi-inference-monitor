import assert from 'node:assert/strict';
import { tileDataUri, switchTileDataUri } from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/render.js';

const decode = (uri) => Buffer.from(uri.split(',')[1], 'base64').toString('utf8');
const provider = {
  id: 'openai', name: 'OpenAI', kind: 'limit', icon: 'lightning-bolt', ok: true,
  plan: 'Pro', headline: 'Pro', session: null,
  week: { pct: 23, label: 'WEEK', resets_in: '5d 2h' },
};

const primary = decode(tileDataUri({ provider, slot: 'primary', theme: 'dark' }));
const secondary = decode(tileDataUri({ provider, slot: 'secondary', theme: 'dark' }));
const switchTile = decode(switchTileDataUri({ provider, theme: 'dark', index: 1, count: 5 }));

assert.match(primary, />Pro</);
assert.match(primary, />plan</);
assert.match(secondary, />WEEK</);
assert.match(secondary, />23%</);
assert.match(secondary, /5d 2h/);
assert.match(switchTile, />OpenAI</);
assert.match(switchTile, />23%</);
console.log('ok   OpenAI week-only tiles render plan + usage gauge');
