// End-to-end check: drive the real ProviderSampler + render modules against a
// live inf-agent, assert the tile contents, and write a visual preview.html.
//
// Usage: INF_URL=http://127.0.0.1:9899 node test/preview.mjs
import { writeFileSync } from 'fs';
import ProviderSampler from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/ProviderSampler.js';
import { tileDataUri, switchTileDataUri } from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/render.js';
import { MDI_LITE } from '../com.ulanzi.infmonitor.ulanziPlugin/plugin/monitor/mdi-lite.js';

const URL = process.env.INF_URL || 'http://127.0.0.1:9899';
const decode = (uri) => Buffer.from(uri.split(',')[1], 'base64').toString('utf8');

let failures = 0;
function check(cond, msg) { console.log((cond ? 'ok   ' : 'FAIL ') + msg); if (!cond) failures++; }

const s = new ProviderSampler(URL);
await s.sample();

check(s.ok, `sampler reachable (${URL})`);
check(s.count() === 4, `4 providers (got ${s.count()}: ${s.providers.map(p => p.id).join(',')})`);

const cards = [];
for (let i = 0; i < s.count(); i++) {
  const p = s.at(i);
  const iconPath = MDI_LITE[p.icon] || MDI_LITE.server || '';
  const sw = switchTileDataUri({ provider: p, iconPath, theme: 'dark', index: i, count: s.count(), offline: false });
  const a = tileDataUri({ provider: p, slot: 'primary', theme: 'dark' });
  const b = tileDataUri({ provider: p, slot: 'secondary', theme: 'dark' });

  for (const [lbl, uri] of [['switch', sw], ['primary', a], ['secondary', b]]) {
    check(uri.startsWith('data:image/svg+xml;base64,'), `${p.id} ${lbl} is an SVG data-uri`);
  }
  check(decode(sw).includes(p.name), `${p.id} switch tile shows the name`);

  // Per-kind content assertions.
  const ap = decode(a), bp = decode(b);
  if (p.kind === 'limit' && p.session) {
    check(ap.includes('SESSION') && ap.includes('%'), `${p.id} primary = session %`);
    check(bp.includes('WEEK'), `${p.id} secondary = week`);
  } else if (p.kind === 'limit') {
    check(ap.includes('plan') || ap.includes(p.headline || '###'), `${p.id} primary = plan fallback`);
  } else if (p.kind === 'balance') {
    check(/\$|FREE/.test(ap), `${p.id} primary = balance/free`);
    check(bp.includes('SPEND') || bp.includes('RATE'), `${p.id} secondary = spend/rate`);
  }

  cards.push({ id: p.id, name: p.name, sw, a, b });
}

// Visual preview (open in a browser).
const cell = (uri, cap) =>
  `<figure><img src="${uri}" width="100" height="100" style="image-rendering:auto;border:1px solid #333;border-radius:6px"><figcaption>${cap}</figcaption></figure>`;
const rows = cards.map(c =>
  `<div class="row"><h3>${c.name}</h3><div class="tiles">${cell(c.sw, 'switch')}${cell(c.a, 'primary')}${cell(c.b, 'secondary')}</div></div>`
).join('\n');
const html = `<!doctype html><meta charset="utf-8"><title>Inference Monitor preview</title>
<style>body{background:#111;color:#ddd;font:14px system-ui;padding:20px}
.row{margin:18px 0}.tiles{display:flex;gap:14px}figure{margin:0;text-align:center}
figcaption{font-size:11px;color:#888;margin-top:4px}h3{color:#17a2d6;margin:0 0 8px}</style>
<h1>Inference Monitor — live tile preview</h1><p>Press the switch key to cycle; tiles follow the active provider.</p>${rows}`;
const out = new global.URL('./preview.html', import.meta.url).pathname;
writeFileSync(out, html);
console.log(`\npreview written: ${out}`);
console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nALL CHECKS PASSED');
process.exit(failures ? 1 : 0);
