"""CodexBar input. Fixtures are real CodexBar 0.74.0 output on Linux with emails and IDs replaced."""
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from token_tv.display import render_page
from token_tv.sources import fetch_account, load_config
from token_tv.state import UsageStore
from token_tv.usage import normalize_codexbar

FIXTURES = Path(__file__).parent / "fixtures" / "codexbar"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ran(stdout, code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout)


CLAUDE = {"key": "claude_a", "alias": "CLAUDE A", "provider": "claude", "email": "user@example.com",
          "codexbar_command": "codexbar", "codexbar_source": "oauth"}
CODEX = {"key": "codex_a", "alias": "CODEX A", "provider": "codex", "email": "user@example.com",
         "codexbar_command": "codexbar"}


class NormalizeTests(unittest.TestCase):
    def test_claude_session_and_weekly(self):
        windows = normalize_codexbar(fixture("usage-claude-oauth.json")[0])
        self.assertEqual(windows, [
            {"label": "5H", "used_percent": 10.0, "resets_at": 1791724200, "duration_minutes": 300},
            {"label": "WEEK", "used_percent": 77.0, "resets_at": 1791846000, "duration_minutes": 10080}])

    def test_model_scoped_window_never_replaces_weekly(self):
        entry = fixture("usage-claude-oauth.json")[0]
        self.assertEqual(entry["usage"]["extraRateWindows"][0]["window"]["usedPercent"], 0)
        entry["usage"]["tertiary"] = {"usedPercent": 1, "windowMinutes": 10080}
        self.assertEqual([w["used_percent"] for w in normalize_codexbar(entry)], [10.0, 77.0])

    def test_missing_session_stays_missing(self):
        entry = fixture("usage-codex.json")[0]
        self.assertIsNone(entry["usage"]["primary"])
        self.assertEqual(normalize_codexbar(entry), [
            {"label": "WEEK", "used_percent": 6.0, "resets_at": 1792296163, "duration_minutes": 10080}])

    def test_unknown_cadence_is_not_guessed_from_display_label(self):
        entry = {"rateWindowLabels": {"primary": "Session"},
                 "usage": {"primary": {"usedPercent": 40, "resetsAt": "2026-10-11T13:10:00Z"}}}
        self.assertEqual(normalize_codexbar(entry), [
            {"label": "WINDOW", "used_percent": 40.0, "resets_at": 1791724200, "duration_minutes": None}])

    def test_missing_percent_is_not_zero(self):
        entry = {"usage": {"primary": {"windowMinutes": 300, "resetsAt": "2026-10-11T13:10:00Z"}}}
        self.assertEqual(normalize_codexbar(entry), [])
        self.assertEqual(normalize_codexbar({"provider": "claude", "error": {"kind": "provider"}}), [])


