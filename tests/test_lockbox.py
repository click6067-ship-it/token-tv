import base64
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from token_tv import arcade, lockbox
from token_tv.sample import D, snapshot
from token_tv.state import UsageStore


def at(hour, minute=0, day=29):
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


def content(name, tier='unique'):
    return {'name': name, 'tier': tier, 'seconds': 6, 'height': 71, 'strip': strip(len(name))}


def strip(frames):
    image = Image.new('RGB', (120, 71 * frames), (9, 9, 9))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


class LockboxTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.bundle = Path(self.dir.name) / 'eggs.bin'
        salt = b'0123456789abcdef'
        boxes = [lockbox.seal(salt, {'hour=10', 'minute=7'}, content('late'), chance=1, cooldown_days=7),
                 lockbox.seal(salt, {'codex:crossed_70'}, content('jump'), chance=1, cooldown_days=7),
                 lockbox.seal(salt, {'codex:active'}, content('legendary', 'legend'), chance=1, cooldown_days=28),
                 lockbox.seal(salt, {'weekend=yes'}, content('maybe'), chance=.05, cooldown_days=7)]
        self.bundle.write_text(json.dumps({'salt': salt.hex(), 'boxes': boxes}))
        self.rolls = []
        self.box = lambda: lockbox.Lockbox(Path(self.dir.name) / 'history.json', self.bundle,
                                           roll=lambda: self.rolls.pop(0) if self.rolls else 0.0)

    def tearDown(self):
        self.dir.cleanup()

    def data(self, now, **row):
        out = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)])])
        out['accounts']['codex_a'].update(row)
        return out

    def test_the_bundle_says_nothing_readable_about_what_opens_a_box(self):
        text = self.bundle.read_text()
        for word in ('hour', 'minute', 'jump', 'late', 'legendary', 'codex'):
            self.assertNotIn(word, text)

    def test_a_box_opens_only_in_its_situation_and_then_rests(self):
        locks = self.box()
        self.assertIsNone(locks.pick(self.data(at(10, 6)), at(10, 6)))
        box = locks.pick(self.data(at(10, 7)), at(10, 7))
        self.assertEqual((box.name, box.tier, box.key, len(box.frames)), ('late', 'unique', 'codex_a', 4))
        self.assertEqual(box.frames[0].size, (120, 71))
        self.assertIsNone(locks.pick(self.data(at(10, 7, day=30)), at(10, 7, day=30)))  # a week's cooldown
        self.assertEqual(locks.pick(self.data(at(10, 7, day=36)), at(10, 7, day=36)).name, 'late')  # a week on

    def test_news_counts_for_ten_minutes_and_hidden_ones_keep_apart_unless_legendary(self):
        locks = self.box()
        now = at(12)
        news = dict(news=[{'kind': 'crossed', 'value': 70, 'at': now}])
        self.assertEqual(locks.pick(self.data(now, **news), now).name, 'jump')
        self.assertIsNone(locks.pick(self.data(now + 60, **news), now + 60))  # thirty minutes apart
        legend = locks.pick(self.data(now + 120, active=True), now + 120)
        self.assertEqual(legend.tier, 'legend')  # a legend does not wait
        stale = dict(news=[{'kind': 'crossed', 'value': 70, 'at': now}])
        self.assertNotIn('codex:crossed_70', lockbox.facts(self.data(now + 700, **stale), locks.history, now + 700)['codex_a'])

    def test_one_roll_each_time_a_situation_comes_about_and_sure_once_twice_its_share_has_passed(self):
        locks = self.box()
        saturday = time.mktime((2026, 10, 31, 15, 0, 0, 0, 0, -1))
        data = locks.history.data
        data['met'] = {'other': {'first': saturday - 70 * D, 'count': 70, 'tier': 'unique'}}  # a daily one
        data['held'] = {'other': saturday}
        self.rolls[:] = [.99]
        self.assertIsNone(locks.pick(self.data(saturday), saturday))  # missed (two uniques met: 16 days each)
        self.rolls[:] = [.0, .0]
        self.assertIsNone(locks.pick(self.data(saturday + 60), saturday + 60))  # the same afternoon: no new roll
        self.assertEqual(self.rolls, [.0, .0])
        week = 7 * D
        for n in range(1, 5):  # more Saturday afternoons, every roll a miss
            data['held']['other'] = saturday + n * week
            self.rolls[:] = [.99]
            self.assertIsNone(locks.pick(self.data(saturday + n * week), saturday + n * week))
        data['held']['other'] = saturday + 5 * week
        self.rolls[:] = [.99]
        box = locks.pick(self.data(saturday + 5 * week), saturday + 5 * week)
        self.assertEqual(box.name, 'maybe')  # 35 days on, past twice its share: sure

    def test_the_odds_follow_how_often_a_situation_comes_about(self):
        self.assertAlmostEqual(lockbox.odds(14, 14, 12, first=False), 1 / 12)  # daily, one opening in twelve days
        self.assertAlmostEqual(lockbox.odds(14, 14, 12, first=True), 2 / 12)
        self.assertAlmostEqual(lockbox.odds(2, 14, 12, first=False), 7 / 12)  # weekly: most times it comes
        self.assertEqual(lockbox.odds(1, 0, 3, first=False), 1.0)  # new to the clock, and its tier's only box

    def test_a_tier_shares_its_pace_and_keeps_apart(self):
        self.assertAlmostEqual(lockbox.shares([1, 1], 8), 16)  # two daily boxes: each every 16 days
        self.assertAlmostEqual(lockbox.shares([.01, 1], 8), 1 / (1 / 8 - .01))  # a rare one opens every time
        self.assertEqual(lockbox.shares([.01, .02], 8), 0)  # both too rare for the pace: every time
        locks = self.box()
        saturday = time.mktime((2026, 10, 31, 15, 0, 0, 0, 0, -1))
        locks.history.data['spaced'] = {'unique': saturday}
        self.rolls[:] = [.0, .0]
        self.assertIsNone(locks.pick(self.data(saturday + 7 * D + 3600), saturday + 7 * D + 3600 - 2 * D))  # kept apart
        self.assertEqual(self.rolls, [.0, .0])

    def test_two_won_together_keep_their_tier_apart(self):
        salt = b'0123456789abcdef'
        boxes = [lockbox.seal(salt, {'claude:idle'}, content('one', 'rare'), chance=.5, cooldown_days=3),
                 lockbox.seal(salt, {'codex:idle'}, content('two', 'rare'), chance=.5, cooldown_days=3)]
        self.bundle.write_text(json.dumps({'salt': salt.hex(), 'boxes': boxes}))
        locks = self.box()
        now = at(12)
        data = snapshot(now, [('claude_a', 'A', 'claude', [('WEEK', 50, 3 * D)]), ('codex_a', 'B', 'codex', [('WEEK', 50, 3 * D)])])
        for row in data['accounts'].values():
            row['active'] = False  # both at rest: both situations hold
        first = locks.pick(data, now)
        self.assertIsNotNone(first)
        self.assertIsNone(locks.pick(data, now + lockbox.GAP + 60))  # the other rare waits out the day

    def test_a_legend_plays_in_its_minute(self):
        locks = self.box()
        now = at(12)
        self.rolls[:] = [.0, .99]  # won; a delay roll that would push anything else minutes on
        self.assertEqual(locks.pick(self.data(now, active=True), now).tier, 'legend')

    def test_a_pick_that_never_reached_the_clock_is_taken_back(self):
        locks = self.box()
        self.assertEqual(locks.pick(self.data(at(10, 7)), at(10, 7)).name, 'late')
        locks.forget()
        self.assertEqual(locks.collection()['hidden'], 4)
        self.assertEqual(locks.pick(self.data(at(10, 7, day=30)), at(10, 7, day=30)).name, 'late')  # no cooldown

    def test_a_win_waits_a_moment_while_its_situation_still_holds(self):
        locks = self.box()
        saturday = time.mktime((2026, 10, 31, 15, 0, 0, 0, 0, -1))
        self.rolls[:] = [.0, .5]  # won; plays half the delay later
        self.assertIsNone(locks.pick(self.data(saturday), saturday))
        self.assertIsNone(locks.pick(self.data(saturday + 60), saturday + 60))
        box = locks.pick(self.data(saturday + lockbox.DELAY / 2 + 1), saturday + lockbox.DELAY / 2 + 1)
        self.assertEqual(box.name, 'maybe')

    def test_found_scenes_fill_the_collection_and_play_again(self):
        locks = self.box()
        self.assertEqual(locks.collection(), {'found': [], 'total': 4, 'hidden': 4})
        locks.pick(self.data(at(10, 7)), at(10, 7))
        book = locks.collection()
        self.assertEqual((book['hidden'], len(book['found'])), (3, 1))
        seen = book['found'][0]
        self.assertEqual((seen['name'], seen['tier'], seen['count']), ('late', 'unique', 1))
        self.assertNotIn('combo', seen)  # the page never learns what opened it
        again = locks.replay(seen['check'])
        self.assertEqual((again.name, again.key), ('late', 'codex_a'))
        self.assertIsNone(locks.replay('not-a-box'))

    def test_the_dashboard_lists_the_collection_and_queues_a_replay(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        from token_tv import live
        locks = self.box()
        locks.pick(self.data(at(10, 7)), at(10, 7))
        check = locks.collection()['found'][0]['check']
        store = UsageStore([{'key': 'codex_a', 'alias': 'A', 'provider': 'codex'}], fetch=lambda _: None)
        replays, wake = [], threading.Event()
        server = ThreadingHTTPServer(('127.0.0.1', 0), live.handler(store, None, locks, replays, wake))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def ask(method, path, body=None):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                conn.request(method, path, body, {'Content-Type': 'application/json'} if body else {})
                reply = conn.getresponse()
                return reply.status, reply.read()
            status, body = ask('GET', '/collection')
            self.assertEqual((status, json.loads(body)['hidden']), (200, 3))
            self.assertEqual(ask('POST', '/collection/replay', json.dumps({'check': check}))[0], 200)
            self.assertEqual((replays, wake.is_set()), ([check], True))
            self.assertEqual(ask('POST', '/collection/replay', json.dumps({'check': 'nope'}))[0], 400)
        finally:
            server.shutdown()

    def test_a_replay_with_no_clock_says_so_and_queues_nothing(self):
        import http.client
        import threading
        from token_tv import live
        locks = self.box()
        locks.pick(self.data(at(10, 7)), at(10, 7))
        check = locks.collection()['found'][0]['check']
        config = Path(self.dir.name) / 'config.json'
        config.write_text(json.dumps({'display_style': 'arcade', 'accounts': [{'key': 'codex_a', 'alias': 'A', 'provider': 'codex'}]}))
        preferences = live.DisplayPreferences(config, json.loads(config.read_text()))
        store = UsageStore([{'key': 'codex_a', 'alias': 'A', 'provider': 'codex'}], fetch=lambda _: None)
        replays = []
        server = live.QuietServer(('127.0.0.1', 0), live.handler(store, preferences, locks, replays, threading.Event()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            conn.request('POST', '/collection/replay', json.dumps({'check': check}), {'Content-Type': 'application/json'})
            reply = conn.getresponse()
            self.assertEqual(reply.status, 409)
            self.assertIn(b'No clock connected', reply.read())
            self.assertEqual(replays, [])
        finally:
            server.shutdown()

    def test_a_replay_waits_for_the_clock_to_take_a_first_picture(self):
        import http.client
        import threading
        from token_tv import live
        locks = self.box()
        locks.pick(self.data(at(10, 7)), at(10, 7))
        check = locks.collection()['found'][0]['check']
        config = Path(self.dir.name) / 'config.json'
        config.write_text(json.dumps({'display_style': 'arcade', 'device_url': 'http://127.0.0.1:9',
                                      'accounts': [{'key': 'codex_a', 'alias': 'A', 'provider': 'codex'}]}))
        preferences = live.DisplayPreferences(config, json.loads(config.read_text()))
        store = UsageStore([{'key': 'codex_a', 'alias': 'A', 'provider': 'codex'}], fetch=lambda _: None)
        replays = []
        server = live.QuietServer(('127.0.0.1', 0), live.handler(store, preferences, locks, replays, threading.Event()))
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def replay():
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            conn.request('POST', '/collection/replay', json.dumps({'check': check}), {'Content-Type': 'application/json'})
            reply = conn.getresponse()
            return reply.status, json.loads(reply.read() or b'{}').get('error')
        try:
            self.assertEqual(replay(), (409, 'Waiting for the clock'))  # the first picture is still on its way
            preferences.delivered('arcade', False)
            self.assertEqual(replay(), (409, 'The clock is not answering'))
            self.assertEqual(replays, [])
            preferences.delivered('arcade', True)
            self.assertEqual(replay(), (200, None))
            self.assertEqual(replays, [check])
        finally:
            server.shutdown()

    def test_no_bundle_means_no_hidden_one_offs(self):
        locks = lockbox.Lockbox(Path(self.dir.name) / 'history.json', Path(self.dir.name) / 'none.bin')
        self.assertIsNone(locks.pick(self.data(at(10, 7)), at(10, 7)))


class FactTests(unittest.TestCase):
    def test_the_facts_of_a_moment(self):
        with tempfile.TemporaryDirectory() as directory:
            history = lockbox.History(Path(directory) / 'history.json')
            now = time.mktime((2026, 10, 30, 23, 15, 0, 0, 0, -1))  # a Friday, late
            data = snapshot(now, [(f'{p}_a', p, p, [('WEEK', 40, 3 * D)]) for p in lockbox.PROVIDERS])
            for row in data['accounts'].values():
                row.update(active=True, rose_at=now - 60, active_since=now - 7300)
            found = lockbox.facts(data, history, now)['claude_a']
            for fact in ('hour=23', 'minute=15', 'weekday=fri', 'weekend=no', 'daypart=late', 'date=10-30',
                         'all_active', 'all_used_today', 'claude:active', 'claude:active_1h', 'claude:active_2h',
                         'claude:worked_today'):
                self.assertIn(fact, found)
            self.assertNotIn('codex:active', found)  # an account sees only its own facts and the shared ones

    def test_four_full_weeks_in_a_row_and_the_anniversary(self):
        with tempfile.TemporaryDirectory() as directory:
            history = lockbox.History(Path(directory) / 'history.json')
            start = time.mktime((2026, 10, 5, 12, 0, 0, 0, 0, -1))
            for week in range(4):
                when = start + week * 7 * D
                history.observe(snapshot(when, [('codex_a', 'A', 'codex', [('WEEK', 100, D)])]), when)
            self.assertEqual(history.full_streak('codex_a', start + 3 * 7 * D), 4)
            self.assertEqual(history.full_streak('codex_a', start + 4 * 7 * D), 0)  # this week is not full yet
            for month in range(4):  # a monthly limit counts months, a budget too
                when = time.mktime((2026, 7 + month, 15, 12, 0, 0, 0, 0, -1))
                history.observe(snapshot(when, [('copilot_a', 'C', 'copilot', [('MONTH', 100, None)]),
                                                ('grok_a', 'G', 'grok', [('BUDGET', 100, None)])]), when)
            self.assertEqual(history.full_streak('copilot_a', time.mktime((2026, 10, 20, 9, 0, 0, 0, 0, -1))), 4)
            self.assertEqual(history.full_streak('grok_a', time.mktime((2026, 10, 20, 9, 0, 0, 0, 0, -1))), 4)
            self.assertFalse(history.anniversary(start + 30 * D))
            self.assertTrue(history.anniversary(time.mktime((2027, 10, 5, 9, 0, 0, 0, 0, -1))))

    def test_a_reading_brings_its_news(self):
        readings = [(70, 1), (85, 1), (88, 0)]  # a third and fourth reading follow
        def fetch(_):
            used, count = readings.pop(0)
            return {'key': 'a', 'alias': 'A', 'provider': 'codex', 'status': 'ok', 'fetched_at': time.time(),
                    'windows': [{'label': 'WEEK', 'used_percent': used, 'resets_at': None}],
                    'reset_credits': {'count': count, 'expires_at': time.time() + 3600}}
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}], fetch=fetch)
        store.refresh()
        store.refresh()
        news = {item['kind']: item['value'] for item in store.snapshot()['accounts']['a']['news']}
        self.assertEqual((news['jump'], news['crossed']), (15, 80))
        self.assertTrue(store.snapshot()['accounts']['a']['active_since'])
        store.refresh()
        spent = [i for i in store.snapshot()['accounts']['a']['news'] if i['kind'] == 'ticket_spent']
        self.assertLess(spent[0]['value'], 1)  # spent on its last day
        readings.append((88, 0))
        store.refresh()  # an unchanged reading keeps the news, so a rare event played first does not swallow it
        self.assertTrue(any(i['kind'] == 'ticket_spent' for i in store.snapshot()['accounts']['a']['news']))


