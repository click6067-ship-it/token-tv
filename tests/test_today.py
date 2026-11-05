"""v2 phase 3b, x7: today's use for the Survival face (state.py), from the window it is read from (its week over its 5
hours) on this computer's local date: the sum over the day's windows (one reset period each) of each one's last reading
less its first that day. A window that began today counts from nothing; for the one the day began in, a reading in the
15 minutes before midnight stands for midnight. A new window is one whose reset time moved later (or, with none known,
whose use fell to under half and below 10 %); any other fall is a correction within the window. Today's use is a share
of an even day (a seventh of a week). It goes into the state folder with the snapshot, so a restart keeps it; not known
is None."""
import json
import os
import time
import unittest
from unittest import mock

from token_tv import state
from token_tv.state import DAY_EDGE, SAME_WINDOW, UsageStore, day_step, today_share, valid_day
from token_tv.usage import (even_day, five_hour, long_window, normalize_codex, reset_credits, today_window,
                            window_minutes)

EVEN_WEEK = 100 / 7  # an even day's points of a week


def local(y, m, d, hh=12, mm=0, ss=0):
    return time.mktime((y, m, d, hh, mm, ss, 0, 0, -1))


def week(used, resets, label='WEEK', minutes=10080):
    return {'label': label, 'used_percent': used, 'resets_at': resets, 'duration_minutes': minutes}


def five(used, resets):
    return {'label': '5H', 'used_percent': used, 'resets_at': resets, 'duration_minutes': 300}


def walk(readings):
    """The day after `readings` [(at, window)], in turn."""
    day = None
    for at, value in readings:
        day = day_step(day, value, at)
    return day


def points(readings):
    """Today's use in the window's points after each of `readings` [(at, window)], in turn."""
    day, out = None, []
    for at, value in readings:
        day = day_step(day, value, at)
        out.append(round(today_share(day, at) * even_day(day['minutes']), 9))
    return out


class WindowsTests(unittest.TestCase):
    def test_todays_use_is_read_from_the_longest_window_of_a_known_length_in_any_order(self):
        a, b = five(30, 1), week(60, 2)
        self.assertIs(today_window([a, b]), b)
        self.assertIs(today_window([b, a]), b)
        month, chat = {'label': 'MONTH', 'used_percent': 40}, {'label': 'CHAT', 'used_percent': 90}
        self.assertIs(today_window([chat, month]), month)
        self.assertEqual(today_window([{'label': 'BUDGET', 'used_percent': 61}])['label'], 'BUDGET')
        self.assertIs(today_window([a]), a)
        self.assertIsNone(today_window([chat, {'label': 'WINDOW', 'used_percent': 3}]))  # no length known: unknown

    def test_hearts_are_the_5_hour_window_and_hunger_the_week_else_the_longest_other(self):
        a, b = five(30, 1), week(60, 2)
        for order in ([a, b], [b, a]):
            self.assertIs(five_hour(order), a)
            self.assertIs(long_window(order), b)
        alias = {'label': 'WINDOW', 'used_percent': 5, 'duration_minutes': 10080}  # a week by its length
        self.assertIs(long_window([{'label': 'MONTH', 'used_percent': 1}, alias]), alias)
        self.assertEqual(five_hour([{'label': 'WINDOW', 'used_percent': 5, 'duration_minutes': 300}])['label'], 'WINDOW')
        self.assertEqual(long_window([{'label': 'CHAT', 'used_percent': 9}, {'label': 'MONTH', 'used_percent': 1}])['label'],
                         'MONTH')
        self.assertIsNone(long_window([a]))
        self.assertIsNone(five_hour([b]))

    def test_an_even_day_is_a_seventh_of_a_week_a_thirtieth_of_a_month_and_one_whole_5_hour_window(self):
        self.assertAlmostEqual(even_day(window_minutes(week(0, 0))), 100 / 7)
        self.assertAlmostEqual(even_day(window_minutes({'label': 'MONTH'})), 100 / 30)
        self.assertAlmostEqual(even_day(window_minutes({'label': 'BUDGET'})), 100 / 30)
        self.assertEqual(even_day(window_minutes({'label': 'DAY'})), 100)
        self.assertEqual(even_day(window_minutes(five(0, 0))), 100)
        self.assertIsNone(even_day(window_minutes({'label': 'CHAT'})))


