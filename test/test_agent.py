#!/usr/bin/env python3
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("inf_agent", ROOT / "agent" / "inf-agent.py")
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)

# Never let a test read the host's real credential files: a failing assertion
# would print the real key (2026-11-02: OPENCODE_GO_API_KEY appeared in hermes
# .env and leaked into a failure message). Point every discovery path at an
# empty sandbox and drop provider-key env overrides for the whole run.
_CRED_SANDBOX = tempfile.TemporaryDirectory()
agent.HERMES_ENV = os.path.join(_CRED_SANDBOX.name, "hermes.env")
agent.HERMES_CONFIG = os.path.join(_CRED_SANDBOX.name, "config.yaml")
agent.OPENCODE_AUTH = os.path.join(_CRED_SANDBOX.name, "opencode-auth.json")
agent.CLAUDE_CREDS = os.path.join(_CRED_SANDBOX.name, "claude-credentials.json")
agent.OPENAI_CREDS = os.path.join(_CRED_SANDBOX.name, "codex-auth.json")
agent.OPENAI_SESSIONS = os.path.join(_CRED_SANDBOX.name, "codex-sessions")
for _k in ("OPENROUTER_API_KEY", "OLLAMA_API_KEY", "OPENCODE_GO_API_KEY"):
    os.environ.pop(_k, None)


class OpenAIProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth_path = Path(self.tmp.name) / "auth.json"
        self.auth_path.write_text(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": "test-token",
                "account_id": "test-account",
            },
        }))
        self.old_creds = agent.OPENAI_CREDS
        self.old_sessions = agent.OPENAI_SESSIONS
        self.old_http = agent._http
        self.old_fallback = agent._latest_codex_rate_limits
        agent.OPENAI_CREDS = str(self.auth_path)

    def tearDown(self):
        agent.OPENAI_CREDS = self.old_creds
        agent.OPENAI_SESSIONS = self.old_sessions
        agent._http = self.old_http
        agent._latest_codex_rate_limits = self.old_fallback
        self.tmp.cleanup()

    @staticmethod
    def usage(primary_seconds=18000, secondary_seconds=604800):
        def window(seconds, pct):
            return None if seconds is None else {
                "used_percent": pct,
                "limit_window_seconds": seconds,
                "reset_at": 4102444800,
            }
        return {
            "plan_type": "pro",
            "rate_limit": {
                "limit_reached": False,
                "primary_window": window(primary_seconds, 23),
                "secondary_window": window(secondary_seconds, 41),
            },
            "credits": {"has_credits": False, "balance": "0"},
        }

    def test_live_dual_window_usage(self):
        captured = {}

        def fake_http(method, url, headers=None, body=None):
            captured.update(method=method, url=url, headers=headers)
            return self.usage()

        agent._http = fake_http
        result = agent.probe_openai()

        self.assertTrue(result["ok"])
        self.assertEqual(result["plan"], "Pro")
        self.assertEqual(result["session"]["pct"], 23.0)
        self.assertEqual(result["session"]["label"], "5H")
        self.assertEqual(result["week"]["pct"], 41.0)
        self.assertEqual(result["week"]["label"], "WEEK")
        self.assertEqual(captured["headers"]["ChatGPT-Account-Id"], "test-account")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-token")

    def test_week_only_window_uses_secondary_tile(self):
        agent._http = lambda *args, **kwargs: self.usage(604800, None)
        result = agent.probe_openai()

        self.assertTrue(result["ok"])
        self.assertIsNone(result["session"])
        self.assertEqual(result["week"]["label"], "WEEK")
        self.assertEqual(result["week"]["pct"], 23.0)

    def test_local_codex_snapshot_is_stale_fallback(self):
        agent._http = lambda *args, **kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("offline"))
        agent._latest_codex_rate_limits = lambda: self.usage()
        result = agent.probe_openai()

        self.assertTrue(result["ok"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["source"], "codex-session")
        self.assertIn("offline", result["last_error"])

    def test_missing_auth_is_actionable(self):
        agent.OPENAI_CREDS = str(Path(self.tmp.name) / "missing.json")
        result = agent.probe_openai()

        self.assertFalse(result["ok"])
        self.assertIn("codex login", result["error"])

    def test_reads_latest_codex_jsonl_snapshot(self):
        sessions = Path(self.tmp.name) / "sessions" / "2026" / "07" / "21"
        sessions.mkdir(parents=True)
        rollout = sessions / "rollout-test.jsonl"
        rollout.write_text(json.dumps({
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "plan_type": "pro",
                    "primary": {
                        "used_percent": 12,
                        "window_minutes": 300,
                        "resets_at": 4102444800,
                    },
                    "secondary": {
                        "used_percent": 34,
                        "window_minutes": 10080,
                        "resets_at": 4102444800,
                    },
                    "credits": {"has_credits": False, "balance": "0"},
                },
            },
        }) + "\n")
        agent.OPENAI_SESSIONS = str(Path(self.tmp.name) / "sessions")

        result = agent._latest_codex_rate_limits()

        self.assertEqual(result["plan_type"], "pro")
        self.assertEqual(result["rate_limit"]["primary_window"]["limit_window_seconds"], 18000)
        self.assertEqual(result["rate_limit"]["secondary_window"]["used_percent"], 34)


