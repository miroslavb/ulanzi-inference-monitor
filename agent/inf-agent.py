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
  * openai        — Codex ChatGPT usage    (live account rate-limit windows)
  * openrouter    — /credits + /key         (balance + spend today/week/month)
  * nous          — portal JWT claims       (tier, spend, rate limits; free tier)
  * ollama_cloud  — POST /api/me            (plan + billing-period renewal)

Env (all optional — sane defaults for this box):
  INF_AGENT_PORT      listen port            (default 9890)
  INF_AGENT_BIND      bind address           (default 0.0.0.0; set the Tailscale IP to stay on the tailnet)
  INF_AGENT_TOKEN     shared secret          (?token=.. or Authorization: Bearer ..)
  INF_AGENT_INTERVAL  provider poll seconds  (default 60)
  INF_AGENT_PROVIDERS comma list to enable   (default claude,openai,openrouter,nous,ollama_cloud)

  INF_CLAUDE_CREDS    path to Claude creds   (default /root/.claude/.credentials.json)
  INF_OPENAI_CREDS    path to Codex auth     (default /root/.codex/auth.json)
  INF_HERMES_ENV      path to hermes .env    (default /root/.hermes/.env)
  INF_HERMES_CONFIG   path to hermes config  (default /root/.hermes/config.yaml)
  INF_NOUS_PORTAL     path to nous portal js (default /root/.hermes/nous-portal.json)
  OPENROUTER_API_KEY / OLLAMA_API_KEY        explicit key overrides (win over file discovery)

Endpoints:
  GET /providers (or /)  -> { ts, agent_host, interval, providers:[ ... ] }
  GET /healthz           -> "ok"
"""
import base64
import glob
import json
import os
import re
import socket
import subprocess
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
    "INF_AGENT_PROVIDERS", "claude,openai,openrouter,nous,ollama_cloud").split(",") if p.strip()]

CLAUDE_CREDS = os.environ.get("INF_CLAUDE_CREDS", "/root/.claude/.credentials.json")
OPENAI_CREDS = os.environ.get("INF_OPENAI_CREDS", "/root/.codex/auth.json")
OPENAI_USAGE_URL = os.environ.get(
    "INF_OPENAI_USAGE_URL", "https://chatgpt.com/backend-api/wham/usage")
OPENAI_SESSIONS = os.environ.get("INF_OPENAI_SESSIONS", "/root/.codex/sessions")
HERMES_ENV = os.environ.get("INF_HERMES_ENV", "/root/.hermes/.env")
HERMES_CONFIG = os.environ.get("INF_HERMES_CONFIG", "/root/.hermes/config.yaml")
NOUS_PORTAL = os.environ.get("INF_NOUS_PORTAL", "/root/.hermes/nous-portal.json")

UA = "ulanzi-inf-agent/1.4"
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
        if isinstance(s, (int, float)) or (isinstance(s, str) and s.strip().isdigit()):
            return datetime.fromtimestamp(float(s), timezone.utc)
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


def _first_num(*vals):
    """First value coercible to float, else None."""
    for v in vals:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


# ---- provider probes -------------------------------------------------------
_claude_profile = {"headline": None, "ts": 0.0}  # plan rarely changes → cache it


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
    # The shared OAuth rate limit on these endpoints 429s easily, so fetch the
    # (static) plan headline from /profile at most hourly, not every cycle.
    if _claude_profile["headline"] is None or (time.time() - _claude_profile["ts"]) > 3600:
        try:
            prof = _http("GET", "https://api.anthropic.com/api/oauth/profile", hdr)
            tier = (prof.get("organization") or {}).get("rate_limit_tier", "")
            m = re.search(r"max_(\d+)x", str(tier))  # "default_claude_max_20x" -> "Max 20x"
            if m:
                _claude_profile["headline"] = f"Max {m.group(1)}x"
                _claude_profile["ts"] = time.time()
        except Exception:
            pass
    p["headline"] = _claude_profile["headline"] or p.get("plan") or "Claude"
    try:
        u = _http("GET", "https://api.anthropic.com/api/oauth/usage", hdr)
    except urllib.error.HTTPError as e:
        p["error"] = ("rate limited (429)" if e.code == 429
                      else f"token expired ({e.code})" if e.code in (401, 403)
                      else f"HTTP {e.code}")
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


def _window_label(seconds):
    """Compact, truthful label for a rate-limit window."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "WINDOW"
    if seconds % 604800 == 0:
        n = seconds // 604800
        return "WEEK" if n == 1 else f"{n}W"
    if seconds % 86400 == 0:
        n = seconds // 86400
        return "DAY" if n == 1 else f"{n}D"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}H"
    return f"{max(1, round(seconds / 60))}M"