class ReviewFixTests(unittest.TestCase):
    def test_a_badge_leaves_the_reset_countdown_alone(self):
        now = time.time()
        data = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)])])
        stage = tuple(Image.new('RGB', (120, 71)) for _ in range(2))
        panel = (120, 172, 240, 240)
        after = arcade.BURST_FRAMES['unique'] + 1  # once the cut-in has gone
        plain = arcade.arcade_frames(data, now)[after].crop(panel)
        boxed = arcade.arcade_frames(data, now, lockbox.Box('x', 'unique', 'codex_a', stage, 6))[after].crop(panel)
        self.assertEqual(plain.tobytes(), boxed.tobytes())

    def test_unique_and_legend_open_with_a_whole_screen_cut_in_and_rare_without(self):
        now = time.time()
        data = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)])])
        stage = tuple(Image.new('RGB', (120, 71)) for _ in range(2))
        header, panel = (0, 0, 240, 26), (0, 172, 240, 240)
        plain = arcade.arcade_frames(data, now)[3]
        for tier, cut in (('rare', False), ('unique', True), ('legend', True)):
            shown = arcade.arcade_frames(data, now, lockbox.Box('x', tier, 'codex_a', stage, 6))[3]
            self.assertEqual(shown.crop(panel).tobytes() != plain.crop(panel).tobytes(), cut, tier)
            quiet = arcade.arcade_frames(data, now, lockbox.Box('x', tier, 'codex_a', stage, 6, intro=False))[3]
            self.assertEqual(quiet.crop(panel).tobytes(), plain.crop(panel).tobytes(), tier)  # the quiet loop: no cut-in

    def test_unavailable_accounts_are_neither_working_nor_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            now = time.time()
            data = snapshot(now, [('copilot_a', 'C', 'copilot', [('MONTH', 40, None)])])
            data['accounts']['copilot_a']['status'] = 'auth_required'
            found = lockbox.facts(data, lockbox.History(Path(directory) / 'h.json'), now)['copilot_a']
            self.assertFalse({'copilot:idle', 'copilot:active'} & found)

    def test_a_streak_counts_calendar_weeks_across_a_clock_change(self):
        import os
        saved = os.environ.get('TZ')
        os.environ['TZ'] = 'America/New_York'
        time.tzset()
        try:
            with tempfile.TemporaryDirectory() as directory:
                history = lockbox.History(Path(directory) / 'h.json')
                history.data['peaks'] = {'a': {'WEEK': {'2026-W42': 100, '2026-W43': 100, '2026-W44': 100}}}
                now = time.mktime((2026, 11, 1, 23, 30, 0, 0, 0, -1))  # the day the clocks go back
                self.assertEqual(history.full_streak('a', now), 3)
        finally:
            if saved is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = saved
            time.tzset()

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / 'pyproject.toml').exists(), 'a source copy without packaging')
    def test_the_bundle_is_packaged(self):
        self.assertIn('"*.bin"', (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())


class TimingTests(unittest.TestCase):
    """When a reading counts as what: rates for jumps, the provider's reset time for resets, a margin for worry."""

    @staticmethod
    def row(used, at, resets_at=None, status='ok', **fields):
        return dict({'key': 'a', 'alias': 'A', 'provider': 'codex', 'status': status, 'fetched_at': at,
                     'windows': [{'label': '5H', 'used_percent': used, 'resets_at': resets_at}]}, **fields)

    def test_a_jump_is_a_rate_so_a_long_gap_is_not_a_sudden_one(self):
        from token_tv.state import news_of
        now = time.time()
        jump = lambda gap, rise: next(i['value'] for i in news_of(self.row(40, now - gap), self.row(40 + rise, now))
                                      if i['kind'] == 'jump')
        self.assertEqual(jump(120, 12), 12)  # twelve points in two minutes
        self.assertLess(jump(3600, 15), 10)  # fifteen over an hour

    def test_a_jump_adds_up_the_last_ten_minutes_and_an_outage_is_not_one(self):
        start = time.time() - 4000
        def jumps(readings):
            readings = list(readings)
            def fetch(_):
                at, used = readings.pop(0)
                return self.row(used, start + at, status='ok' if used is not None else 'error')
            store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}], fetch=fetch)
            for _ in range(len(readings)):
                store.refresh()
            news = store.snapshot()['accounts']['a'].get('news', [])
            return max([i['value'] for i in news if i['kind'] == 'jump'] or [0])
        self.assertEqual(jumps([(0, 40), (250, 45), (500, 51)]), 11)  # two small steps, one sharp ten minutes
        self.assertLess(jumps([(0, 40), (3540, None), (3600, 55)]), 10)  # the kept 40% is an hour old

    def test_a_reset_needs_its_reset_time_to_pass_or_move_on(self):
        from token_tv.state import event_of
        now = time.time()
        due, later = now + 30, now + 3 * 3600
        self.assertIsNone(event_of(self.row(60, now - 60, later), self.row(5, now, later)))  # a correction
        self.assertEqual(event_of(self.row(60, now - 60, due), self.row(5, now, now + 5 * 3600)), 'reset')
        self.assertEqual(event_of(self.row(60, now - 60, later), self.row(5, now, later + 5 * 3600)), 'reset')
        self.assertEqual(event_of(self.row(60, now - 60), self.row(5, now)), 'reset')  # no reset time known

    def test_a_reading_with_other_windows_is_not_compared(self):
        from token_tv.state import event_of, news_of, rose
        now = time.time()
        before = self.row(80, now - 60)
        before['windows'] = [{'label': 'WEEK', 'used_percent': 80, 'resets_at': None},
                             {'label': 'WEEK2', 'used_percent': 5, 'resets_at': None}]
        after = self.row(5, now)
        after['windows'] = [{'label': 'WEEK', 'used_percent': 5, 'resets_at': None}]  # the first went missing
        self.assertIsNone(event_of(before, after))
        self.assertFalse(rose(after, before))
        self.assertFalse({'jump', 'crossed'} & {i['kind'] for i in news_of(after, before)})

    def test_a_saved_reset_that_ran_out_was_not_spent(self):
        from token_tv.state import event_of, news_of
        now = time.time()
        before = self.row(40, now - 60, reset_credits={'count': 1, 'expires_at': now - 30})
        after = self.row(40, now, reset_credits={'count': 0, 'expires_at': None})
        self.assertIsNone(event_of(before, after))
        self.assertNotIn('ticket_spent', {i['kind'] for i in news_of(before, after)})
        before['reset_credits']['expires_at'] = now + 3600  # still good an hour more: used
        self.assertEqual(event_of(before, after), 'reset')

    def test_worry_starts_at_90_and_ends_below_85_and_an_outage_changes_nothing(self):
        readings = [(91, 'ok'), (87, 'ok'), (None, 'error'), (84, 'ok')]
        def fetch(_):
            used, status = readings.pop(0)
            row = self.row(used, time.time(), status=status)
            if used is None:
                row['windows'] = []
            return row
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}], fetch=fetch)
        seen = []
        for _ in range(4):
            store.refresh()
            seen.append(bool(store.snapshot()['accounts']['a'].get('worry')))
        self.assertEqual(seen, [True, True, True, False])

    def test_a_crossing_names_its_window_so_a_picture_drawn_ahead_stays_true(self):
        now = time.time()
        data = snapshot(now, [('codex_a', 'A', 'codex', [('5H', 81, 3600), ('WEEK', 82, 3 * D)])])
        with tempfile.TemporaryDirectory() as directory:
            history = lockbox.History(Path(directory) / 'history.json')
            for label, main in (('5H', False), ('WEEK', True)):
                data['accounts']['codex_a']['news'] = [{'kind': 'crossed', 'value': 80, 'label': label, 'at': now}]
                found = lockbox.facts(data, history, now)['codex_a']
                self.assertIn('codex:crossed_80', found)
                self.assertEqual('codex:main_crossed_80' in found, main)  # the picture follows the week
            data['accounts']['codex_a']['windows'][1]['used_percent'] = 100  # gone on to full: the garden is complete
            self.assertNotIn('codex:main_crossed_80', lockbox.facts(data, history, now)['codex_a'])

    def test_five_hour_windows_in_a_row_count_for_the_full_points(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as directory:
            history = lockbox.History(Path(directory) / 'history.json')
            for k, used in enumerate((100, 60, 100, 100)):
                data = snapshot(now, [('anti_a', 'A', 'antigravity', [('5H', used, 3600)])])
                data['accounts']['anti_a']['windows'][0]['resets_at'] = now + k * 5 * 3600
                history.observe(data, now)
            self.assertEqual(history.five_hour_run('anti_a'), 2)

    def test_coming_back_after_an_hour_and_the_first_use_of_the_day(self):
        from token_tv.state import news_of
        now = time.time()
        kinds = lambda news: {i['kind'] for i in news}
        self.assertIn('back', kinds(news_of(self.row(10, now - 60, rose_at=now - 2 * 3600), self.row(12, now))))
        self.assertNotIn('back', kinds(news_of(self.row(10, now - 60, rose_at=now - 600), self.row(12, now))))
        data = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)]),
                              ('claude_a', 'CLAUDE A', 'claude', [('WEEK', 50, 3 * D)])])
        data['accounts']['codex_a']['news'] = [{'kind': 'first_today', 'value': True, 'at': now}]
        with tempfile.TemporaryDirectory() as directory:
            found = lockbox.facts(data, lockbox.History(Path(directory) / 'history.json'), now)
        self.assertIn('day_start', found['claude_a'])  # the day's first use counts for every account


