#!/usr/bin/env python3
"""inf-agent — inference-provider limits/balance endpoint for the Ulanzi
Inference Monitor plugin.

Runs on the host that holds your provider credentials (here: the hermes NUC) and
serves ONE JSON snapshot describing every provider, so the Ulanzi plugin treats
it like a single data source (mirrors sysmon-agent's contract). The plugin's
Provider Switch key cycles through `providers[]`; two tiles render the active
provider — session/week for limit-providers, balance/last-usage for the rest.

Stdlib only (urllib/json/base64) — no pip installs.

Providers (auto-discovered from the box's credential files; override via env):
  * claude        — Anthropic OAuth usage  (5h session % + 7d week %, + resets)
  * openrouter    — /credits + /key         (balance + spend today/week/month)
  * nous          — portal JWT claims       (tier, spend, rate limits; free tier)
  * ollama_cloud  — POST /api/me            (plan + billing-period renewal)

Env (all optional — sane defaults for this box):
  INF_AGENT_PORT      listen port            (default 9890)
  INF_AGENT_BIND      bind address           (default 0.0.0.0; set the Tailscale IP to stay on the tailnet)
  INF_AGENT_TOKEN     shared secret          (?token=.. or Authorization: Bearer ..)
  INF_AGENT_INTERVAL  provider poll seconds  (default 60)
  INF_AGENT_PROVIDERS comma list to enable   (default claude,openrouter,nous,ollama_cloud)

  INF_CLAUDE_CREDS    path to Claude creds   (default /root/.claude/.credentials.json)
  INF_HERMES_ENV      path to hermes .env    (default /root/.hermes/.env)
  INF_HERMES_CONFIG   path to hermes config  (default /root/.hermes/config.yaml)
  INF_NOUS_PORTAL     path to nous portal js (default /root/.hermes/nous-portal.json)
  OPENROUTER_API_KEY / OLLAMA_API_KEY        explicit key overrides (win over file discovery)

Endpoints:
  GET /providers (or /)  -> { ts, agent_host, interval, providers:[ ... ] }
  GET /healthz           -> "ok"
"""
import base64
import json
import os
import re
import socket
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ---- config ----------------------------------------------------------------
PORT = int(os.environ.get("INF_AGENT_PORT", "9890"))
BIND = os.environ.get("INF_AGENT_BIND", "0.0.0.0")
TOKEN = os.environ.get("INF_AGENT_TOKEN", "")
INTERVAL = max(15, int(os.environ.get("INF_AGENT_INTERVAL", "60")))
ENABLED = [p.strip() for p in os.environ.get(
    "INF_AGENT_PROVIDERS", "claude,openrouter,nous,ollama_cloud").split(",") if p.strip()]

CLAUDE_CREDS = os.environ.get("INF_CLAUDE_CREDS", "/root/.claude/.credentials.json")
HERMES_ENV = os.environ.get("INF_HERMES_ENV", "/root/.hermes/.env")
HERMES_CONFIG = os.environ.get("INF_HERMES_CONFIG", "/root/.hermes/config.yaml")
NOUS_PORTAL = os.environ.get("INF_NOUS_PORTAL", "/root/.hermes/nous-portal.json")

UA = "ulanzi-inf-agent/1.0"
HTTP_TIMEOUT = 12

_snapshot = {"ts": 0, "agent_host": socket.gethostname(), "interval": INTERVAL, "providers": []}
_lock = threading.Lock()


# ---- helpers ---------------------------------------------------------------
def _http(method, url, headers=None, body=None):
    """Return parsed-JSON (dict/list) for a request, raising on non-2xx."""
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw else {}


def _env_value(path, key):
    """Pluck KEY=value out of a dotenv file (last non-empty wins)."""
    val = ""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    v = line[len(key) + 1:].strip().strip('"').strip("'")
                    if v:
                        val = v
    except OSError:
        pass
    return val


def _yaml_value(path, *key_path):
    """Best-effort nested scalar read from a YAML file.

    Uses PyYAML when present, else a minimal indentation walk for the requested
    dotted key path (e.g. providers -> ollama_cloud -> api_key). Stdlib-safe."""
    try:
        import yaml  # available on the NUC; optional elsewhere
        d = yaml.safe_load(open(path))
        for k in key_path:
            d = d[k]
        return str(d)
    except Exception:
        pass
    # Fallback: indentation-aware scan for the exact key chain.
    try:
        want = list(key_path)
        depth = 0
        with open(path) as f:
            for line in f:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                m = re.match(r"\s*([A-Za-z0-9_.-]+):\s*(.*)$", line)
                if not m:
                    continue
                k, v = m.group(1), m.group(2).strip()
                if depth < len(want) and k == want[depth]:
                    if depth == len(want) - 1:
                        return v.strip('"').strip("'")
                    depth += 1
    except OSError:
        pass
    return ""