class FetchTests(unittest.TestCase):
    def test_cli_command_line_and_row(self):
        stdout = (FIXTURES / "usage-claude-oauth.json").read_text(encoding="utf-8")
        with patch("token_tv.sources.subprocess.run", return_value=ran(stdout)) as run:
            row = fetch_account(CLAUDE)
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ["usage", "--provider", "claude", "--format", "json", "--source", "oauth"])
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual((row["status"], row["source"]), ("ok", "codexbar"))
        self.assertEqual([w["label"] for w in row["windows"]], ["5H", "WEEK"])
        # CodexBar's Claude OAuth path reports no email, so nothing is claimed.
        self.assertFalse(row["identity_verified"])

    def test_source_flag_is_omitted_unless_configured(self):
        stdout = (FIXTURES / "usage-codex.json").read_text(encoding="utf-8")
        with patch("token_tv.sources.subprocess.run", return_value=ran(stdout)) as run:
            row = fetch_account(CODEX)
        self.assertNotIn("--source", run.call_args.args[0])
        self.assertIsNone(run.call_args.kwargs["env"])
        self.assertEqual((row["status"], row["identity_verified"]), ("ok", True))

    def test_source_home_scopes_the_cli_home(self):
        account = dict(CODEX, source_home="/explicit/codex-home")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "DO-NOT-INHERIT"}), \
                patch("token_tv.sources.subprocess.run", return_value=ran((FIXTURES / "usage-codex.json").read_text(encoding="utf-8"))) as run:
            fetch_account(account)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["CODEX_HOME"], str(Path("/explicit/codex-home")))
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_reported_email_must_match(self):
        stdout = (FIXTURES / "usage-codex.json").read_text(encoding="utf-8")
        with patch("token_tv.sources.subprocess.run", return_value=ran(stdout)):
            row = fetch_account(dict(CODEX, email="someone-else@example.com"))
        self.assertEqual((row["status"], row["windows"]), ("identity_mismatch", []))

    def test_every_reported_email_must_match(self):
        entry = fixture("usage-codex.json")[0]
        entry["usage"]["accountEmail"] = "someone-else@example.com"
        with patch("token_tv.sources.subprocess.run", return_value=ran(json.dumps([entry]))):
            row = fetch_account(CODEX)
        self.assertEqual((row["status"], row["windows"]), ("identity_mismatch", []))

    def test_malformed_entry_fails_only_that_account(self):
        broken = [{"provider": "codex", "usage": "x"},
                  {"provider": "codex", "usage": {"identity": [], "primary": "x", "secondary": 5}}]
        for entry in broken:
            with patch("token_tv.sources.subprocess.run", return_value=ran(json.dumps([entry]))):
                row = fetch_account(CODEX)
            self.assertIn(row["status"], ("error", "quota_unavailable"), entry)
            self.assertEqual(row["windows"], [])
        direct = {"key": "claude_d", "alias": "CLAUDE D", "provider": "claude", "email": "user@example.com",
                  "source_home": "/unused"}
        store = UsageStore([dict(CODEX), direct])
        with patch("token_tv.sources.subprocess.run", return_value=ran(json.dumps(broken[:1]))), \
                patch("token_tv.sources.claude_payload", return_value=({"account": {"email": "user@example.com"}},
                                                                       {"five_hour": {"utilization": 8}})):
            store.refresh()
        self.assertEqual(store.snapshot()["accounts"]["claude_d"]["session_percent"], 8.0)

    def test_failed_provider_keeps_no_numbers_and_no_message(self):
        stdout = (FIXTURES / "usage-claude-cli-error.json").read_text(encoding="utf-8")
        with patch("token_tv.sources.subprocess.run", return_value=ran(stdout, 1)):
            row = fetch_account(dict(CLAUDE, codexbar_source="cli"))
        self.assertEqual((row["status"], row["error_code"], row["windows"]), ("error", "codexbar_provider", []))
        self.assertNotIn("Could not parse", json.dumps(row))

    def test_auth_failure_is_reported_as_sign_in(self):
        stdout = json.dumps([{"provider": "codex", "source": "auto",
                              "error": {"code": 1, "kind": "provider", "message": "Codex login required"}}])
        with patch("token_tv.sources.subprocess.run", return_value=ran(stdout, 1)):
            row = fetch_account(CODEX)
        self.assertEqual(row["status"], "auth_required")

    def test_missing_cli_is_not_a_login_problem(self):
        with patch("token_tv.sources.subprocess.run", side_effect=FileNotFoundError):
            row = fetch_account(CODEX)
        self.assertEqual((row["status"], row["error_code"]), ("error", "cli_unavailable"))

    def test_unreadable_output_is_an_error(self):
        for stdout in ("", "not json", "{}", "[]"):
            with patch("token_tv.sources.subprocess.run", return_value=ran(stdout)):
                row = fetch_account(CODEX)
            self.assertEqual((row["status"], row["windows"]), ("error", []), stdout)

    def test_timeout_is_an_error(self):
        with patch("token_tv.sources.subprocess.run", side_effect=subprocess.TimeoutExpired("codexbar", 60)):
            row = fetch_account(CODEX)
        self.assertEqual(row["status"], "error")

    def test_serve_url_picks_this_accounts_provider(self):
        account = {"key": "claude_a", "alias": "CLAUDE A", "provider": "claude", "email": "user@example.com",
                   "codexbar_url": "http://127.0.0.1:8080/usage"}
        with patch("token_tv.sources.json_get", return_value=fixture("serve-usage.json")) as get, \
                patch("token_tv.sources.subprocess.run") as run:
            row = fetch_account(account)
        get.assert_called_once_with("http://127.0.0.1:8080/usage")
        run.assert_not_called()
        self.assertEqual([w["used_percent"] for w in row["windows"]], [10.0, 77.0])
        with patch("token_tv.sources.json_get", return_value=fixture("serve-usage.json")):
            row = fetch_account(dict(account, provider="codex", key="codex_a", alias="CODEX A"))
        self.assertEqual(([w["label"] for w in row["windows"]], row["identity_verified"]), (["WEEK"], True))

    def test_serve_picks_the_matching_codex_account(self):
        first = fixture("usage-codex.json")[0]
        second = json.loads(json.dumps(first))
        second["usage"]["identity"]["accountEmail"] = second["usage"]["accountEmail"] = "work@example.com"
        second["usage"]["secondary"]["usedPercent"] = 55
        account = dict(CODEX, email="work@example.com", codexbar_url="http://127.0.0.1:8080/usage")
        del account["codexbar_command"]
        with patch("token_tv.sources.json_get", return_value=[first, second]):
            row = fetch_account(account)
        self.assertEqual([w["used_percent"] for w in row["windows"]], [55.0])
        with patch("token_tv.sources.json_get", return_value=[first, second]):
            row = fetch_account(dict(account, email="nobody@example.com"))
        self.assertEqual(row["status"], "identity_mismatch")

    def test_provider_absent_from_output(self):
        with patch("token_tv.sources.subprocess.run", return_value=ran((FIXTURES / "usage-codex.json").read_text(encoding="utf-8"))):
            row = fetch_account(CLAUDE)
        self.assertEqual((row["status"], row["error_code"]), ("error", "codexbar_provider_missing"))

    def test_store_and_clock_render_from_real_output(self):
        outputs = {"claude": (FIXTURES / "usage-claude-oauth.json").read_text(encoding="utf-8"),
                   "codex": (FIXTURES / "usage-codex.json").read_text(encoding="utf-8")}
        def fake(command, **kwargs):
            return ran(outputs[command[command.index("--provider") + 1]])
        store = UsageStore([CLAUDE, CODEX])
        with patch("token_tv.sources.subprocess.run", side_effect=fake), \
                patch("time.time", return_value=1791717216):
            store.refresh()
            snapshot = store.snapshot()
        claude, codex = snapshot["accounts"]["claude_a"], snapshot["accounts"]["codex_a"]
        self.assertEqual((claude["session_percent"], claude["weekly_percent"]), (10.0, 77.0))
        self.assertEqual((codex["session_percent"], codex["weekly_percent"]), (None, 6.0))
        image = Image.open(io.BytesIO(render_page(snapshot, 0, "pixel")))
        self.assertEqual(image.size, (240, 240))