class GardenTests(unittest.TestCase):
    def test_five_spots_show_at_every_reading_and_only_a_full_fifth_blooms(self):
        marks = {arcade.PLOT, arcade.STEM, arcade.BUD, arcade.PETAL}
        def garden(used):
            stage = Image.new('RGB', (120, 71))
            arcade.codex_scene(stage, arcade.ImageDraw.Draw(stage), (0, 0, 120, 71), 0, 10, False, 1, {'used': used})
            return stage
        def spots(stage):  # a plot, a sprout or a flower at each of the five places
            return sum(any(stage.getpixel((x + d, y)) in marks for d in range(-6, 6) for y in range(71))
                       for x in (12, 36, 60, 84, 108))
        def blooms(stage):
            return sum(1 for p in stage.getdata() if p == arcade.HEART)
        for used in (0, 20, 40, 41, 60, 80, 99):
            self.assertEqual(spots(garden(used)), 5, used)
        self.assertEqual(blooms(garden(58)), blooms(garden(40)))  # 58% is a bud on the third spot, not a bloom
        self.assertGreater(blooms(garden(60)), blooms(garden(58)))


NOON = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))  # exact colours: the stage dims at night


class PropTests(unittest.TestCase):
    def test_a_trace_is_the_prop_standing_in_the_scene_not_a_header_mark(self):
        now = NOON
        art = Image.new('RGBA', (7, 6), (255, 0, 255, 255))
        buffer = io.BytesIO()
        art.save(buffer, format='PNG')
        prop = base64.b64encode(buffer.getvalue()).decode()
        for provider in ('claude', 'codex', 'grok', 'copilot', 'antigravity'):
            data = snapshot(now, [(f'{provider}_a', 'A', provider, [('WEEK', 40, 3 * D)])])
            plain = arcade.arcade_frames(data, now)[0]
            data['accounts'][f'{provider}_a'].update(trace='legend', trace_prop=prop)
            left = arcade.arcade_frames(data, now)[0]
            self.assertIn((255, 0, 255), [p for p in left.crop((0, 28, 240, 170)).getdata()], provider)
            self.assertEqual(plain.crop((0, 0, 240, 28)).tobytes(), left.crop((0, 0, 240, 28)).tobytes())


