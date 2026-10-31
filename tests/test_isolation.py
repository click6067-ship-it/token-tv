"""One account's trouble stays that account's: the others still update, draw and reach the clock."""
import json
import time
import unittest
from unittest.mock import patch

from token_tv import sources
from token_tv.display import render_page
from token_tv.state import UsageStore
from token_tv.usage import FormatChanged, normalize_claude, normalize_codex, normalize_codexbar, normalize_grok

PROFILE = {'account': {'email': 'user@example.com'}}
CLAUDE = {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'user@example.com', 'source_home': '/unused'}
CODEX = {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'user@example.com', 'source_home': '/unused'}


def codex(used):
    return {'rateLimits': {'primary': {'usedPercent': used, 'windowDurationMins': 300, 'resetsAt': time.time() + 3600}}}


class IsolationTests(unittest.TestCase):
    def read_both(self, claude, codex_reply):
        with patch.object(sources, 'claude_payload', **claude), patch.object(sources, 'codex_payload', return_value=codex_reply):
            self.store.refresh()
        return self.store.snapshot()

    def setUp(self):
        self.store = UsageStore([dict(CLAUDE), dict(CODEX)])
        first = self.read_both({'return_value': (PROFILE, {'five_hour': {'utilization': 20}})}, codex(40))
        self.assertEqual((first['accounts']['claude_a']['session_percent'], first['accounts']['codex_a']['session_percent']),
                         (20.0, 40.0))
        self.before = render_page(first, 0, 'arcade')

    def test_a_changed_reply_spoils_only_its_own_account(self):
        # Claude's five-hour window comes as a list where an object was: a changed format.
        after = self.read_both({'return_value': (PROFILE, {'five_hour': ['changed-shape']})}, codex(73))
        claude, other = after['accounts']['claude_a'], after['accounts']['codex_a']
        self.assertEqual((other['status'], other['session_percent']), ('ok', 73.0))  # the healthy one moves on
        self.assertEqual((claude['status'], claude['error_code'], claude['session_percent']), ('stale', 'format_changed', 20.0))
        self.assertNotEqual(render_page(after, 0, 'arcade'), self.before)  # and the clock gets the new picture

    def test_an_unexpected_error_is_named_by_its_type_only(self):
        after = self.read_both({'side_effect': RuntimeError('SECRET_SENTINEL /home/me/.claude')}, codex(73))
        claude = after['accounts']['claude_a']
        self.assertEqual((claude['status'], claude['error_code']), ('stale', 'unexpected:RuntimeError'))
        self.assertEqual(after['accounts']['codex_a']['session_percent'], 73.0)
        self.assertNotIn('SECRET_SENTINEL', json.dumps(after))

    def test_an_account_never_read_stays_a_dash(self):
        store = UsageStore([dict(CLAUDE), dict(CODEX)])
        with patch.object(sources, 'claude_payload', side_effect=RuntimeError('SECRET_SENTINEL')), \
                patch.object(sources, 'codex_payload', return_value=codex(73)):
            store.refresh()
        claude = store.snapshot()['accounts']['claude_a']
        self.assertEqual((claude['status'], claude['error_code'], claude['windows']), ('error', 'unexpected:RuntimeError', []))
        self.assertIsNone(claude['session_percent'])  # a dash, never 0%

    def test_a_reader_that_fails_outright_fails_only_its_account(self):
        def fetch(account):
            if account['key'] == 'claude_a':
                raise KeyError('SECRET_SENTINEL')
            return {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'status': 'ok', 'fetched_at': time.time(),
                    'windows': [{'label': '5H', 'used_percent': 73.0, 'resets_at': None, 'duration_minutes': 300}]}
        store = UsageStore([dict(CLAUDE), dict(CODEX)], fetch=fetch)
        store.refresh()
        after = store.snapshot()
        self.assertEqual(after['accounts']['claude_a']['error_code'], 'unexpected:KeyError')
        self.assertEqual(after['accounts']['codex_a']['session_percent'], 73.0)
        self.assertGreater(store.updated_at, 0)
        self.assertNotIn('SECRET_SENTINEL', json.dumps(after))


class ShapeTests(unittest.TestCase):
    def test_every_reader_checks_the_shape_it_reads(self):
        for normalize, data in ((normalize_claude, {'five_hour': ['x']}), (normalize_claude, ['x']),
                                (normalize_codex, {'rateLimits': ['x']}), (normalize_codex, {'rateLimits': {'primary': 'x'}}),
                                (normalize_codexbar, {'provider': 'codex', 'usage': {'primary': ['x']}}),
                                (normalize_grok, {'config': ['changed-shape']}),
                                (normalize_grok, {'config': {'currentPeriod': 'x'}})):
            with self.subTest(normalize=normalize.__name__, data=data), self.assertRaises(FormatChanged):
                normalize(data)

    def test_missing_parts_are_still_missing_readings_not_a_changed_format(self):
        self.assertEqual(normalize_claude({'five_hour': None}), [])
        self.assertEqual(normalize_codex({}), [])
        self.assertEqual(normalize_grok({'config': None}), [])

    def test_a_changed_format_is_reported_as_such(self):
        with patch.object(sources, 'grok_identity', return_value='user@example.com'), \
                patch.object(sources, 'grok_payload', return_value={'config': ['changed-shape']}):
            row = sources.fetch_account({'key': 'grok_a', 'alias': 'GROK A', 'provider': 'grok', 'email': 'user@example.com',
                                         'source_home': '/unused'})
        self.assertEqual((row['status'], row['error_code'], row['windows']), ('error', 'format_changed', []))
        with patch.object(sources, 'claude_payload', return_value=(['not', 'a', 'profile'], {})):
            row = sources.fetch_account(dict(CLAUDE))
        self.assertEqual((row['status'], row['error_code']), ('error', 'format_changed'))


if __name__ == '__main__':
    unittest.main()