class DayTests(unittest.TestCase):
    D = (2026, 11, 5)

    def at(self, hh, mm=0, ss=0, day=0):
        return local(2026, 11, 5 + day, hh, mm, ss)

    def test_a_day_counts_what_its_window_rose_since_it_began(self):
        resets = self.at(23) + 3 * 86400
        day = walk([(self.at(9), week(40, resets))])
        self.assertEqual(today_share(day, self.at(9, 1)), 0)  # its first reading: nothing used since
        day = day_step(day, week(42, resets), self.at(10))
        self.assertAlmostEqual(today_share(day, self.at(10)), 2 / EVEN_WEEK)
        self.assertEqual(day_step(day, week(42, resets), self.at(10)), day)  # the same reading again
        self.assertEqual(day_step(day, week(41, resets), self.at(9, 30)), day)  # an older one
        day = day_step(day, week(55.5, resets), self.at(18))
        self.assertAlmostEqual(today_share(day, self.at(18)), 15.5 / EVEN_WEEK)

    def test_a_reset_is_never_use_and_the_new_window_counts_from_nothing(self):
        r1, r2 = self.at(10), self.at(15)  # a 5-hour window resetting at 10:00, then at 15:00
        day = walk([(self.at(9), five(30, r1)), (self.at(9, 50), five(50, r1)), (self.at(10, 5), five(4, r2))])
        self.assertAlmostEqual(today_share(day, self.at(10, 5)), (20 + 4) / 100)  # one 5-hour window is an even day
        idle = walk([(self.at(9), five(30, r1)), (self.at(9, 50), five(50, r1)), (self.at(10, 5), five(0, r2))])
        self.assertAlmostEqual(today_share(idle, self.at(10, 5)), 20 / 100)  # a reset with no use since adds nothing
        unknown = walk([(self.at(9), {'label': 'BUDGET', 'used_percent': 60, 'resets_at': None}),
                        (self.at(9, 30), {'label': 'BUDGET', 'used_percent': 70, 'resets_at': None}),
                        (self.at(9, 40), {'label': 'BUDGET', 'used_percent': 3, 'resets_at': None})])
        self.assertAlmostEqual(today_share(unknown, self.at(10)), (10 + 3) / (100 / 30))  # no reset time: the fall

    def test_any_other_fall_is_a_correction_within_the_window(self):
        r = self.at(15)  # the same reset time in every reading
        self.assertEqual(points([(self.at(9, i), five(used, r)) for i, used in enumerate((30, 50, 45, 50, 45, 50))]),
                         [0, 20, 15, 20, 15, 20])  # its last reading less its first: a correction adds nothing
        self.assertEqual(points([(self.at(9), five(30, r)), (self.at(9, 55), five(25, r))]), [0, 0])  # never below 0

    def test_a_new_window_is_one_whose_reset_time_moved_later_else_one_that_fell_to_near_nothing(self):
        r = self.at(15)
        rose = [(self.at(9), five(30, r)), (self.at(10), five(50, r))]
        self.assertEqual(points(rose + [(self.at(10, 5), five(2, r + SAME_WINDOW + 1))])[-1], 20 + 2)  # a new window
        for wobble in (SAME_WINDOW, -3600):  # moved later by no more than SAME_WINDOW, or earlier: the same window
            self.assertEqual(points(rose + [(self.at(10, 5), five(2, r + wobble))])[-1], 0)

        def budget(used, resets=None):
            return {'label': 'BUDGET', 'used_percent': used, 'resets_at': resets}
        # with no reset time known, a new window is a fall to under half and below 10 %
        for before, after, new in ((30, 9.9, True), (30, 14, False), (12, 5.9, True), (12, 6, False), (12, 9, False)):
            got = points([(self.at(9), budget(0)), (self.at(10), budget(before)), (self.at(11), budget(after))])
            self.assertEqual(got[-1], before + after if new else after, (before, after))
        mixed = points([(self.at(9), budget(40, r)), (self.at(10), budget(60, r)), (self.at(11), budget(0)),
                        (self.at(12), budget(3, r + 30 * 86400))])  # (one reading without a reset time)
        self.assertEqual(mixed, [0, 20, 20, 23])
        # a week re-dated later without a fall, begun days ago: nothing invented, and the day counts on
        week_end = self.at(12, day=3)
        self.assertEqual(points([(self.at(9), week(40, week_end)), (self.at(10), week(60, week_end)),
                                 (self.at(11), week(60, week_end + 86400)), (self.at(12), week(62, week_end + 86400))]),
                         [0, 20, 20, 22])

    def test_a_spent_reset_credit_is_a_new_window_counted_from_nothing(self):
        week_end = self.at(23) + 3 * 86400  # the week as read at 9:00 has three days to go
        new_end = self.at(11) + 7 * 86400  # a reset credit spent at 11:00: a new week from then
        for first in (0, 5):  # the new week's first reading, whatever was used of it by then
            readings = [(self.at(9), week(40, week_end)), (self.at(10), week(60, week_end)),
                        (self.at(11, 5), week(first, new_end)), (self.at(12), week(10, new_end)),
                        (self.at(13), week(15, new_end))]
            self.assertEqual(points(readings), [0, 20, 20 + first, 30, 35], first)  # 0, 140, 140 or 175, 210, 245 %
            tomorrow = day_step(walk(readings), week(17, new_end), self.at(9, day=1))
            self.assertEqual(today_share(tomorrow, self.at(9, day=1)), 0)  # the next day starts anew
        # first seen the next morning: from nothing if the new week began that day, else from its first reading
        day = walk([(self.at(9), week(40, week_end)), (self.at(22), week(60, week_end))])
        for spent, want in ((self.at(7, day=1), 5), (self.at(23), 0)):
            seen = day_step(day, week(5, spent + 7 * 86400), self.at(8, day=1))
            self.assertAlmostEqual(today_share(seen, self.at(8, day=1)), want / EVEN_WEEK)
        # just after midnight, from a reading that stands for midnight: the day counts from the new week's start
        new_end = self.at(0, 10, day=1) + 7 * 86400
        late = walk([(self.at(23, 50), week(60, week_end)), (self.at(0, 10, day=1), week(0, new_end)),
                     (self.at(1, day=1), week(5, new_end))])
        self.assertAlmostEqual(today_share(late, self.at(1, day=1)), 5 / EVEN_WEEK)

    def test_a_reading_in_the_quarter_hour_before_midnight_stands_for_the_days_start(self):
        resets = self.at(12, day=3)
        late = walk([(self.at(23, 50), week(50, resets)), (self.at(0, 5, day=1), week(52, resets))])
        self.assertAlmostEqual(today_share(late, self.at(0, 6, day=1)), 2 / EVEN_WEEK)
        early = walk([(self.at(22), week(50, resets)), (self.at(8, day=1), week(60, resets))])
        self.assertEqual(today_share(early, self.at(8, day=1)), 0)  # asleep at midnight: from its first reading
        self.assertEqual(today_share(walk([(self.at(23, 55), week(50, resets))]), self.at(0, 2, day=1)), 0)
        self.assertIsNone(today_share(walk([(self.at(22), week(50, resets))]), self.at(0, 2, day=1)))  # not known yet
        midnight = self.at(0, day=1)
        self.assertEqual(today_share(walk([(midnight - DAY_EDGE, week(50, resets))]), midnight + 60), 0)
        self.assertIsNone(today_share(walk([(midnight - DAY_EDGE - 1, week(50, resets))]), midnight + 60))
        reset = self.at(0, 30, day=1)  # the week itself resets at 00:30: the new one from nothing, no carry-over
        day = walk([(self.at(23, 55), week(70, reset)), (self.at(0, 35, day=1), week(1, reset + 7 * 86400))])
        self.assertAlmostEqual(today_share(day, self.at(0, 40, day=1)), 1 / EVEN_WEEK)
        day = day_step(day, week(3, reset + 7 * 86400), self.at(9, day=1))
        self.assertAlmostEqual(today_share(day, self.at(9, day=1)), 3 / EVEN_WEEK)

    def test_the_same_use_today_is_the_same_whatever_came_before(self):
        resets = self.at(12, day=4)
        a = walk([(self.at(23, 50, day=-1), week(10, resets)), (self.at(9), week(14, resets)), (self.at(18), week(20, resets))])
        b = walk([(self.at(23, 50, day=-1), week(70, resets)), (self.at(9), week(74, resets)), (self.at(18), week(80, resets))])
        self.assertAlmostEqual(today_share(a, self.at(18)), today_share(b, self.at(18)))
        c = walk([(self.at(23, 50, day=-1), week(70, resets)), (self.at(18), week(80, resets))])
        d = walk([(self.at(23, 50, day=-1), week(75, resets)), (self.at(18), week(80, resets))])
        self.assertNotAlmostEqual(today_share(c, self.at(18)), today_share(d, self.at(18)))  # the same quota, not use

    def test_another_window_is_counted_from_its_first_reading(self):
        day = walk([(self.at(9), week(40, 1)), (self.at(10), week(45, 1))])
        day = day_step(day, five(20, 2), self.at(11))  # (the week went missing: the 5 hours now)
        self.assertEqual(today_share(day, self.at(11)), 0)
        self.assertEqual(day['label'], '5H')

    def test_a_kept_day_must_look_like_one(self):
        good = walk([(self.at(9), week(40, 1))])
        self.assertEqual(valid_day(json.loads(json.dumps(good))), good)
        for bad in (None, [], 'x', dict(good, used=True), dict(good, date=3), dict(good, minutes='10080'),
                    {k: v for k, v in good.items() if k != 'base'}, dict(good, resets_at='soon'),
                    dict(good, resets_at=False)):
            self.assertIsNone(valid_day(bad), bad)

    @unittest.skipUnless(hasattr(time, 'tzset'), 'needs a settable time zone')
    def test_the_day_is_this_computers_own(self):
        self.addCleanup(time.tzset)
        before = 1793890800 - 600  # 2026-11-05 15:00 UTC is midnight in Seoul: ten minutes before, and after
        after = 1793890800 + 600
        for zone, new_day in (('Asia/Seoul', True), ('UTC', False)):
            with mock.patch.dict(os.environ, {'TZ': zone}):
                time.tzset()
                day = walk([(before - 3600, week(40, after + 86400)), (before, week(45, after + 86400)),
                            (after, week(47, after + 86400))])
                self.assertAlmostEqual(today_share(day, after), (2 if new_day else 7) / EVEN_WEEK, msg=zone)
            time.tzset()