class GaugeTests(unittest.TestCase):
    """The pictures read as gauges: Grok's fuel is what is left; Copilot's clouds fill as it is used."""

    def stage(self, provider, used, active=False, label='WEEK'):
        now = NOON
        data = snapshot(now, [(f'{provider}_a', 'A', provider, [(label, used, 3 * D)])])
        data['accounts'][f'{provider}_a']['active'] = active
        return arcade.arcade_frames(data, now)[0].convert('RGB').crop((0, 28, 240, 170))

    def count(self, image, colours):
        return sum(1 for p in image.getdata() if p in colours)

    def test_grok_fuel_drains_as_the_limit_is_used(self):
        fuel = {arcade.FUEL, arcade.FUEL_TOP}
        self.assertGreater(self.count(self.stage('grok', 20), fuel), self.count(self.stage('grok', 70), fuel))
        self.assertGreater(self.count(self.stage('grok', 95), {arcade.FUEL_LOW}), 0)  # the last of it, red

    def test_copilot_counts_its_use_in_clouds(self):
        def clouds(used, active=False):
            sky = self.stage('copilot', used, active).crop((0, 0, 240, 56))  # the row of five, above the plane
            return self.count(sky, {arcade.CLOUD_TOP}), self.count(sky, {arcade.CLOUD_SPOT})
        (none, clear), (two, _), (all_, left) = clouds(5), clouds(45), clouds(100)
        self.assertLess(none, two)
        self.assertLess(two, all_)
        self.assertEqual(left, 0)  # all five clouds out
        self.assertGreater(clear, 0)  # the clear patches still show
        self.assertEqual(clouds(45, True)[0], two)  # the same count at work

    def test_a_jog_meets_its_start_when_two_accounts_share_the_loop(self):
        data = snapshot(NOON, [('claude_a', 'A', 'claude', [('WEEK', 50, 3 * D)]), ('codex_a', 'B', 'codex', [('WEEK', 50, 3 * D)])])
        for row in data['accounts'].values():
            row['active'] = True
        frames = arcade.arcade_frames(data, NOON)
        def clawd_x(frame):
            xs = [x for y in range(100, 170, 2) for x in range(0, 240, 2) if frame.getpixel((x, y))[0] > 190
                  and frame.getpixel((x, y))[1] < 140 and frame.getpixel((x, y))[2] < 120]
            return min(xs)
        spots = [clawd_x(frames[k]) for k in range(arcade.FRAMES // 2)]  # Claude's half of the loop
        self.assertLessEqual(max(abs(a - b) for a, b in zip(spots, spots[1:])), 8)

    def test_the_stage_dims_late_at_night_and_the_numbers_do_not(self):
        night = time.mktime((2026, 10, 29, 2, 0, 0, 0, 0, -1))
        def frame(now):
            data = snapshot(now, [('codex_a', 'A', 'codex', [('WEEK', 40, 3 * D)])])
            return arcade.arcade_frames(data, now)[0].convert('L')
        day, dark = frame(NOON), frame(night)
        bright = lambda image, box: sum(image.crop(box).getdata())
        self.assertLess(bright(dark, (0, 28, 240, 170)), bright(day, (0, 28, 240, 170)) * .8)
        self.assertEqual(day.crop((0, 170, 240, 240)).tobytes(), dark.crop((0, 170, 240, 240)).tobytes())


class FifthAccountTests(unittest.TestCase):
    def test_more_than_four_take_turns_round_by_round_of_the_rest_flow(self):
        rows = [(f'codex_{n}', f'CODEX {n.upper()}', 'codex', [('WEEK', 40 + i, 3 * D)]) for i, n in enumerate('abcdef')]
        data = snapshot(NOON, rows)
        for row in data['accounts'].values():
            row['active'] = True
        seen, rounds = set(), set()
        for minute in range(0, 12):
            turn = arcade.shown_rows(data, NOON - NOON % 360 + 60 * minute)
            self.assertEqual(len(turn), 4)
            seen.update(row['key'] for row in turn)
            rounds.add(tuple(row['key'] for row in turn))
        self.assertEqual(seen, set(data['accounts']))
        self.assertEqual(len(rounds), 2)  # the same four for six minutes, then the next

    def test_a_restart_remembers_when_each_account_last_worked(self):
        from token_tv.state import news_of
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}], fetch=lambda _: None)
        now = time.time()
        today = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        earlier = now - min(60, (now - today) / 2)  # earlier today, even a minute after midnight
        store.restore({'accounts': {'a': {'rose_at': earlier, 'active_since': earlier - 3600}}})
        previous = dict(store.rows['a'], windows=[{'label': 'WEEK', 'used_percent': 10}], status='ok', fetched_at=earlier)
        row = {'status': 'ok', 'fetched_at': time.time(), 'windows': [{'label': 'WEEK', 'used_percent': 11}]}
        self.assertNotIn('first_today', {i['kind'] for i in news_of(previous, row)})  # it already worked today

    def test_a_one_off_plays_for_an_account_the_clock_does_not_cycle_through(self):
        rows = [(f'{p}_{n}', f'{p.upper()} {n}', p, [('WEEK', used, 3 * D)])
                for (p, n, used) in (('claude', 'a', 81), ('claude', 'b', 82), ('codex', 'a', 83), ('codex', 'b', 84),
                                     ('codex', 'c', 1))]
        data = snapshot(NOON, rows)
        usual = arcade.arcade_frames(data, NOON)
        played = arcade.arcade_frames(data, NOON, egg='reset@codex_c')
        self.assertNotEqual(usual[30].tobytes(), played[30].tobytes())


