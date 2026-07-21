// render.js — inference-provider tiles as SVG (pure string templating, no deps).
//
// Two tile shapes, picked from the active provider's `kind`:
//   * limit   (claude, openai, ollama_cloud) — a ring gauge of % utilisation, with the
//     reset countdown beneath. Primary slot = session (5h), secondary = week (7d).
//     When a window has no live %, the ring is replaced by a plan/renewal card.
//   * balance (openrouter, nous)     — a value card. Primary slot = balance,
//     secondary slot = spend today/week (or rate limits for a free tier).
//
// Plus the Provider Switch key (switchTileDataUri): the active provider's icon,
// name and headline value, with an accent ring and an offline dot.

export const CELL = 100;

export const THEMES = {
  dark:  { bg: '#1b1b1b', grid: '#333333', text: '#e8e8e8', sub: '#9aa0a6', track: '#3a3a3a', chip: 'rgba(0,0,0,0.45)' },
  light: { bg: '#f6f6f6', grid: '#d6d6d6', text: '#1b1b1b', sub: '#5f6368', track: '#d6d6d6', chip: 'rgba(255,255,255,0.55)' },
};

const ACCENT = '#17a2d6';
const GOOD = '#3fb950', WARN = '#e0a23a', BAD = '#e2504a';
const FAM = "font-family=\"'Segoe UI','Source Han Sans SC',sans-serif\"";

function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function truncate(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

// Utilisation colour: calm until ~60%, amber to ~85%, red past it.
function utilColor(pct) { return pct >= 85 ? BAD : (pct >= 60 ? WARN : GOOD); }

// Compact a big integer: 500000 -> "500k", 6000000 -> "6M".
export function compact(n) {
  n = Number(n);
  if (!isFinite(n)) return '–';
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, '') + 'B';
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'k';
  return String(n);
}
function money(v) {
  const n = Number(v);
  if (!isFinite(n)) return '–';
  if (Math.abs(n) >= 1000) return '$' + compact(n);
  return '$' + n.toFixed(2);
}

function svg(inner, C) {
  C = C || CELL;
  return 'data:image/svg+xml;base64,' + Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${C}" height="${C}" viewBox="0 0 ${C} ${C}">${inner}</svg>`
  ).toString('base64');
}

// Centred category header (SESSION / WEEK / BALANCE / SPEND / RATE). The provider
// identity is owned by the adjacent Provider Switch key, so tiles stay legible at
// 100px and never collide a long provider name with the label.
function header(t, label) {
  return `<text x="50" y="14" text-anchor="middle" ${FAM} font-size="11" font-weight="700" letter-spacing="1" fill="${ACCENT}">${esc(label)}</text>`;
}