class Clock:
    """state.time on a hand-moved clock."""
    def __init__(self, at):
        self.t = at

    def time(self):
        return self.t

    def monotonic(self):
        return self.t

    def __getattr__(self, name):
        return getattr(time, name)


class StoreTests(unittest.TestCase):
    """Through UsageStore, as live.main reads and keeps it."""
    def setUp(self):
        self.clock = Clock(local(2026, 11, 5, 9))
        patcher = mock.patch.object(state, 'time', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.used = {'claude_a': 40.0, 'codex_a': 10.0}
        self.status = 'ok'

    def fetch(self, account):
        windows = [{'label': '5H', 'used_percent': 20.0, 'resets_at': self.clock.t + 3600, 'duration_minutes': 300},
                   {'label': 'WEEK', 'used_percent': self.used[account['key']], 'resets_at': local(2026, 11, 9, 12),
                    'duration_minutes': 10080}]
        return {'key': account['key'], 'alias': account['alias'], 'provider': account['provider'], 'status': self.status,
                'windows': windows if self.status == 'ok' else [], 'fetched_at': self.clock.t}

    def store(self):
        return UsageStore([{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude'},
                           {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex'}], fetch=self.fetch)

    def test_each_account_has_its_own_today_and_a_restart_keeps_it(self):
        store = self.store()
        store.refresh()
        self.assertEqual(store.snapshot()['accounts']['claude_a']['today'], 0)
        for minutes, claude, codex in ((60, 42.0, 10.0), (120, 44.5, 13.0), (180, 44.5, 13.0)):  # (a duplicate last)
            self.clock.t = local(2026, 11, 5, 9) + 60 * minutes
            self.used.update(claude_a=claude, codex_a=codex)
            store.refresh()
        shown = store.snapshot()['accounts']
        self.assertAlmostEqual(shown['claude_a']['today'], 4.5 / EVEN_WEEK)
        self.assertAlmostEqual(shown['codex_a']['today'], 3 / EVEN_WEEK)
        kept = json.loads(json.dumps(store.snapshot()))  # as live.main writes snapshot.json and reads it back
        again = self.store()
        again.restore(kept)
        self.assertAlmostEqual(again.snapshot()['accounts']['claude_a']['today'], 4.5 / EVEN_WEEK)  # still loading
        self.used.update(claude_a=46.0)
        self.clock.t += 600
        again.refresh()
        self.assertAlmostEqual(again.snapshot()['accounts']['claude_a']['today'], 6 / EVEN_WEEK)
        broken = json.loads(json.dumps(kept))
        broken['accounts']['claude_a']['day']['base'] = 'forty'
        third = self.store()
        third.restore(broken)
        self.assertIsNone(third.snapshot()['accounts']['claude_a']['today'])  # a broken record is no day

    def test_a_reading_that_fails_keeps_the_day_and_the_next_day_starts_anew(self):
        store = self.store()
        store.refresh()
        self.clock.t += 3600
        self.used['claude_a'] = 47.0
        store.refresh()
        self.status = 'error'
        self.clock.t += 600
        store.refresh()
        row = store.snapshot()['accounts']['claude_a']
        self.assertEqual(row['status'], 'stale')
        self.assertAlmostEqual(row['today'], 7 / EVEN_WEEK)
        self.status = 'ok'
        self.clock.t = local(2026, 11, 6, 0, 2)  # the next day, its first reading two minutes in; nothing read at 23:4x
        store.refresh()
        self.assertEqual(store.snapshot()['accounts']['claude_a']['today'], 0)
        self.clock.t = local(2026, 11, 6, 9)
        self.used['claude_a'] = 49.0
        store.refresh()
        self.assertAlmostEqual(store.snapshot()['accounts']['claude_a']['today'], 2 / EVEN_WEEK)

    def restart(self, store):
        """TokenTV started again, from the snapshot `store` wrote (as live.main writes snapshot.json and reads it)."""
        again = UsageStore(store.accounts, fetch=store.fetch)
        again.restore(json.loads(json.dumps(store.snapshot())))
        return again

    def test_a_spent_reset_credit_keeps_todays_use_through_restarts(self):
        """A Codex week read as sources.fetch_account reads it (usage.normalize_codex, usage.reset_credits): 40 % at 9,
        60 % at 10, a reset credit spent at 11 (a new week from then) first read at 0 % or at 5 %, 10 % at 12:30 and
        15 % at 13:30. Today: 0, 140 %, 140 % or 175 %, 210 %, 245 % (35 points), with TokenTV restarted before the
        reset and after it."""
        reading = {}

        def fetch(account):
            five_hours = {'usedPercent': 5, 'windowDurationMins': 300, 'resetsAt': self.clock.t + 3600}
            the_week = {'usedPercent': reading['used'], 'windowDurationMins': 10080, 'resetsAt': reading['resets']}
            reply = {'rateLimits': {'primary': five_hours, 'secondary': the_week},
                     'rateLimitResetCredits': {'availableCount': reading['credits'], 'credits': [
                         {'status': 'available', 'expiresAt': local(2026, 12, 1)}] * reading['credits']}}
            return {'key': account['key'], 'alias': account['alias'], 'provider': 'codex', 'status': 'ok',
                    'windows': normalize_codex(reply), 'reset_credits': reset_credits(reply),
                    'fetched_at': self.clock.t}

        def shown(store):
            return store.snapshot()['accounts']['codex_a']['today'] * EVEN_WEEK

        for first in (0, 5):
            self.clock.t = local(2026, 11, 5, 9)
            reading.update(used=40, resets=local(2026, 11, 8, 12), credits=2)
            store = UsageStore([{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex'}], fetch=fetch)
            store.refresh()
            self.assertEqual(shown(store), 0)
            self.clock.t, reading['used'] = local(2026, 11, 5, 10), 60
            store.refresh()
            self.assertAlmostEqual(shown(store), 20)  # 140 %
            store = self.restart(store)
            self.clock.t = local(2026, 11, 5, 11)
            reading.update(used=first, resets=self.clock.t + 7 * 86400, credits=1)
            store.refresh()
            self.assertAlmostEqual(shown(store), 20 + first)  # 140 % or 175 %: the new week from nothing
            store = self.restart(store)
            self.assertAlmostEqual(shown(store), 20 + first)
            for at, used, want in ((local(2026, 11, 5, 12, 30), 10, 30), (local(2026, 11, 5, 13, 30), 15, 35)):
                self.clock.t, reading['used'] = at, used
                store.refresh()
                self.assertAlmostEqual(shown(store), want, msg=first)  # 210 %, 245 %

    def test_a_correction_counts_within_its_window_through_restarts(self):
        """The week read at 30 %, 50 %, then corrected to 45 %, then 50 % again, with TokenTV restarted between every
        two readings: today is 0, 20, 15, 20 points, the week's last reading less its first."""
        self.used['codex_a'] = 30.0
        store = self.store()
        store.refresh()
        got = [store.snapshot()['accounts']['codex_a']['today'] * EVEN_WEEK]
        for hours, used in ((1, 50.0), (2, 45.0), (3, 50.0)):
            store = self.restart(store)
            self.clock.t, self.used['codex_a'] = local(2026, 11, 5, 9 + hours), used
            store.refresh()
            got.append(store.snapshot()['accounts']['codex_a']['today'] * EVEN_WEEK)
        self.assertEqual([round(p, 9) for p in got], [0, 20, 15, 20])

    def test_no_reading_today_yet_is_not_known(self):
        store = self.store()
        store.refresh()
        self.clock.t = local(2026, 11, 6, 10)  # a day later, nothing read since
        self.assertIsNone(store.snapshot()['accounts']['claude_a']['today'])


if __name__ == '__main__':
    unittest.main()