class UnknownReadingTests(unittest.TestCase):
    def test_no_reading_draws_no_gauge_and_no_fret(self):
        for provider, label in (('grok', 'BUDGET'), ('copilot', 'MONTH'), ('antigravity', '5H'), ('codex', 'WEEK')):
            data = snapshot(NOON, [(f'{provider}_a', 'A', provider, [(label, 50, 3 * D)])])
            row = data['accounts'][f'{provider}_a']
            row['windows'], row['worry'] = [], True
            plan = arcade.scene_plan(row, NOON)
            self.assertNotEqual(plan['mood'], 'worried', provider)
            stage = arcade.arcade_frames(data, NOON)[0].convert('RGB').crop((0, 28, 240, 170))
            gauge_inks = {arcade.FUEL, arcade.FUEL_TOP, arcade.FUEL_LOW, arcade.CLOUD_SPOT, arcade.PLOT}
            self.assertFalse(gauge_inks & {p for p in stage.getdata()}, provider)

    def test_the_moon_is_dark_when_nothing_is_left_and_labels_spell_out(self):
        stage = Image.new('RGB', (40, 40))
        draw = arcade.ImageDraw.Draw(stage)
        arcade.moon_gauge(draw, 20, 20, 8, 0)
        self.assertNotIn(arcade.MOON_LIT, set(stage.getdata()))
        self.assertTrue(all(c in arcade.LABEL_GLYPHS for c in 'CHAT WINDOW DAY MO BUD 5H WK'.replace(' ', '')))


