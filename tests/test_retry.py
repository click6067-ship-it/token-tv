"""A provider that asks to wait is left alone for that long, that account only; the owner sees why."""
import json
import time
import unittest
from email.message import Message
from email.utils import formatdate
from unittest.mock import patch
from urllib.error import HTTPError

from token_tv import live, sources
from token_tv.state import BACKOFF_CAP, UsageStore, backoff

T = 1793000000.0
PROFILE = {'account': {'email': 'user@example.com'}}
CLAUDE = {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'user@example.com', 'source_home': '/unused'}
CODEX = {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'user@example.com', 'source_home': '/unused'}


def limited(code=429, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    return HTTPError('https://api.invalid/usage', code, 'synthetic', headers, None)


def codex(used=40):
    return {'rateLimits': {'primary': {'usedPercent': used, 'windowDurationMins': 300, 'resetsAt': T + 3600}}}


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.calls = {'claude_a': [], 'codex_a': []}
        self.claude = [(PROFILE, {'five_hour': {'utilization': 20}})]  # what each Claude read gives, the last one again

    def run_at(self, store, elapsed):
        def claude(account):
            self.calls['claude_a'].append(elapsed)
            reply = self.claude[0] if len(self.claude) == 1 else self.claude.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        def codex_reply(account):
            self.calls['codex_a'].append(elapsed)
            return codex()
        with patch('time.monotonic', return_value=1000 + elapsed), patch('time.time', return_value=T + elapsed), \
                patch.object(sources, 'claude_payload', side_effect=claude), \
                patch.object(sources, 'codex_payload', side_effect=codex_reply):
            store.refresh()
            return store.snapshot()

    def test_retry_after_seconds_is_honoured_for_that_account_only(self):
        store = UsageStore([dict(CLAUDE), dict(CODEX)])
        self.run_at(store, 0)
        self.claude = [limited(429, '120'), (PROFILE, {'five_hour': {'utilization': 30}})]
        after = self.run_at(store, 60)
        row = after['accounts']['claude_a']
        self.assertEqual((row['status'], row['error_code'], row['retry_at']), ('stale', 'http_429', int(T + 60 + 120)))
        for elapsed in (120, 179):
            self.run_at(store, elapsed)
        self.assertEqual(self.calls['claude_a'], [0, 60])  # nothing before the time it asked for
        self.assertEqual(self.calls['codex_a'], [0, 60, 120, 179])  # the other account goes on
        fresh = self.run_at(store, 180)
        self.assertEqual(self.calls['claude_a'], [0, 60, 180])
        self.assertEqual((fresh['accounts']['claude_a']['status'], fresh['accounts']['claude_a']['session_percent']), ('ok', 30.0))
        self.assertNotIn('retry_at', fresh['accounts']['claude_a'])

    def test_the_time_the_service_gave_comes_before_claudes_own_five_minutes(self):
        from token_tv.state import MIN_FETCH_SECONDS
        store = UsageStore([dict(CLAUDE)], min_fetch_seconds=MIN_FETCH_SECONDS)
        self.claude = [limited(429, '120'), (PROFILE, {'five_hour': {'utilization': 30}})]
        for elapsed in (0, 60, 119, 120):
            self.run_at(store, elapsed)
        self.assertEqual(self.calls['claude_a'], [0, 120])  # at the time it gave, not five minutes after the last try
        for elapsed in (180, 300):
            self.run_at(store, elapsed)
        self.assertEqual(self.calls['claude_a'], [0, 120])  # then its usual five minutes again
        self.run_at(store, 420)
        self.assertEqual(self.calls['claude_a'], [0, 120, 420])

    def test_retry_after_as_a_date_and_a_busy_service(self):
        store = UsageStore([dict(CLAUDE)])
        self.claude = [limited(503, formatdate(T + 300, usegmt=True))]
        row = self.run_at(store, 0)['accounts']['claude_a']
        self.assertEqual((row['status'], row['error_code'], row['retry_at']), ('error', 'http_503', int(T + 300)))
        self.run_at(store, 299)
        self.assertEqual(self.calls['claude_a'], [0])
        self.run_at(store, 300)
        self.assertEqual(self.calls['claude_a'], [0, 300])

    def test_a_computer_waking_from_sleep_tries_again_once_the_wall_clock_has_passed(self):
        store = UsageStore([dict(CLAUDE)])
        self.claude = [limited(429, '600')]
        self.run_at(store, 0)
        with patch('time.monotonic', return_value=1000 + 5), patch('time.time', return_value=T + 3 * 3600), \
                patch.object(sources, 'claude_payload', return_value=(PROFILE, {'five_hour': {'utilization': 9}})) as call:
            store.refresh()
        call.assert_called_once()  # monotonic time stood still while asleep; the wall clock says it is time

    def test_without_retry_after_the_wait_grows_and_stops_growing_and_success_resets_it(self):
        self.assertEqual([backoff(n) for n in range(1, 8)], [0, 60, 120, 240, 480, BACKOFF_CAP, BACKOFF_CAP])
        store = UsageStore([dict(CLAUDE), dict(CODEX)])
        self.claude = [limited(500)]
        elapsed, tries = 0, []
        while elapsed < 6 * 3600:
            before = len(self.calls['claude_a'])
            self.run_at(store, elapsed)
            if len(self.calls['claude_a']) > before:
                tries.append(elapsed)
            elapsed += 60
        gaps = [b - a for a, b in zip(tries, tries[1:])]
        self.assertEqual(gaps[:5], [60, 60, 120, 240, 480])
        self.assertTrue(gaps[5:] and max(gaps) <= BACKOFF_CAP + 60)  # bounded: at most a quarter of an hour apart
        self.assertEqual(len(self.calls['codex_a']), 6 * 60)  # never slowed by its neighbour
        self.claude = [(PROFILE, {'five_hour': {'utilization': 30}})]
        while len(self.calls['claude_a']) == len(tries):
            last = self.run_at(store, elapsed)
            elapsed += 60
        self.assertEqual(last['accounts']['claude_a']['status'], 'ok')
        self.claude = [limited(500)]
        start = len(self.calls['claude_a'])
        for step in range(3):
            self.run_at(store, elapsed + 60 * step)
        self.assertEqual(len(self.calls['claude_a']) - start, 3)  # after a success the next failures start over


class HealthTests(unittest.TestCase):
    def health(self, rows):
        store = UsageStore([{'key': k, 'alias': k.upper(), 'provider': 'codex'} for k in rows],
                           fetch=lambda account: dict(rows[account['key']], key=account['key'], alias=account['key'].upper(),
                                                      provider='codex', fetched_at=time.time()))
        store.refresh()
        return live.health(store.snapshot())

    def test_ok_only_when_every_account_is_fresh(self):
        window = [{'label': '5H', 'used_percent': 10.0, 'resets_at': None, 'duration_minutes': 300}]
        report = self.health({'a': {'status': 'ok', 'windows': window}})
        self.assertEqual((report['status'], report['accounts']['a']['freshness']), ('ok', 'fresh'))
        report = self.health({'a': {'status': 'ok', 'windows': window},
                              'b': {'status': 'stale', 'error_code': 'codexbar_old', 'windows': window, 'measured_at': time.time() - 2000},
                              'c': {'status': 'stale', 'error_code': 'freshness_unknown', 'windows': window},
                              'd': {'status': 'auth_required', 'windows': []}})
        self.assertEqual(report['status'], 'degraded')
        self.assertEqual({k: v['freshness'] for k, v in report['accounts'].items()},
                         {'a': 'fresh', 'b': 'stale', 'c': 'unknown', 'd': 'none'})
        self.assertNotIn('windows', json.dumps(report))  # how each is, not what it reads

    def test_health_still_answers_200(self):
        import io
        from email.message import Message as Headers
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}])
        handler = live.handler(store)
        request = handler.__new__(handler)
        request.path, request.command, request.request_version = '/health', 'GET', 'HTTP/1.1'
        request.requestline = 'GET /health HTTP/1.1'
        request.headers = Headers()
        request.headers['Host'] = '127.0.0.1:8787'
        request.rfile, request.wfile = io.BytesIO(), io.BytesIO()
        request.do_GET()
        head, body = request.wfile.getvalue().split(b'\r\n\r\n', 1)
        self.assertIn(b' 200 ', head.split(b'\r\n')[0])
        self.assertEqual(json.loads(body)['accounts']['a']['freshness'], 'unknown')  # still loading