def _openai_window(raw):
    if not isinstance(raw, dict) or raw.get("used_percent") is None:
        return None
    seconds = int(raw.get("limit_window_seconds") or 0)
    reset = raw.get("reset_at")
    return {
        "pct": round(float(raw["used_percent"]), 1),
        "window_seconds": seconds,
        "label": _window_label(seconds),
        "resets_at": reset,
        "resets_in": _resets_in(reset),
    }


def _tail_json_objects(path, max_bytes=262144):
    """Yield recent JSONL objects without reading a whole Codex rollout file."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            raw = f.read().decode("utf-8", "replace")
        lines = raw.splitlines()
        if start and lines:
            lines = lines[1:]  # first line may be a truncated JSON object
        for line in reversed(lines):
            try:
                yield json.loads(line)
            except (TypeError, ValueError):
                continue
    except OSError:
        return


def _latest_codex_rate_limits():
    """Last Codex-emitted rate-limit snapshot, used only as an offline fallback."""
    paths = glob.glob(os.path.join(OPENAI_SESSIONS, "**", "*.jsonl"), recursive=True)
    try:
        paths.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        return None
    for path in paths[:8]:
        for row in _tail_json_objects(path):
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            rate = payload.get("rate_limits")
            if not isinstance(rate, dict):
                continue

            def convert(win):
                if not isinstance(win, dict):
                    return None
                return {
                    "used_percent": win.get("used_percent"),
                    "limit_window_seconds": int(win.get("window_minutes") or 0) * 60,
                    "reset_at": win.get("resets_at"),
                }

            return {
                "plan_type": rate.get("plan_type"),
                "rate_limit": {
                    "primary_window": convert(rate.get("primary")),
                    "secondary_window": convert(rate.get("secondary")),
                    "limit_reached": bool(rate.get("rate_limit_reached_type")),
                },
                "credits": rate.get("credits"),
            }
    return None


def probe_openai():
    """Codex/ChatGPT plan usage from the same endpoint the official CLI uses.

    The agent reads Codex's access token but never refreshes or writes it. If the
    live endpoint is briefly unavailable, the newest rate-limit snapshot already
    written by Codex to its local rollout JSONL is served as stale data.
    """
    p = {"id": "openai", "name": "OpenAI", "kind": "limit",
         "icon": "lightning-bolt", "ok": False, "session": None, "week": None}
    try:
        with open(OPENAI_CREDS) as f:
            auth = json.load(f)
        tokens = auth.get("tokens") or {}
        token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        if not token:
            raise ValueError("no ChatGPT access token")
    except Exception as e:
        p["error"] = f"Codex auth: {e} (run: codex login)"
        return p

    headers = {"Authorization": "Bearer " + token}
    if account_id:
        headers["ChatGPT-Account-Id"] = str(account_id)

    live_error = None
    try:
        usage = _http("GET", OPENAI_USAGE_URL, headers)
        p["source"] = "live"
    except urllib.error.HTTPError as e:
        live_error = (f"token expired ({e.code})" if e.code in (401, 403)
                      else f"usage HTTP {e.code}")
        usage = _latest_codex_rate_limits()
    except Exception as e:
        live_error = f"usage: {e}"
        usage = _latest_codex_rate_limits()

    if not isinstance(usage, dict):
        p["error"] = live_error or "empty usage response"
        return p
    if live_error:
        p["source"] = "codex-session"
        p["stale"] = True
        p["last_error"] = live_error

    plan = str(usage.get("plan_type") or "").strip()
    if plan:
        p["plan"] = plan.title()
    p["headline"] = p.get("plan") or "Codex"

    rate = usage.get("rate_limit") or {}
    windows = [w for w in (
        _openai_window(rate.get("primary_window")),
        _openai_window(rate.get("secondary_window")),
    ) if w]
    windows.sort(key=lambda w: w.get("window_seconds") or 0)
    for win in windows:
        if (win.get("window_seconds") or 0) <= 86400 and p["session"] is None:
            p["session"] = win
        elif p["week"] is None:
            p["week"] = win
        elif p["session"] is None:
            p["session"] = win
    if len(windows) >= 2 and p["session"] is None:
        p["session"], p["week"] = windows[0], windows[-1]

    p["limit_reached"] = bool(rate.get("limit_reached"))
    credits = usage.get("credits") or {}
    if credits.get("has_credits") and credits.get("balance") is not None:
        p["credit_balance"] = _first_num(credits.get("balance"))
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


# Live Nous plan/balance comes from the user's portal account API, which needs a
# valid token. We must NEVER refresh the Nous token ourselves (single-use; reuse →
# full session revocation; only hermes may rotate it). So we delegate to hermes's
# OWN `get_nous_portal_account_info()` by running it in hermes's venv — that path
# refreshes + persists the rotation correctly (same code + lock the gateway uses).
NOUS_HELPER_PY = os.environ.get("INF_NOUS_HELPER_PY", "/root/.hermes/hermes-agent/venv/bin/python")
NOUS_HELPER_CWD = os.environ.get("INF_NOUS_HELPER_CWD", "/root/.hermes/hermes-agent")
NOUS_LIVE_TTL = max(30, int(os.environ.get("INF_NOUS_LIVE_TTL", "60")))

_NOUS_HELPER_SRC = (
    "import json\n"
    "from hermes_cli.nous_account import get_nous_portal_account_info\n"
    "i=get_nous_portal_account_info(force_fresh=True)\n"
    "s=i.subscription; p=i.paid_service_access_info\n"
    "b=None\n"
    "if p is not None and getattr(p,'total_usable_credits',None) is not None: b=p.total_usable_credits\n"
    "elif s is not None and getattr(s,'credits_remaining',None) is not None: b=s.credits_remaining\n"
    "print(json.dumps({'logged_in':i.logged_in,'paid':i.paid_service_access,"
    "'plan':getattr(s,'plan',None),'tier':getattr(s,'tier',None),'balance':b,"
    "'monthly':getattr(s,'monthly_credits',None),'error':(str(i.error) if i.error else None)}))\n"
)
NOUS_STALE_AFTER = max(180, 3 * NOUS_LIVE_TTL)  # flag stale only after repeated fetch failures
_nous_live = {"data": None, "ts": 0.0}  # ts = last SUCCESSFUL live fetch


def _log(msg):
    print(f"[inf-agent] {msg}", flush=True)


def _nous_account_live():
    """Live plan/balance via hermes's sanctioned account path (cached NOUS_LIVE_TTL).
    Returns a dict or None. hermes owns the refresh/persist/locking — this is the
    only safe way to read the real balance. On failure, serves the last good value
    (probe_nous flags it `stale` once it ages past NOUS_STALE_AFTER) and logs to the
    journal so a real freeze is visible (vs a balance that simply isn't moving)."""
    if not os.path.exists(NOUS_HELPER_PY):
        return None
    if _nous_live["data"] is not None and (time.time() - _nous_live["ts"]) < NOUS_LIVE_TTL:
        return _nous_live["data"]
    try:
        r = subprocess.run([NOUS_HELPER_PY, "-c", _NOUS_HELPER_SRC], cwd=NOUS_HELPER_CWD,
                           capture_output=True, text=True, timeout=45)
        line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.strip().startswith("{")), "")
        data = json.loads(line) if line else None
        if data and data.get("logged_in") and not data.get("error"):
            prev = (_nous_live["data"] or {}).get("balance")
            _nous_live["data"] = data
            _nous_live["ts"] = time.time()
            _log(f"nous live ok: plan={data.get('plan')} balance={data.get('balance')}"
                 + ("" if prev == data.get("balance") else f" (was {prev})"))
            return data
        why = (data or {}).get("error") or (r.stderr.strip()[-160:] if r.stderr else "no json")
        _log(f"nous live fetch failed (serving last-good): {why}")
    except Exception as e:
        _log(f"nous live fetch EXC (serving last-good): {e}")
    return _nous_live["data"]  # last good live, if any