class ConfigTests(unittest.TestCase):
    def check(self, **account):
        base = {"key": "a", "alias": "A", "provider": "claude", "email": "user@example.com"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"accounts": [dict(base, **account)]}), encoding="utf-8")
            return load_config(path)

    def test_accepts_cli_or_url_for_verified_providers(self):
        self.check(codexbar_command="~/.local/opt/codexbar/codexbar", codexbar_source="oauth")
        self.check(provider="codex", codexbar_url="http://127.0.0.1:8080/usage")
        self.check(codexbar_url="http://127.0.0.1:8080/usage?provider=claude")

    def test_url_carries_no_credentials(self):
        for url in ("http://user:secret@127.0.0.1:8080/usage", "http://127.0.0.1:8080/usage?token=secret",
                    "http://127.0.0.1:8080/usage#secret"):
            with self.assertRaises(ValueError, msg=url):
                self.check(codexbar_url=url)

    def test_rejects_unclear_or_unverified_input(self):
        for account in ({"provider": "grok", "codexbar_command": "codexbar"},
                        {"codexbar_command": "codexbar", "codexbar_url": "http://127.0.0.1:8080/usage"},
                        {"codexbar_url": "file:///etc/passwd"},
                        {"codexbar_command": ""},
                        {"codexbar_command": "codexbar", "codexbar_source": "browser"},
                        {"codexbar_url": "http://127.0.0.1:8080/usage", "codexbar_source": "oauth"},
                        {"codexbar_source": "oauth"},
                        {"codexbar_command": "codexbar", "snapshot_file": "/tmp/snapshot.json"}):
            with self.assertRaises(ValueError, msg=account):
                self.check(**account)


if __name__ == "__main__":
    unittest.main()