class NousLiveProbeTest(unittest.TestCase):
    def setUp(self):
        self.old_run = agent.subprocess.run
        self.old_log = agent._log
        self.old_live = agent._nous_live
        self.old_retry = agent.NOUS_LOGGED_OUT_RETRY
        agent.NOUS_LOGGED_OUT_RETRY = 900
        agent._nous_live = {"data": None, "ts": 0.0, "retry_at": 0.0, "notice": None}
        self.logs = []
        agent._log = self.logs.append

    def tearDown(self):
        agent.subprocess.run = self.old_run
        agent._log = self.old_log
        agent._nous_live = self.old_live
        agent.NOUS_LOGGED_OUT_RETRY = self.old_retry

    def test_logged_out_json_uses_fallback_without_failure_spam(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(
                stdout=json.dumps({
                    "logged_in": False,
                    "paid": None,
                    "plan": None,
                    "tier": None,
                    "balance": None,
                    "monthly": None,
                    "error": None,
                }) + "\n",
                stderr="",
                returncode=0,
            )

        agent.subprocess.run = fake_run

        self.assertIsNone(agent._nous_account_live())
        self.assertIsNone(agent._nous_account_live())
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            self.logs,
            ["nous live unavailable: not logged in; using configured fallback"],
        )
        self.assertFalse(any("fetch failed" in message for message in self.logs))

    def test_missing_json_remains_an_actionable_failure(self):
        agent.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
            stdout="", stderr="", returncode=7)

        self.assertIsNone(agent._nous_account_live())
        self.assertEqual(
            self.logs,
            ["nous live fetch failed (serving last-good): helper returned no JSON (exit 7)"],
        )


