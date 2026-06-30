// ProviderSampler.js — the single data source: the inf-agent over HTTP.
//
// Unlike sysmon (one source per host), here ONE agent returns ALL providers in
// one snapshot; the plugin selects which provider is "active". So we keep a
// single sampler that polls GET /providers and exposes `providers[]` + `byId`.
//
// The fetch is the same guaranteed-to-settle pattern as sysmon's RemoteSampler:
// an absolute deadline plus socket-error / mid-stream-abort / oversize handlers
// all funnel through one idempotent finish(), and a wedged in-flight poll is
// force-reset after 4× the timeout — so a stalled agent can never permanently
// freeze the source.

import http from 'http';
import https from 'https';

// Accept "100.x.y.z:9890", "host", "http://host:9890", "https://h/providers?token=..".
export function normalizeAgentUrl(raw) {
  let s = String(raw || '').trim();
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  let u;
  try { u = new URL(s); } catch { return ''; }
  if (!u.port && u.protocol === 'http:') u.port = '9890';   // default agent port
  if (!u.pathname || u.pathname === '/') u.pathname = '/providers';
  return u.toString();
}

export default class ProviderSampler {
  constructor(url, timeoutMs = 4000) {
    this.url = normalizeAgentUrl(url);
    this.timeoutMs = timeoutMs;
    this.providers = [];     // ordered list (cycle order = agent's ENABLED order)
    this.byId = {};
    this.agentHost = '';
    this.ts = 0;
    this.ok = false;
    this.lastError = null;
    this._inflight = false;
    this._inflightSince = 0;
  }

  setUrl(url) {
    const n = normalizeAgentUrl(url);
    if (n && n !== this.url) { this.url = n; this.ok = false; }
  }

  _get() {
    const timeoutMs = this.timeoutMs;
    return new Promise((resolve, reject) => {
      let settled = false, req = null;
      const finish = (err, val) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try { if (req) req.destroy(); } catch (e) {}
        if (err) reject(err); else resolve(val);
      };
      const timer = setTimeout(() => finish(new Error('timeout')), timeoutMs);
      let u;
      try { u = new URL(this.url); } catch (e) { return finish(new Error('bad url')); }
      const lib = u.protocol === 'https:' ? https : http;
      req = lib.get(u, (res) => {
        if (res.statusCode !== 200) { res.resume(); return finish(new Error('HTTP ' + res.statusCode)); }
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (c) => { body += c; if (body.length > 1e6) finish(new Error('too large')); });
        res.on('aborted', () => finish(new Error('response aborted')));
        res.on('error', (e) => finish(e));
        res.on('end', () => { try { finish(null, JSON.parse(body)); } catch (e) { finish(new Error('bad json')); } });
      });
      req.on('error', (e) => finish(e));
    });
  }

  // Never throws; on failure marks the source unreachable and keeps the last
  // good snapshot so tiles freeze rather than blank out.
  async sample() {
    if (!this.url) { this.ok = false; this.lastError = 'no agent url'; return; }
    if (this._inflight) {
      if (this._inflightSince && Date.now() - this._inflightSince > this.timeoutMs * 4) this._inflight = false;
      else return;
    }
    this._inflight = true;
    this._inflightSince = Date.now();
    try {
      const d = await this._get();
      if (d && Array.isArray(d.providers)) {
        this.providers = d.providers;
        this.byId = {};
        for (const p of d.providers) if (p && p.id) this.byId[p.id] = p;
        this.agentHost = d.agent_host || this.agentHost;
        this.ts = d.ts || Date.now();
      }
      this.ok = true;
      this.lastError = null;
    } catch (e) {
      this.ok = false;
      this.lastError = e.message || String(e);
    } finally {
      this._inflight = false;
    }
  }

  count() { return this.providers.length; }
  at(i) { const n = this.providers.length; return n ? this.providers[((i % n) + n) % n] : null; }
}
