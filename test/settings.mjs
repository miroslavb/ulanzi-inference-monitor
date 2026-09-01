import assert from 'node:assert/strict';
import {
  readSwitchSettings, readTileSettings, visibleProviders, nextProviderId,
} from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/settings.js';

const providers = [
  { id: 'claude', name: 'Claude' },
  { id: 'ollama_cloud', name: 'Ollama Cloud' },
  { id: 'opencode_go', name: 'OpenCode Go' },
];

// Existing persisted switch settings have no allow-list and must keep cycling all.
assert.equal(readSwitchSettings({}).providerIds, null);
assert.deepEqual(visibleProviders(providers, null).map((p) => p.id),
  ['claude', 'ollama_cloud', 'opencode_go']);

const settings = readSwitchSettings({ providerIds: [' opencode_go ', 'claude', 'claude', '', 5] });
assert.deepEqual(settings.providerIds, ['opencode_go', 'claude']);
assert.deepEqual(visibleProviders(providers, settings.providerIds).map((p) => p.id),
  ['claude', 'opencode_go']);
assert.equal(nextProviderId(visibleProviders(providers, settings.providerIds), null), 'claude');
assert.equal(nextProviderId(visibleProviders(providers, settings.providerIds), 'claude'), 'opencode_go');
assert.equal(nextProviderId(visibleProviders(providers, settings.providerIds), 'opencode_go'), 'claude');

assert.equal(readTileSettings({ slot: 'tertiary' }).slot, 'tertiary');
console.log('ok   provider selection filters in agent order and monthly tile settings survive');