class OllamaCloudProbeTest(unittest.TestCase):
    def setUp(self):
        self.old_http = agent._http
        self.old_key = os.environ.get("OLLAMA_API_KEY")
        os.environ["OLLAMA_API_KEY"] = "ollama-test-key"

    def tearDown(self):
        agent._http = self.old_http
        if self.old_key is None:
            os.environ.pop("OLLAMA_API_KEY", None)
        else:
            os.environ["OLLAMA_API_KEY"] = self.old_key

    def _fake(self, routes, calls=None):
        def fake_http(method, url, headers=None, body=None):
            if calls is not None:
                calls.append((method, url, headers))
            for suffix, value in routes.items():
                if url.endswith(suffix):
                    if isinstance(value, Exception):
                        raise value
                    return value
            self.fail("unexpected URL: " + url)
        return fake_http

    def test_credit_plan_renders_as_balance_with_spend_and_renewal(self):
        calls = []
        agent._http = self._fake({
            "/api/balance": {
                "included": {"balance_usd": 59.93709, "allowance_usd": 60,
                             "period": {"from": "2026-10-31T18:37:16Z", "until": "2099-12-01T18:37:00Z"}},
                "purchased": {"balance_usd": 5},
            },
            "/api/usage": {"range": "7d", "totals": {"usage_usd": 0.06291},
                           "buckets": [{"from": "2000-01-01T00:00:00Z", "until": "2000-01-02T00:00:00Z", "usage_usd": 0},
                                       {"from": "2099-01-01T00:00:00Z", "until": "2099-01-02T00:00:00Z", "usage_usd": 0.01}]},
            "/api/me": {"Plan": "pro"},
        }, calls)
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "balance")
        self.assertEqual(result["balance"], 64.94)           # included + purchased
        self.assertEqual(result["included_balance"], 59.94)
        self.assertEqual(result["purchased_balance"], 5.0)
        self.assertEqual(result["spend_month"], 0.06)        # allowance - included balance
        self.assertEqual(result["spend_week"], 0.06)
        self.assertEqual(result["spend_today"], 0.01)        # no bucket spans now -> last bucket
        self.assertEqual(result["month"]["label"], "MONTH")
        self.assertEqual(result["month"]["pct"], 0.1)
        self.assertEqual(result["renews_at"], "2099-12-01T18:37:00Z")
        self.assertEqual(result["plan"], "Pro · $60/mo")
        self.assertEqual(result["headline"], "$64.94")
        self.assertNotIn("limit_reached", result)
        self.assertEqual(calls[0][0:2], ("GET", "https://ollama.com/api/balance"))
        self.assertEqual(calls[0][2]["Authorization"], "Bearer ollama-test-key")

    def test_spent_credits_flag_limit_reached(self):
        agent._http = self._fake({
            "/api/balance": {"included": {"balance_usd": 0, "allowance_usd": 20,
                                          "period": {"until": "2099-01-01T00:00:00Z"}},
                             "purchased": {"balance_usd": 0}},
            "/api/usage": {"totals": {"usage_usd": 20}},
            "/api/me": {"Plan": "free"},
        })
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["balance"], 0.0)
        self.assertEqual(result["month"]["pct"], 100.0)
        self.assertTrue(result["limit_reached"])

    def test_legacy_plan_session_and_weekly_with_resets(self):
        agent._http = self._fake({
            "/api/balance": {"included": {
                "session": {"remaining_percent": 76.5, "resets_at": "2099-10-01T07:00:00Z"},
                "weekly": {"remaining_percent": 39, "resets_at": "2099-10-05T00:00:00Z"}},
                "purchased": {"balance_usd": 25}},
            "/api/usage": {"totals": {"usage_usd": 1.2}},
            "/api/me": {"Plan": "pro"},
        })
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "limit")
        self.assertEqual(result["session"]["pct"], 23.5)
        self.assertEqual(result["session"]["label"], "5H")
        self.assertEqual(result["session"]["resets_at"], "2099-10-01T07:00:00Z")
        self.assertTrue(result["session"]["resets_in"])
        self.assertEqual(result["week"]["pct"], 61.0)
        self.assertEqual(result["purchased_balance"], 25.0)
        self.assertEqual(result["headline"], "PRO")

    def test_balance_outage_falls_back_to_legacy_usage_limits(self):
        agent._http = self._fake({
            "/api/balance": OSError("balance unavailable"),
            "/api/usage": {"limits": {"session": {"usage": 0.235}, "weekly": {"usage": 0.61}}},
            "/api/me": {"Plan": "Pro"},
        })
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["session"], {"pct": 23.5, "label": "5H"})
        self.assertEqual(result["week"], {"pct": 61.0, "label": "WEEK"})

    def test_rejected_key_is_reported_not_hidden(self):
        err = agent.urllib.error.HTTPError("https://ollama.com/api/balance", 401, "Unauthorized", {}, None)
        agent._http = self._fake({
            "/api/balance": err,
            "/api/usage": {"range": "7d", "totals": {"usage_usd": 0}},
        })
        result = agent.probe_ollama_cloud()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "key rejected (401)")

    def test_profile_failure_does_not_hide_credits(self):
        agent._http = self._fake({
            "/api/balance": {"included": {"balance_usd": 10, "allowance_usd": 20, "period": {}},
                             "purchased": {"balance_usd": 0}},
            "/api/usage": OSError("usage unavailable"),
            "/api/me": OSError("profile unavailable"),
        })
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["headline"], "$10.00")
        self.assertEqual(result["plan"], "$20/mo")
        self.assertIn("profile unavailable", result["profile_error"])
        self.assertIn("usage unavailable", result["usage_error"])


class OpenCodeGoProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth_path = Path(self.tmp.name) / "opencode-auth.json"
        self.auth_path.write_text(json.dumps({"opencode-go": {"type": "api", "key": "go-test-key"}}))
        self.old_auth = agent.OPENCODE_AUTH
        self.old_http = agent._http
        self.old_key = os.environ.get("OPENCODE_GO_API_KEY")
        os.environ.pop("OPENCODE_GO_API_KEY", None)
        agent.OPENCODE_AUTH = str(self.auth_path)

    def tearDown(self):
        agent.OPENCODE_AUTH = self.old_auth
        agent._http = self.old_http
        if self.old_key is None:
            os.environ.pop("OPENCODE_GO_API_KEY", None)
        else:
            os.environ["OPENCODE_GO_API_KEY"] = self.old_key
        self.tmp.cleanup()

    def test_auth_file_and_three_usage_windows_are_normalised(self):
        captured = {}

        def fake_http(method, url, headers=None, body=None):
            captured.update(method=method, url=url, headers=headers)
            return {"usage": {
                "rolling": {"percent": 12.5, "resetsAt": "2100-01-01T00:00:00Z"},
                "weekly": {"percent": 34, "resetsAt": "2100-01-03T00:00:00Z"},
                "monthly": {"percent": 56.75, "resetsAt": "2100-02-01T00:00:00Z"},
            }}

        agent._http = fake_http
        result = agent.probe_opencode_go()

        self.assertTrue(result["ok"])
        self.assertEqual(result["session"]["pct"], 12.5)
        self.assertEqual(result["session"]["label"], "5H")
        self.assertEqual(result["week"]["pct"], 34.0)
        self.assertEqual(result["month"]["pct"], 56.8)
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["url"], agent.OPENCODE_GO_USAGE_URL)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer go-test-key")


if __name__ == "__main__":
    unittest.main()