// Point on a circle at `deg` (0°=3 o'clock, +ve clockwise in SVG's y-down space).
function polar(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

// Centred ring gauge (0..100) with the value drawn in the middle.
//
// The progress arc is an explicit `<path … A …>` (NOT stroke-dasharray): the
// D200H's SVG renderer ignores `pathLength`, so a normalised dasharray was being
// read in real user units and tiled into a SECOND spurious arc segment. An arc
// path has one definite start/end, so it renders identically everywhere.
function ring(t, pct, centerText, centerColor, cy) {
  cy = cy || 56;
  const r = 29, sw = 8, len = Math.max(0, Math.min(100, pct));
  const col = centerColor || utilColor(len);
  const track = `<circle cx="50" cy="${cy}" r="${r}" fill="none" stroke="${t.track}" stroke-width="${sw}"/>`;
  let prog = '';
  if (len >= 99.95) {
    prog = `<circle cx="50" cy="${cy}" r="${r}" fill="none" stroke="${col}" stroke-width="${sw}"/>`;
  } else if (len > 0) {
    const sweep = (len / 100) * 360;                 // clockwise from 12 o'clock
    const [x0, y0] = polar(50, cy, r, -90);
    const [x1, y1] = polar(50, cy, r, -90 + sweep);
    const large = sweep > 180 ? 1 : 0;
    prog = `<path d="M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}" ` +
      `fill="none" stroke="${col}" stroke-width="${sw}" stroke-linecap="round"/>`;
  }
  return track + prog +
    `<text x="50" y="${cy + 6}" text-anchor="middle" ${FAM} font-size="22" font-weight="800" fill="${col}">${esc(centerText)}</text>`;
}

// Big centred value with a small caption beneath it (value-card tiles).
function valueCard(t, big, sub, color, bigSize) {
  const fs = bigSize || (String(big).length > 6 ? 21 : 27);
  let s = `<text x="50" y="60" text-anchor="middle" ${FAM} font-size="${fs}" font-weight="800" fill="${color || t.text}">${esc(big)}</text>`;
  if (sub) s += `<text x="50" y="84" text-anchor="middle" ${FAM} font-size="12" fill="${t.sub}">${esc(sub)}</text>`;
  return s;
}

function bottomNote(t, txt, color) {
  return `<text x="50" y="93" text-anchor="middle" ${FAM} font-size="10" fill="${color || t.sub}">${esc(txt)}</text>`;
}

/**
 * Render one metric tile for the active provider.
 * @param {object} o  { provider, slot:'primary'|'secondary', theme }
 */
export function tileDataUri(o) {
  const t = THEMES[o.theme] || THEMES.dark;
  const bg = `<rect x="0" y="0" width="${CELL}" height="${CELL}" fill="${t.bg}"/>`;
  const frame = `<rect x="0.5" y="0.5" width="${CELL - 1}" height="${CELL - 1}" rx="6" fill="none" stroke="${t.grid}" stroke-width="1"/>`;
  const p = o.provider;
  const slot = o.slot === 'secondary' ? 'secondary' : 'primary';

  if (!p) {
    return svg(bg + header(t, 'INFERENCE') + valueCard(t, '…', 'connecting', t.sub, 22) + frame);
  }
  if (p.ok === false) {
    return svg(bg + header(t, truncate((p.name || p.id).toUpperCase(), 12)) +
      valueCard(t, '⚠', truncate(p.error || 'offline', 13), BAD, 24) + frame);
  }

  if (p.kind === 'limit') return svg(bg + limitTile(t, p, slot) + frame);
  return svg(bg + balanceTile(t, p, slot) + frame);
}

function limitTile(t, p, slot) {
  const win = slot === 'primary' ? p.session : p.week;
  const label = (win && win.label) || (slot === 'primary' ? 'SESSION' : 'WEEK');
  let s = header(t, label);
  if (win && typeof win.pct === 'number') {
    s += ring(t, win.pct, Math.round(win.pct) + '%');
    s += bottomNote(t, '↻ ' + (win.resets_in || ''));
  } else {
    // No live window (e.g. Ollama has no usage API): show plan + renewal instead.
    const head = slot === 'primary' ? (p.headline || p.plan || '—') : (p.renews_in ? 'in ' + p.renews_in : '—');
    const sub = slot === 'primary' ? 'plan' : 'renews';
    s += valueCard(t, head, sub, t.text);
  }
  return s;
}

function balanceTile(t, p, slot) {
  if (slot === 'primary') {
    // Balance / credit headline. Show the plan as the caption when known.
    let big, sub, color = t.text;
    if (typeof p.balance === 'number') { big = money(p.balance); sub = p.plan || 'balance'; color = p.balance <= 0 ? BAD : t.text; }
    else if (p.free) { big = 'FREE'; sub = p.tier != null ? 'tier ' + p.tier : 'free tier'; color = GOOD; }
    else if (p.plan) { big = p.plan; sub = 'plan'; }
    else { big = '—'; sub = truncate(p.name || '', 12); color = t.sub; }
    return header(t, 'BALANCE') + valueCard(t, big, sub, color);
  }
  // Secondary: spend today/week, or rate limits for a free provider with no $.
  if (typeof p.spend_today === 'number' || typeof p.spend_week === 'number') {
    const today = money(p.spend_today || 0), wk = money(p.spend_week || 0);
    return header(t, 'SPEND') +
      `<text x="50" y="50" text-anchor="middle" ${FAM} font-size="24" font-weight="800" fill="${t.text}">${esc(today)}</text>` +
      `<text x="50" y="66" text-anchor="middle" ${FAM} font-size="10" fill="${t.sub}">today</text>` +
      bottomNote(t, wk + ' this week');
  }
  if (p.rate && (p.rate.rpm != null || p.rate.tpm != null)) {
    return header(t, 'RATE') +
      `<text x="50" y="50" text-anchor="middle" ${FAM} font-size="23" font-weight="800" fill="${t.text}">${esc(compact(p.rate.rpm))}</text>` +
      `<text x="50" y="66" text-anchor="middle" ${FAM} font-size="10" fill="${t.sub}">req / min</text>` +
      bottomNote(t, compact(p.rate.tpm) + ' tok/min');
  }
  return header(t, 'SPEND') + valueCard(t, money(p.spend_total || 0), 'to date', t.text);
}

/**
 * Render the Provider Switch key for the currently-selected provider.
 * @param {object} o
 *   provider   active provider object (or null while connecting)
 *   theme      'dark' | 'light'
 *   index,count position in the cycle (shows "2/4")
 *   offline    agent unreachable (red dot)
 */
export function switchTileDataUri(o) {
  const C = CELL;
  const t = THEMES[o.theme] || THEMES.dark;
  const p = o.provider;
  const bg = `<rect x="0" y="0" width="${C}" height="${C}" fill="${t.bg}"/>`;
  const ringFrame = `<rect x="2.5" y="2.5" width="${C - 5}" height="${C - 5}" rx="10" fill="none" stroke="${ACCENT}" stroke-width="3"/>`;

  if (!p) {
    return svg(bg + ringFrame +
      `<text x="${C / 2}" y="${C / 2 + 4}" text-anchor="middle" ${FAM} font-size="13" fill="${t.sub}">${o.offline ? 'agent off' : '…'}</text>`);
  }

  // MDI 24x24 glyph, scaled to ~42px near the top.
  const iconPath = o.iconPath || '';
  const size = 42, scale = size / 24, ix = (C - size) / 2, iy = 12;
  const icon = iconPath ? `<g transform="translate(${ix},${iy}) scale(${scale})"><path d="${iconPath}" fill="${t.text}"/></g>` : '';

  const name = `<text x="${C / 2}" y="72" text-anchor="middle" ${FAM} font-size="14" font-weight="800" fill="${t.text}">${esc(truncate(p.name, 12))}</text>`;

  // Headline: live %, balance or plan — colour the limit % by load.
  let head = p.headline || '', headColor = ACCENT;
  const activeWindow = p.kind === 'limit' && (p.session || p.week);
  if (activeWindow && typeof activeWindow.pct === 'number') {
    head = Math.round(activeWindow.pct) + '%';
    headColor = utilColor(activeWindow.pct);
  }
  const headline = head ? `<text x="${C / 2}" y="90" text-anchor="middle" ${FAM} font-size="13" font-weight="700" fill="${headColor}">${esc(truncate(head, 12))}</text>` : '';

  // Cycle position, top-left; status dot, top-right (red = offline/error, amber = stale).
  const idx = (o.count > 1) ? `<text x="6" y="14" ${FAM} font-size="10" font-weight="700" fill="${t.sub}">${(o.index | 0) + 1}/${o.count}</text>` : '';
  let corner = '';
  if (o.offline || p.ok === false) corner = `<circle cx="${C - 12}" cy="12" r="5" fill="${BAD}"/>`;
  else if (p.stale) corner = `<circle cx="${C - 12}" cy="12" r="5" fill="${WARN}"/>`;

  return svg(bg + ringFrame + icon + name + headline + idx + corner);
}
