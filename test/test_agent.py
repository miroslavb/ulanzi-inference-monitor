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

    def test_usage_endpoint_populates_live_session_and_weekly_limits(self):
        calls = []

        def fake_http(method, url, headers=None, body=None):
            calls.append((method, url, headers))
            if url.endswith("/api/usage"):
                return {"limits": {
                    "session": {"usage": 0.235, "models": []},
                    "weekly": {"usage": 0.61, "models": []},
                }}
            if url.endswith("/api/me"):
                return {"Plan": "Pro"}
            self.fail("unexpected URL: " + url)

        agent._http = fake_http
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["session"], {"pct": 23.5, "label": "5H"})
        self.assertEqual(result["week"], {"pct": 61.0, "label": "WEEK"})
        self.assertEqual(result["headline"], "PRO")
        self.assertEqual(calls[0][0:2], ("GET", "https://ollama.com/api/usage"))
        self.assertEqual(calls[0][2]["Authorization"], "Bearer ollama-test-key")

    def test_profile_failure_does_not_hide_usage(self):
        def fake_http(method, url, headers=None, body=None):
            if url.endswith("/api/usage"):
                return {"limits": {"session": {"usage": 0.1}, "weekly": {"usage": 0.2}}}
            raise OSError("profile unavailable")

        agent._http = fake_http
        result = agent.probe_ollama_cloud()

        self.assertTrue(result["ok"])
        self.assertEqual(result["headline"], "Ollama")
        self.assertIn("profile unavailable", result["profile_error"])


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