def probe_nous():
    # The nous-portal.json JWT is the hermes-agent *free-tier* identity — never
    # infer "Free" / balance from it. Real plan + purchased balance come from the
    # live account API (via hermes, see _nous_account_live). Precedence:
    # live > INF_NOUS_* env fallback > rate-limits/unknown.
    p = {"id": "nous", "name": "Nous", "kind": "balance", "icon": "chip",
         "currency": "USD", "ok": False}
    claims, token = {}, None
    try:
        d = json.load(open(NOUS_PORTAL))
        token = d.get("access_token")
        if token:
            seg = token.split(".")[1]
            seg += "=" * (-len(seg) % 4)
            claims = json.loads(base64.urlsafe_b64decode(seg))
    except Exception:
        pass

    p["tier"] = claims.get("subscription_tier")
    p["rate"] = {"rpm": claims.get("rate_limit_rpm"), "tpm": claims.get("rate_limit_tpm"),
                 "rph": claims.get("rate_limit_rph"), "tph": claims.get("rate_limit_tph")}
    if claims.get("iat"):
        p["token_age_min"] = round((time.time() - float(claims["iat"])) / 60, 1)

    live = _nous_account_live()
    p["live"] = bool(live)
    if live and _nous_live["ts"]:
        age = round(time.time() - _nous_live["ts"], 1)
        p["live_age_s"] = age
        if age > NOUS_STALE_AFTER:   # live fetch has been failing → flag frozen
            p["stale"] = True

    plan_env = os.environ.get("INF_NOUS_PLAN", "").strip()
    bal_env = _first_num(os.environ.get("INF_NOUS_BALANCE", "").strip().lstrip("$"))

    # plan: live > env
    if live and live.get("plan"):
        p["plan"] = live["plan"]
    elif plan_env:
        p["plan"] = plan_env
    # balance: live > env
    bal = live.get("balance") if (live and live.get("balance") is not None) else bal_env
    if bal is not None:
        p["balance"] = round(float(bal), 2)
    if live and live.get("tier") is not None:
        p["tier"] = live["tier"]
    if live and live.get("monthly") is not None:
        p["monthly_credits"] = live["monthly"]

    # Only mark FREE on positive live evidence (never from the stale agent JWT).
    p["free"] = bool(live and live.get("paid") is False and not p.get("plan") and "balance" not in p)

    if "balance" in p:
        p["headline"] = f"${p['balance']:.2f}"
    elif p.get("plan"):
        p["headline"] = p["plan"]
    elif p["free"]:
        p["headline"] = f"Free T{p['tier']}" if p.get("tier") is not None else "Free"
    else:
        p["headline"] = "Nous"

    if live or "balance" in p or token:
        p["ok"] = True
    else:
        p["error"] = "Nous not logged in (run: hermes auth add nous) and no INF_NOUS_* override"
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
    "openai": probe_openai,
    "openrouter": probe_openrouter,
    "nous": probe_nous,
    "ollama_cloud": probe_ollama_cloud,
}


