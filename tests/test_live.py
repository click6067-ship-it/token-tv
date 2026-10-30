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
            path.write_text(json.dumps({"accounts": [{"key": "a", "alias": "A", "provider": "claude", "password": "DO-NOT-USE"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_grok_owner_identity_must_match_expected_email(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            path.write_text(json.dumps({"issuer::client": {"email": "owner@example.com", "key": "NEVER-EXPORT", "refresh_token": "NEVER-EXPORT"}}), encoding="utf-8")
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
            path.write_text(json.dumps({"accounts": {"a": row}}), encoding="utf-8")
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

    def test_each_account_gets_a_row_and_more_than_four_keep_the_most_relevant(self):
        def account(provider, alias, status="ok", used=94):
            return {"provider": provider, "alias": alias, "status": status,
                    "windows": [] if status != "ok" else [{"label": "WEEK", "used_percent": used, "resets_at": None}]}
        snapshot = {"accounts": {
            "ca": account("claude", "CLAUDE A"), "cb": account("claude", "CLAUDE B", used=20),
            "cc": account("claude", "CLAUDE C"), "xa": account("codex", "CODEX A"),
            "ga": account("grok", "GROK A", "auth_required"), "gb": account("grok", "GROK B", used=50)}}
        rows = overview_rows(snapshot)  # four rows: the fullest accounts with a reading, in service order
        self.assertEqual([r["key"] for r in rows], ["ca", "cc", "xa", "gb"])
        snapshot["accounts"]["cb"]["active"] = True  # an account in use takes a row first
        self.assertEqual([r["key"] for r in overview_rows(snapshot)], ["ca", "cb", "cc", "xa"])
        two = {"accounts": {"xa": account("codex", "CODEX A"), "xb": account("codex", "CODEX B")}}
        self.assertEqual([r["key"] for r in overview_rows(two)], ["xa", "xb"])  # two of one service, two rows
        self.assertEqual(len(snapshot["accounts"]), 6)
        self.assertEqual(render_page(snapshot, 0), render_page(snapshot, 1))

    def test_roomy_rows_show_both_windows_and_crowded_ones_the_week(self):
        from token_tv.display import shown_windows, slots
        row = {"windows": [{"label": "WEEK", "used_percent": 80}, {"label": "5H", "used_percent": 20}]}
        self.assertEqual([w["label"] for w in shown_windows(row, 1)], ["5H", "WEEK"])
        self.assertEqual([w["label"] for w in shown_windows(row, 2)], ["5H", "WEEK"])
        self.assertEqual([w["label"] for w in shown_windows(row, 3)], ["WEEK"])
        self.assertEqual([w["label"] for w in shown_windows({"windows": [{"label": "5H", "used_percent": 3}]}, 4)], ["5H"])
        self.assertEqual(shown_windows({"windows": []}, 1), [])
        self.assertEqual([(s.y, s.h) for s in slots(3)], [(3, 76), (82, 76), (161, 76)])  # three rows as always
        for count in (1, 2, 4):
            places = slots(count)
            self.assertEqual(len(places), count)
            self.assertEqual(places[0].y, 3)
            self.assertLessEqual(places[-1].y + places[-1].h, 3 + 2 * 79 + 76 + 1)

    def test_overview_preserves_quota_period_and_unknown_values(self):
        windows = [{"label": "5H", "used_percent": 2}, {"label": "WEEK", "used_percent": 94}]
        self.assertEqual(primary_window({"windows": windows})["label"], "WEEK")
        self.assertIsNone(primary_window({"windows": []}))
        self.assertEqual(primary_window({"windows": [{"label": "BUDGET", "used_percent": 100}]})["label"], "BUDGET")


if __name__ == "__main__":
    unittest.main()


class LoopTimingTests(unittest.TestCase):
    def test_a_new_picture_goes_as_the_loop_ends(self):
        from token_tv.live import until_loop_end
        shown = {'at': 100.0, 'loop': 8.4}
        self.assertAlmostEqual(until_loop_end(shown, 101.0), 7.4)  # 1 s in
        self.assertAlmostEqual(until_loop_end(shown, 100.0 + 2 * 8.4), 0)  # right at the end of the second loop
        self.assertEqual(until_loop_end({'at': None, 'loop': None}, 5), 0)


class RelocateTests(unittest.TestCase):
    def test_a_clock_with_a_new_address_is_followed_only_when_it_is_the_one_clock(self):
        from token_tv.live import relocate
        old = 'http://192.168.0.50'
        self.assertEqual(relocate(old, lambda: ['http://192.168.0.77']), 'http://192.168.0.77')
        self.assertIsNone(relocate(old, lambda: [old]))  # still there: just busy
        self.assertIsNone(relocate(old, lambda: []))  # off
        self.assertIsNone(relocate(old, lambda: ['http://192.168.0.77', 'http://192.168.0.78']))  # which one?


class LockTests(unittest.TestCase):
    def test_one_tokentv_per_config(self):
        import subprocess, sys, tempfile
        from token_tv.live import hold_lock
        folder = Path(tempfile.mkdtemp())
        self.assertTrue(hold_lock(folder))
        other = subprocess.run([sys.executable, '-c', 'import sys; from pathlib import Path; from token_tv.live import hold_lock; '
                                'sys.exit(0 if hold_lock(Path(sys.argv[1])) else 3)', str(folder)], capture_output=True)
        self.assertEqual(other.returncode, 3)  # a second process with the same config is refused


class LostClockTests(unittest.TestCase):
    def test_searches_back_off_and_the_same_place_is_not_a_move(self):
        from token_tv.live import lost_search_due, relocate, same_place
        self.assertEqual([n for n in range(1, 30) if lost_search_due(n, 0.0, 100.0)], [3, 6, 12, 24])
        self.assertTrue(lost_search_due(30, 0.0, 2000.0))
        self.assertTrue(same_place('http://localhost:18001', 'http://127.0.0.1:18001'))
        self.assertTrue(same_place('http://127.0.0.1:80', 'http://127.0.0.1'))
        self.assertIsNone(relocate('http://localhost:18001', lambda: ['http://127.0.0.1:18001']))

    def test_each_reason_has_words_for_the_dashboard(self):
        from urllib.error import HTTPError, URLError
        from token_tv.device import ClockFull, NotAClock
        from token_tv.live import problem_of
        self.assertEqual(problem_of(URLError('down')), 'no_answer')
        self.assertEqual(problem_of(NotAClock('x')), 'not_a_clock')
        self.assertEqual(problem_of(ClockFull(80000, 20000)), 'clock_full')
        self.assertEqual(problem_of(HTTPError('u', 404, 'nf', {}, None)), 'not_a_clock')
        self.assertEqual(problem_of(ValueError('The clock did not keep the whole picture')), 'short_copy')


class GuardTests(unittest.TestCase):
    def test_the_dashboard_answers_only_by_this_computers_names(self):
        import http.client, threading
        from token_tv import live
        from token_tv.state import UsageStore
        store = UsageStore([{'key': 'codex_a', 'alias': 'A', 'provider': 'codex'}], fetch=lambda _: None)
        server = live.QuietServer(('127.0.0.1', 0), live.handler(store))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def status(host):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                conn.request('GET', '/snapshot', headers={'Host': host})
                return conn.getresponse().status
            self.assertEqual(status(f'127.0.0.1:{server.server_port}'), 200)
            self.assertEqual(status(f'localhost:{server.server_port}'), 200)
            self.assertEqual(status('evil.example:80'), 403)  # a page that renamed itself to 127.0.0.1
        finally:
            server.shutdown()

    def test_one_tokentv_per_clock_whatever_the_config(self):
        import subprocess, sys
        from token_tv.live import hold_clock
        url = 'http://127.0.0.1:18999'
        self.assertTrue(hold_clock(url))
        other = subprocess.run([sys.executable, '-c', 'import sys; from token_tv.live import hold_clock; '
                                'sys.exit(0 if hold_clock(sys.argv[1]) else 3)', 'http://localhost:18999'], capture_output=True)
        self.assertEqual(other.returncode, 3)  # the same clock by another name, from another process

    def test_a_clock_lock_is_held_once_per_process_and_can_be_let_go(self):
        import subprocess, sys
        from token_tv.live import hold_clock, let_go
        url = 'http://127.0.0.1:18998'
        other = [sys.executable, '-c', 'import sys; from token_tv.live import hold_clock; '
                 'sys.exit(0 if hold_clock(sys.argv[1]) else 3)', url]
        path = hold_clock(url)
        self.assertTrue(path)
        self.assertEqual(hold_clock(url), path)  # this process again, say once the config is read again
        self.assertEqual(subprocess.run(other, capture_output=True).returncode, 3)
        let_go(path)  # another clock now
        self.assertEqual(subprocess.run(other, capture_output=True).returncode, 0)

    def test_a_lock_folder_it_cannot_write_is_no_reason_to_stop(self):
        import contextlib, io, os, tempfile
        from token_tv import live
        if hasattr(os, 'geteuid') and os.geteuid() == 0 or os.name == 'nt':
            self.skipTest('root writes anywhere, and Windows has no read-only folders')
        folder = Path(tempfile.mkdtemp())
        folder.chmod(0o555)  # another account's folder, say
        self.addCleanup(folder.chmod, 0o755)
        said = io.StringIO()
        with patch.object(live, 'clock_lock', lambda url: folder / 'clock-x.lock'), contextlib.redirect_stdout(said):
            self.assertTrue(live.hold_clock('http://127.0.0.1:18997'))
        self.assertIn('runs without that check', said.getvalue())

    def test_an_https_address_saved_before_is_read_as_the_http_the_clock_speaks(self):
        from token_tv.live import plain
        self.assertEqual(plain('HTTPS://192.168.0.50:8080'), 'http://192.168.0.50:8080')
        self.assertEqual((plain('http://192.168.0.50'), plain(None)), ('http://192.168.0.50', None))

    def test_a_model_guessed_while_nothing_answers_says_so(self):
        from token_tv.device import open_display
        self.assertTrue(open_display('http://127.0.0.1:9').guessed)  # nothing listens on the discard port

    def test_an_answer_that_is_not_a_clocks_list_counts_as_not_a_clock(self):
        import json
        from token_tv.live import problem_of
        self.assertEqual(problem_of(json.JSONDecodeError('x', '<html>', 0)), 'not_a_clock')