class TierTests(unittest.TestCase):
    def test_each_tier_marks_the_header_and_a_legend_runs_a_rainbow(self):
        now = time.time()
        data = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)])])
        stage = tuple(Image.new('RGB', (120, 71), (20, 20, 20)) for _ in range(3))
        corner = lambda image: image.crop((8, 6, 26, 24))
        plain = arcade.arcade_frames(data, now)[0]
        marks = {}
        for tier in ('unique', 'legend'):
            frames = arcade.arcade_frames(data, now, lockbox.Box('x', tier, 'codex_a', stage, 6))
            marks[tier] = corner(frames[5])
            self.assertNotEqual(corner(plain).tobytes(), marks[tier].tobytes(), tier)
        rare = arcade.arcade_frames(data, now, lockbox.Box('x', 'rare', 'codex_a', stage, 11))[5]
        self.assertNotEqual(corner(rare).tobytes(), marks['unique'].tobytes())  # blue, not purple
        everyday = arcade.arcade_frames(data, now, 'reset@codex_a')[5]  # a reset is common: no mark
        self.assertEqual(corner(everyday).tobytes(), corner(plain).tobytes())
        border = lambda image: image.crop((0, 28, 4, 170))
        legend = arcade.arcade_frames(data, now, lockbox.Box('x', 'legend', 'codex_a', stage, 11))[5]
        unique = arcade.arcade_frames(data, now, lockbox.Box('x', 'unique', 'codex_a', stage, 6))[5]
        self.assertNotEqual(border(legend).tobytes(), border(unique).tobytes())


if __name__ == '__main__':
    unittest.main()
