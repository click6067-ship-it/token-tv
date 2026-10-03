import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from token_tv.usage import normalize_claude, normalize_codex, normalize_grok
from token_tv.sources import fetch_account, load_config, grok_identity, scoped_env
from token_tv.state import UsageStore
from token_tv.display import render_page, pages, overview_rows, primary_window


class LiveTests(unittest.TestCase):
    def test_provider_cli_environment_does_not_inherit_other_authentication(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "DO-NOT-INHERIT", "GROK_OAUTH_TOKEN": "DO-NOT-INHERIT", "CLAUDE_CODE_OAUTH_TOKEN": "DO-NOT-INHERIT"}):
            for provider, variable in (("claude", "CLAUDE_CONFIG_DIR"), ("codex", "CODEX_HOME"), ("grok", "GROK_HOME")):
                env = scoped_env(provider, "/explicit/account/home")
                self.assertEqual(env[variable], "/explicit/account/home")
                self.assertFalse(any(key in env for key in ("OPENAI_API_KEY", "GROK_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")))

    def test_codex_uses_reported_window_duration(self):
        data = {"rateLimits": {"primary": {"usedPercent": 78, "windowDurationMins": 10080, "resetsAt": 2000000000}, "secondary": None}}
        self.assertEqual(normalize_codex(data), [{"label": "WEEK", "used_percent": 78.0, "resets_at": 2000000000, "duration_minutes": 10080}])

    def test_missing_grok_quota_is_unknown(self):
        self.assertEqual(normalize_grok({"config": {"currentPeriod": {"end": "2026-10-05T00:00:00Z"}}}), [])
        self.assertEqual(normalize_claude({"five_hour": {"utilization": None}, "seven_day": {"utilization": 24, "resets_at": None}})[0]["label"], "WEEK")

    def test_credentials_and_identity_never_enter_snapshot(self):
        account = {"key": "a", "alias": "CLAUDE A", "provider": "claude", "source_home": "/unused", "email": "expected@example.com"}
        with patch("token_tv.sources.claude_payload", return_value=({"account": {"email": "wrong@example.com"}}, {"five_hour": {"utilization": 8}, "access_token": "DO-NOT-EXPORT"})):
            row = fetch_account(account)
        self.assertEqual(row["status"], "identity_mismatch")
        self.assertEqual(row["windows"], [])
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(row))
        self.assertNotIn("wrong@example.com", json.dumps(row))

    def test_configuration_rejects_secret_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"accounts": [{"key": "a", "alias": "A", "provider": "claude", "password": "DO-NOT-USE"}]}))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_grok_owner_identity_must_match_expected_email(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(json.dumps({"issuer::client": {"email": "owner@example.com", "key": "NEVER-EXPORT", "refresh_token": "NEVER-EXPORT"}}))
            self.assertEqual(grok_identity({"source_home": directory}), "owner@example.com")
            account = {"key": "g", "alias": "G", "provider": "grok", "source_home": directory, "email": "wrong@example.com"}
            with patch("token_tv.sources.grok_payload") as billing:
                row = fetch_account(account)
            billing.assert_not_called()
            self.assertEqual(row["status"], "identity_mismatch")
            self.assertNotIn("NEVER-EXPORT", json.dumps(row))

    def test_cache_is_per_account_and_failure_preserves_stale_values(self):
        accounts = [{"key": "a", "alias": "A", "provider": "claude"}, {"key": "b", "alias": "B", "provider": "claude"}]
        replies = {
            "a": {"key": "a", "alias": "A", "provider": "claude", "status": "ok", "windows": [{"label": "WEEK", "used_percent": 31, "resets_at": None, "duration_minutes": 10080}], "fetched_at": 100},
            "b": {"key": "b", "alias": "B", "provider": "claude", "status": "auth_required", "windows": [], "fetched_at": 100},
        }
        calls = []
        def fetch(account):
            calls.append(account["key"])
            return copy.deepcopy(replies[account["key"]])
        store = UsageStore(accounts, fetch=fetch)
        store.refresh()
        one = store.snapshot()
        two = store.snapshot()
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(one, two)
        self.assertEqual(one["accounts"]["a"]["windows"][0]["used_percent"], 31)
        self.assertEqual(one["accounts"]["b"]["windows"], [])
        replies["a"].update(status="error", windows=[], fetched_at=200)
        store.refresh()
        row = store.snapshot()["accounts"]["a"]
        self.assertEqual(row["status"], "stale")
        self.assertEqual(row["windows"][0]["used_percent"], 31)
        self.assertEqual(row["last_success_at"], 100)
        self.assertEqual(row["error_code"], "error")

    def test_wrong_identity_does_not_reuse_previous_account_values(self):
        account = {"key": "a", "alias": "A", "provider": "claude"}
        replies = [dict(account, status="ok", windows=[{"label": "WEEK", "used_percent": 31}], fetched_at=time.time(), identity_verified=True),
                   dict(account, status="identity_mismatch", windows=[], fetched_at=time.time(), identity_verified=False)]
        store = UsageStore([account], fetch=lambda _: replies.pop(0))
        store.refresh()
        store.refresh()
        row = store.snapshot()["accounts"]["a"]
        self.assertEqual(row["status"], "identity_mismatch")
        self.assertEqual(row["windows"], [])

    def test_laptop_fallback_is_replaced_by_verified_mini_login(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.json"
            row = {"key": "a", "alias": "A", "provider": "claude", "status": "ok", "fetched_at": time.time(), "identity_verified": True,
                   "windows": [{"label": "WEEK", "used_percent": 31, "resets_at": None, "duration_minutes": 10080}]}
            path.write_text(json.dumps({"accounts": {"a": row}}))
            account = {"key": "a", "alias": "A", "provider": "claude", "email": "owner@example.com", "source_home": str(Path(directory)/"absent"), "fallback_snapshot_file": str(path)}
            actual = fetch_account(account)
            self.assertEqual(actual["source"], "laptop")
            self.assertEqual(actual["status"], "ok")
            self.assertEqual(actual["mini_auth_status"], "auth_required")
            with patch("token_tv.sources.claude_payload", return_value=({"account": {"email": "owner@example.com"}}, {"seven_day": {"utilization": 24}})):
                actual = fetch_account(account)
            self.assertEqual(actual["source"], "mini")
            self.assertEqual(actual["windows"][0]["used_percent"], 24)
            self.assertNotIn("mini_auth_status", actual)

    def test_renderer_has_real_pixel_dimensions_and_missing_state(self):
        snapshot = {"schema": 1, "accounts": {"a": {"alias": "CLAUDE A", "provider": "claude", "status": "auth_required", "windows": [], "fetched_at": 100}}}
        self.assertEqual(len(pages(snapshot)), 1)
        body = render_page(snapshot, 0)
        image = Image.open(io.BytesIO(body))
        self.assertEqual(image.size, (240, 240))
        self.assertEqual(image.format, "JPEG")
        self.assertGreater(len(image.getcolors(240 * 240)), 20)
        self.assertLess(len(body), 60000)

    def test_overview_keeps_one_account_per_provider_without_losing_details(self):
        def account(provider, alias, status="ok"):
            return {"provider": provider, "alias": alias, "status": status,
                    "windows": [] if status != "ok" else [{"label": "WEEK", "used_percent": 94, "resets_at": None}]}
        snapshot = {"accounts": {
            "ca": account("claude", "CLAUDE A"), "cb": account("claude", "CLAUDE B"),
            "cc": account("claude", "CLAUDE C"), "xa": account("codex", "CODEX A"),
            "ga": account("grok", "GROK A", "auth_required"), "gb": account("grok", "GROK B")}}
        rows = overview_rows(snapshot)
        self.assertEqual([r["key"] for r in rows], ["ca", "xa", "gb"])
        self.assertEqual(len(snapshot["accounts"]), 6)
        self.assertEqual(render_page(snapshot, 0), render_page(snapshot, 1))

    def test_overview_preserves_quota_period_and_unknown_values(self):
        windows = [{"label": "5H", "used_percent": 2}, {"label": "WEEK", "used_percent": 94}]
        self.assertEqual(primary_window({"windows": windows})["label"], "WEEK")
        self.assertIsNone(primary_window({"windows": []}))
        self.assertEqual(primary_window({"windows": [{"label": "BUDGET", "used_percent": 100}]})["label"], "BUDGET")


if __name__ == "__main__":
    unittest.main()
