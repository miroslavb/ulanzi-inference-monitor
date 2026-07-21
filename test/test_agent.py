#!/usr/bin/env python3
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
