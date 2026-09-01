import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL(
  '../com.ulanzi.infmonitor.ulanziPlugin/property-inspector/provider-order.js',
  import.meta.url,
), 'utf8');
const context = { console };
context.globalThis = context;
vm.runInNewContext(source, context, { filename: 'provider-order.js' });
const order = context.ProviderOrder;
assert.ok(order, 'provider-order.js exposes ProviderOrder to the Property Inspector');

const providers = [
  { id: 'claude', name: 'Claude' },
  { id: 'openai', name: 'OpenAI' },
  { id: 'ollama_cloud', name: 'Ollama Cloud' },
  { id: 'opencode_go', name: 'OpenCode Go' },
];

// Selected rows use saved order. Any provider omitted by a previous allow-list,
// including OpenAI, remains visible in the available section so it can be restored.
assert.deepEqual(
  Array.from(order.rows(providers, ['opencode_go', 'claude']), (row) => [row.id, row.selected]),
  [['opencode_go', true], ['claude', true], ['openai', false], ['ollama_cloud', false]],
);

assert.deepEqual(Array.from(order.move(providers, ['opencode_go', 'openai', 'claude'], 'openai', -1)),
  ['openai', 'opencode_go', 'claude']);
assert.deepEqual(Array.from(order.move(providers, ['opencode_go', 'openai', 'claude'], 'openai', 1)),
  ['opencode_go', 'claude', 'openai']);
assert.deepEqual(Array.from(order.move(providers, ['opencode_go', 'openai', 'claude'], 'opencode_go', -1)),
  ['opencode_go', 'openai', 'claude']);

assert.deepEqual(Array.from(order.toggle(providers, ['opencode_go', 'claude'], 'openai', true)),
  ['opencode_go', 'claude', 'openai']);
assert.deepEqual(Array.from(order.toggle(providers, ['opencode_go', 'openai'], 'opencode_go', false)),
  ['openai']);
assert.deepEqual(Array.from(order.toggle(providers, ['openai'], 'openai', false)),
  ['openai'], 'the switch must retain at least one provider');
assert.deepEqual(Array.from(order.all(providers)), ['claude', 'openai', 'ollama_cloud', 'opencode_go']);

console.log('ok   provider editor adds, removes and reorders providers while keeping OpenAI recoverable');