def _iso_to_dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _resets_in(iso):
    """Human 'in 4h 12m' / 'in 5d' until an ISO timestamp, or None."""
    dt = _iso_to_dt(iso)
    if not dt:
        return None
    secs = (dt - datetime.now(timezone.utc)).total_seconds()
    if secs <= 0:
        return "now"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    mnt = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {mnt}m"
    return f"{mnt}m"


# ---- provider probes -------------------------------------------------------
def probe_claude():
    p = {"id": "claude", "name": "Claude", "kind": "limit", "icon": "robot", "ok": False}
    try:
        creds = json.load(open(CLAUDE_CREDS))["claudeAiOauth"]
        tok = creds["accessToken"]
        p["plan"] = {"max": "Max", "pro": "Pro"}.get(
            str(creds.get("subscriptionType", "")).lower(), creds.get("subscriptionType") or "")
    except Exception as e:
        p["error"] = f"creds: {e}"
        return p
    hdr = {"Authorization": "Bearer " + tok, "anthropic-beta": "oauth-2025-04-20"}
    try:
        prof = _http("GET", "https://api.anthropic.com/api/oauth/profile", hdr)
        tier = (prof.get("organization") or {}).get("rate_limit_tier", "")
        m = re.search(r"max_(\d+)x", str(tier))  # "default_claude_max_20x" -> "Max 20x"
        if m:
            p["headline"] = f"Max {m.group(1)}x"
    except Exception:
        pass
    try:
        u = _http("GET", "https://api.anthropic.com/api/oauth/usage", hdr)
    except urllib.error.HTTPError as e:
        p["error"] = f"usage HTTP {e.code} (token may need refresh)"
        return p
    except Exception as e:
        p["error"] = f"usage: {e}"
        return p

    def block(key):
        b = u.get(key) or {}
        if not isinstance(b, dict) or b.get("utilization") is None:
            return None
        return {"pct": round(float(b.get("utilization") or 0), 1),
                "resets_at": b.get("resets_at"),
                "resets_in": _resets_in(b.get("resets_at"))}

    p["session"] = block("five_hour")
    p["week"] = block("seven_day")
    detail = {}
    for k, lbl in (("seven_day_opus", "opus"), ("seven_day_sonnet", "sonnet")):
        b = u.get(k)
        if isinstance(b, dict) and b.get("utilization") is not None:
            detail[lbl] = round(float(b["utilization"]), 1)
    if detail:
        p["detail"] = detail
    if not p.get("headline"):
        p["headline"] = p.get("plan") or "Claude"
    p["ok"] = True
    return p


def probe_openrouter():
    p = {"id": "openrouter", "name": "OpenRouter", "kind": "balance", "icon": "swap-horizontal",
         "currency": "USD", "ok": False}
    key = os.environ.get("OPENROUTER_API_KEY", "") or _env_value(HERMES_ENV, "OPENROUTER_API_KEY")
    if not key:
        p["error"] = "no OPENROUTER_API_KEY"
        return p
    hdr = {"Authorization": "Bearer " + key}
    try:
        cr = (_http("GET", "https://openrouter.ai/api/v1/credits", hdr) or {}).get("data", {})
        kd = (_http("GET", "https://openrouter.ai/api/v1/key", hdr) or {}).get("data", {})
    except Exception as e:
        p["error"] = f"{e}"
        return p
    total, used = cr.get("total_credits"), cr.get("total_usage")
    if total is not None and used is not None:
        p["balance"] = round(float(total) - float(used), 2)
    p["spend_today"] = round(float(kd.get("usage_daily") or 0), 4)
    p["spend_week"] = round(float(kd.get("usage_weekly") or 0), 4)
    p["spend_month"] = round(float(kd.get("usage_monthly") or 0), 4)
    p["headline"] = (f"${p['balance']:.2f}" if "balance" in p else "OpenRouter")
    p["ok"] = True
    return p