class ReasonTests(unittest.TestCase):
    def reason(self, **row):
        base = {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source': 'mini', 'windows': [],
                'fetched_at': T, 'last_success_at': T - 3600}
        with patch('token_tv.autostart.how', return_value='npx token-tv'):
            return live.reason_of(dict(base, **row))

    def test_each_failure_says_what_to_do(self):
        self.assertIsNone(self.reason(status='ok'))
        login = self.reason(status='stale', error_code='http_401')
        self.assertIn('npx token-tv connect', login['text'])
        self.assertIn('--account claude_a', login['text'])
        self.assertEqual(self.reason(status='auth_required', error_code='auth_required')['text'], login['text'])
        busy = self.reason(status='stale', error_code='http_429', retry_at=int(T + 600))
        self.assertEqual((busy['text'], busy['at']), ('Rate limited until {at}', int(T + 600)))
        changed = self.reason(status='stale', error_code='format_changed')
        self.assertIn('npx token-tv update', changed['text'])
        self.assertIn('update', self.reason(status='error', error_code='unexpected:AttributeError')['text'])
        old = self.reason(status='stale', error_code='codexbar_old', source='codexbar')
        self.assertEqual(old['at'], T - 3600)
        self.assertIn('CodexBar', self.reason(status='stale', error_code='freshness_unknown', source='codexbar')['text'])
        self.assertIn('CodexBar', self.reason(status='stale', error_code='auth_required', source='codexbar')['text'])
        for row in ({'status': 'stale', 'error_code': 'snapshot_old'}, {'status': 'error', 'error_code': 'timeout'},
                    {'status': 'identity_mismatch', 'error_code': 'identity_mismatch'}):
            self.assertTrue(self.reason(**row)['text'], row)

    def test_the_dashboard_shows_the_reason_and_writes_its_time(self):
        from token_tv.web_assets import asset
        script = asset('/assets/app.js')[0].decode()
        self.assertIn('a.reason', script)
        self.assertIn("'{at}'", script)  # the time comes from the server as a timestamp, shown in the reader's own clock


if __name__ == '__main__':
    unittest.main()
