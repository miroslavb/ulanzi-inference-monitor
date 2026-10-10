// Exercise the shipped Node app + SDK against a real Studio-shaped WS host.
// No Property Inspector is opened and no UI/input events are sent.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { WebSocketServer } from '../com.ulanzi.infmonitor.ulanziPlugin/node_modules/ws/wrapper.mjs';

const source = path.resolve('com.ulanzi.infmonitor.ulanziPlugin');
const scratch = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'inf-startup-'));
const plugin = path.join(scratch, 'plugin');
fs.cpSync(source, plugin, { recursive: true });
const persist = path.join(plugin, 'plugin/monitor/.agent-url.json');
let requests = 0;
const agent = http.createServer((req, res) => {
  requests++;
  res.setHeader('Content-Type', 'application/json');
  // Test fixture only, never represents measured provider/account data.
  res.end(JSON.stringify({ ts: Date.now(), providers: [{ id: 'fixture', name: 'Fixture', kind: 'limit', ok: true, session: { utilization: 0 }, week: { utilization: 0 } }] }));
});
agent.listen(0, '127.0.0.1');
await once(agent, 'listening');
const remote = `http://127.0.0.1:${agent.address().port}`;
const wss = new WebSocketServer({ host: '127.0.0.1', port: 0 });
await once(wss, 'listening');
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(fn, message, ms = 6000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return; await delay(25); }
  assert.fail(message);
}
const action = (suffix, id, key, param) => ({ uuid: `com.ulanzi.ulanzistudio.infmonitor.${suffix}`, actionid: id, key, ...(param === undefined ? {} : { param }) });
const switchAction = action('provswitch', 'switch', '0_1');
const tileAction = action('tile', 'tile', '2_1');
let child, socket, messages, errors;
async function start(saved, reply) {
  requests = 0; messages = []; errors = '';
  if (saved) fs.writeFileSync(persist, JSON.stringify({ agentUrl: saved }));
  else fs.rmSync(persist, { force: true });
  const connection = once(wss, 'connection');
  child = spawn(process.execPath, [path.join(plugin, 'plugin/app.js'), '127.0.0.1', String(wss.address().port), 'en-US'], { stdio: ['ignore', 'ignore', 'pipe'] });
  child.stderr.on('data', (d) => { errors += d; });
  [socket] = await connection;
  socket.on('message', (data) => {
    const m = JSON.parse(data); messages.push(m);
    if (m.cmd === 'getSettings' && reply) reply(m, socket);
  });
  await until(() => messages.some((m) => m.cmd === 'connected'), 'plugin must register');
}
async function stop() {
  if (child && child.exitCode === null) { const exited = once(child, 'exit'); child.kill(); await exited; }
  socket?.terminate();
}
function savedUrl() { try { return JSON.parse(fs.readFileSync(persist)).agentUrl; } catch { return ''; } }
try {
  // Observed profile: switch points to the actual agent; secondary tile has
  // the old localhost default. Restored action order must not decide the URL.
  await start(remote);
  socket.send(JSON.stringify({ cmd: 'add', ...switchAction, param: { agentUrl: remote, refresh: 2000 } }));
  socket.send(JSON.stringify({ cmd: 'add', ...tileAction, param: { agentUrl: 'http://127.0.0.1:9890', slot: 'secondary', refresh: 2000 } }));
  await until(() => messages.some((m) => m.cmd === 'state' && m.param?.statelist?.some((s) => s.actionid === 'tile')), 'restored tile must render');
  await delay(150);
  assert.equal(savedUrl(), remote, 'restored tile localhost must not overwrite the switch agent URL');
  requests = 0;
  await until(() => requests >= 2, 'polling must continue without PI focus');
  await stop();
  console.log('ok   switch URL survives stale tile URL and polls without PI');

  // A fresh process whose settings arrive only in the settings envelope.
  await start(null, (m, ws) => ws.send(JSON.stringify({ cmd: 'didReceiveSettings', uuid: m.uuid, key: m.key, actionid: m.actionid, param: {}, settings: { agentUrl: remote, refresh: 2000, providerIds: ['fixture'] } })));
  socket.send(JSON.stringify({ cmd: 'add', ...switchAction }));
  await until(() => requests > 0, 'settings envelope must recover agent address on cold start');
  assert.equal(savedUrl(), remote);
  assert.equal(messages.filter((m) => m.cmd === 'getSettings').length, 1, 'missing settings pull must remain bounded');
  await stop();
  console.log('ok   cold start hydrates settings reply without UI');

  // Standalone tiles still supply their own URL when no switch is placed.
  await start(null);
  socket.send(JSON.stringify({ cmd: 'add', ...tileAction, param: { agentUrl: remote, refresh: 2000, slot: 'secondary' } }));
  await until(() => requests > 0, 'standalone tile must keep working');
  assert.equal(savedUrl(), remote);
  await stop();
  console.log('ok   standalone tile remains supported');

  // If Studio restores empty parameters, the persisted URL remains usable.
  await start(remote);
  socket.send(JSON.stringify({ cmd: 'add', ...switchAction, param: {} }));
  socket.send(JSON.stringify({ cmd: 'add', ...tileAction, param: {} }));
  await until(() => requests > 0, 'persisted agent address must survive an empty restore');
  assert.equal(savedUrl(), remote);
  await stop();
  console.log('ok   persisted URL survives empty restored actions');
} finally {
  await stop();
  for (const ws of wss.clients) ws.terminate();
  await new Promise((resolve) => wss.close(resolve));
  await new Promise((resolve) => agent.close(resolve));
  fs.rmSync(scratch, { recursive: true, force: true });
}