def probe_nous():
    p = {"id": "nous", "name": "Nous", "kind": "balance", "icon": "chip",
         "currency": "USD", "ok": False}
    try:
        tok = json.load(open(NOUS_PORTAL))["access_token"]
        seg = tok.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        c = json.loads(base64.urlsafe_b64decode(seg))
    except Exception as e:
        p["error"] = f"portal token: {e}"
        return p
    try:
        spend = float(c.get("member_spend_usd") or 0)
    except (TypeError, ValueError):
        spend = 0.0
    cap = c.get("member_spend_cap_usd")
    free = not bool(c.get("paid_access"))
    p["free"] = free
    p["tier"] = c.get("subscription_tier")
    p["spend_total"] = round(spend, 4)
    if cap not in (None, ""):
        try:
            p["balance"] = round(float(cap) - spend, 2)
        except (TypeError, ValueError):
            pass
    p["rate"] = {"rpm": c.get("rate_limit_rpm"), "tpm": c.get("rate_limit_tpm"),
                 "rph": c.get("rate_limit_rph"), "tph": c.get("rate_limit_tph")}
    p["token_age_min"] = round((time.time() - float(c["iat"])) / 60, 1) if c.get("iat") else None
    if "balance" in p:
        p["headline"] = f"${p['balance']:.2f}"
    elif free:
        p["headline"] = f"Free T{p['tier']}" if p.get("tier") is not None else "Free"
    else:
        p["headline"] = f"${spend:.2f} spent"
    p["ok"] = True
    return p


def probe_ollama_cloud():
    p = {"id": "ollama_cloud", "name": "Ollama Cloud", "kind": "limit", "icon": "cloud",
         "ok": False, "note": "no per-window usage API — plan & renewal only"}
    key = os.environ.get("OLLAMA_API_KEY", "") or _env_value(HERMES_ENV, "OLLAMA_API_KEY") \
        or _yaml_value(HERMES_CONFIG, "providers", "ollama_cloud", "api_key")
    if not key:
        p["error"] = "no OLLAMA_API_KEY"
        return p
    try:
        me = _http("POST", "https://ollama.com/api/me", {"Authorization": "Bearer " + key})
    except Exception as e:
        p["error"] = f"{e}"
        return p
    plan = me.get("Plan") or ""
    p["plan"] = plan
    p["headline"] = plan.upper() if plan else "Ollama"
    p["session"] = None  # not exposed by any Ollama API → tiles fall back to plan/renewal
    p["week"] = None
    end = (me.get("SubscriptionPeriodEnd") or {})
    if end.get("Valid") and end.get("Time"):
        p["renews_at"] = end["Time"]
        p["renews_in"] = _resets_in(end["Time"])
    if (me.get("SuspendedAt") or {}).get("Valid"):
        p["suspended"] = True
    p["ok"] = True
    return p


PROBES = {
    "claude": probe_claude,
    "openrouter": probe_openrouter,
    "nous": probe_nous,
    "ollama_cloud": probe_ollama_cloud,
}


def collect():
    out = []
    for pid in ENABLED:
        fn = PROBES.get(pid)
        if not fn:
            continue
        try:
            out.append(fn())
        except Exception as e:  # a probe must never take down the loop
            out.append({"id": pid, "name": pid, "kind": "balance", "ok": False, "error": str(e)})
    return out


def _refresh_loop():
    while True:
        providers = collect()
        with _lock:
            _snapshot["ts"] = int(time.time() * 1000)
            _snapshot["providers"] = providers
        time.sleep(INTERVAL)


# ---- http ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _authed(self, q):
        if not TOKEN:
            return True
        if q.get("token", [None])[0] == TOKEN:
            return True
        return self.headers.get("Authorization", "") == "Bearer " + TOKEN

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/healthz":
            return self._send(200, "ok", "text/plain")
        if u.path in ("/providers", "/"):
            if not self._authed(parse_qs(u.query)):
                return self._send(401, json.dumps({"error": "unauthorized"}))
            with _lock:
                snap = dict(_snapshot)
            return self._send(200, json.dumps(snap))
        self._send(404, json.dumps({"error": "not found"}))


def main():
    # Prime the snapshot synchronously so the first plugin poll has data.
    with _lock:
        _snapshot["ts"] = int(time.time() * 1000)
        _snapshot["providers"] = collect()
    threading.Thread(target=_refresh_loop, daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"[inf-agent] listening on {BIND}:{PORT} "
          f"providers={','.join(ENABLED)} interval={INTERVAL}s"
          + (" (token required)" if TOKEN else ""), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