_last_good = {}  # provider id -> {"p": <last ok payload>, "ts": epoch}


def collect():
    """Run every enabled probe. On a transient failure (e.g. Claude's OAuth token
    briefly 401s while Claude Code rotates it, or a network blip), serve the last
    SUCCESSFUL payload for that provider marked `stale` instead of an error card —
    so a tile freezes on its last good number rather than flashing an error. Only a
    provider that has never succeeded surfaces its raw error."""
    out = []
    for pid in ENABLED:
        fn = PROBES.get(pid)
        if not fn:
            continue
        try:
            p = fn()
        except Exception as e:  # a probe must never take down the loop
            p = {"id": pid, "name": pid, "kind": "balance", "ok": False, "error": str(e)}
        if p.get("ok"):
            _last_good[pid] = {"p": p, "ts": time.time()}
            out.append(p)
        elif pid in _last_good:
            cached = dict(_last_good[pid]["p"])
            cached["stale"] = True
            cached["stale_min"] = round((time.time() - _last_good[pid]["ts"]) / 60, 1)
            cached["last_error"] = p.get("error")
            out.append(cached)
        else:
            out.append(p)  # never succeeded → surface the error
    return out


def _refresh_loop():
    while True:
        providers = collect()
        with _lock:
            _snapshot["ts"] = int(time.time() * 1000)
            _snapshot["providers"] = providers
        time.sleep(INTERVAL)


# ---- http ------------------------------------------------------------------
_poll_seen = {}  # client ip -> last logged ts; first poll + one line per 10 min


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _log_poller(self):
        # Throttled client-visibility log: answers "is the plugin polling us?"
        # (диагноз "agent off" на деке) straight from journalctl.
        ip = self.client_address[0]
        now = time.time()
        if now - _poll_seen.get(ip, 0) >= 600:
            _poll_seen[ip] = now
            print(f"[inf-agent] poll from {ip}", flush=True)

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
            self._log_poller()
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
