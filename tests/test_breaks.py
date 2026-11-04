"""v2 phase 2, e6: after an hour of work (any account at work: its usage rose within state.ACTIVE_SECONDS, all of
them together counted once) since the last break (BREAK with nobody at work) or the last reminder, the pets on the
clock drink water or stretch, one of the two at random, for one loop at the end of the loop playing. A Claude wait
outranks it: it plays after the wait if no break came meanwhile. Nothing piles up."""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import FakeClock, Rig, SyntheticTime, physical  # noqa: E402
from test_limit_warning import SyntheticWall  # noqa: E402

from token_tv import arcade, moments, state  # noqa: E402
from token_tv.moments import BREAK, BREAKS, WORK, Moments, Work, overlay  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402

ACTIVE = state.ACTIVE_SECONDS
NOW = 1793509260
PETS = ('claude', 'codex', 'grok', 'copilot', 'antigravity')


class Picks:
    """moments.RANDOM as a test sets it: each reminder's break in turn from `kinds`."""
    def __init__(self, *kinds):
        self.kinds, self.asked = list(kinds), 0

    def choice(self, options):
        self.asked += 1
        kind = self.kinds.pop(0)
        assert kind in options
        return kind


class WorkTests(unittest.TestCase):
    """The hour of work, on the readings' own times (wall clock seconds here)."""
    def setUp(self):
        self.picks = Picks(*(['drink', 'stretch'] * 8))
        patcher = mock.patch.object(moments, 'RANDOM', self.picks)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = Work(active=ACTIVE)

    def rise(self, at, key='a', now=None):
        self.w.observe({key: {'rose_at': at}}, at if now is None else now)

    def work(self, start, end, every=60, key='a'):
        """Rises every `every` seconds from `start` to `end`, each read as it happens."""
        t = start
        while t <= end:
            self.rise(t, key)
            t += every

    def test_an_hour_of_work_makes_the_reminder_due_once_at_its_end(self):
        self.work(0, WORK - 60)
        self.w.advance(WORK - .001)
        self.assertIsNone(self.w.due)  # not a moment before
        self.rise(WORK)
        self.assertEqual(self.w.due, (WORK, 'drink'))
        self.work(WORK + 60, 2 * WORK + 600)  # an hour more without it shown: still that one reminder
        self.assertEqual(self.w.due, (WORK, 'drink'))
        self.assertEqual(self.picks.asked, 1)

    def test_accounts_at_work_together_count_once_and_a_handover_keeps_the_hour(self):
        for t in range(0, WORK, 60):  # two at once, rising out of step
            self.w.observe({'a': {'rose_at': t}, 'b': {'rose_at': t + 30}}, t + 30)
        self.w.advance(WORK - .001)
        self.assertIsNone(self.w.due)  # no faster for two
        self.w.advance(WORK)
        self.assertEqual(self.w.due[0], WORK)
        other = Work(active=ACTIVE)
        for t in range(0, WORK // 2, 60):
            other.observe({'a': {'rose_at': t}}, t)
        for t in range(WORK // 2, WORK + 60, 60):  # A stops, B goes on: no gap with nobody at work
            other.observe({'a': {'rose_at': WORK // 2 - 60}, 'b': {'rose_at': t}}, t)
        self.assertEqual(other.due[0], WORK)

    def test_a_short_gap_keeps_the_work_done_and_adds_none(self):
        self.work(0, 1800)  # the last rise at 1800: at work until 1800 + ACTIVE
        back = 1800 + ACTIVE + BREAK - 1  # a gap one second short of a break
        self.work(back, back + 2 * WORK, every=60)
        worked = 1800 + ACTIVE  # done before the gap
        self.assertEqual(self.w.due[0], back + WORK - worked)  # not at wall WORK, and not a whole new hour

    def test_a_break_starts_the_hour_over_at_exactly_its_length_not_a_moment_sooner(self):
        edge = 1800 + ACTIVE  # when the last account stopped counting as at work
        for gap, starts_over in ((BREAK - .001, False), (BREAK, True)):
            self.w = Work(active=ACTIVE)
            self.work(0, 1800)
            back = edge + gap
            self.rise(back)
            self.work(back + 60, back + 2 * WORK)
            self.assertEqual(self.w.due[0], back + WORK if starts_over else back + WORK - edge, gap)

    def test_a_rise_read_late_counts_its_work_and_ends_the_gap_before_a_break(self):
        self.work(0, 1800)
        edge = 1800 + ACTIVE
        self.w.advance(edge + BREAK + 5)  # looked at past what would be a break, before the reading came in
        self.assertTrue(self.w.rested(edge + BREAK + 5))
        late = edge + BREAK - .5  # the rise in that reading came just before
        self.rise(late, now=edge + BREAK + 5)
        self.assertFalse(self.w.rested(edge + BREAK + 5))
        self.work(edge + BREAK + 60, edge + 3 * WORK)
        self.assertAlmostEqual(self.w.due[0], late + WORK - edge, places=6)  # the work before the gap kept

    def test_a_rise_read_after_a_later_one_still_counts_for_when_it_was_measured(self):
        self.rise(60, 'a')
        self.rise(900, 'a')  # A again at 900: on its own, a gap from 660 with nobody at work
        self.rise(600, 'b', now=960)  # B's rise at 600, read only at 960 (its snapshot written late, elsewhere)
        self.work(960, WORK + 600, key='a')
        self.assertEqual(self.w.due[0], 60 + WORK)  # their work together is unbroken from 60: due an hour on
        self.assertEqual(self.picks.asked, 1)

    def test_a_rise_read_late_in_what_had_looked_like_a_break_keeps_the_hour(self):
        self.work(0, 1800)  # at work until 1800 + ACTIVE
        edge = 1800 + ACTIVE
        back = edge + BREAK + 100
        self.work(back, back + 600)  # back after what looks like a break: the hour started over at `back`
        self.assertEqual(self.w.start, back)
        self.rise(edge + BREAK / 2, 'b', now=back + 600)  # but another account rose in that gap: read only now
        self.assertEqual(self.w.start, 0)  # no break after all
        self.work(back + 660, back + 2 * WORK)
        self.assertEqual(self.w.due[0], edge + BREAK / 2 + (WORK - edge))  # the work before the gap kept

    def test_the_hour_is_the_same_whatever_order_its_rises_are_read_in(self):
        import random
        # A short gap, one that a single rise splits in two, an hour done, a real break, and another hour.
        rises = sorted([(t, 'a') for t in range(0, 1500, 60)] + [(t, 'b') for t in range(2500, 3000, 100)] +
                       [(3600, 'd')] + [(t, 'c') for t in range(4300, 9000, 90)] + [(t, 'e') for t in range(11000, 14700, 60)])
        states = []
        for order in range(6):
            picks = Picks(*(['drink', 'stretch'] * 8))
            with mock.patch.object(moments, 'RANDOM', picks):
                work, seen = Work(active=ACTIVE), list(rises)
                if order:  # each reading comes in up to a quarter of an hour late, in an order of its own
                    seen.sort(key=lambda rise: rise[0] + random.Random(f'{order}{rise}').uniform(0, 900))
                now = 0
                for at, key in seen:
                    now = max(now, at)
                    work.observe({key: {'rose_at': at}}, now)
                    if order == 0 and work.due and not states:
                        states.append(work.due)  # (the first hour's reminder, read in order)
                work.advance(14700)
                states.append((work.due, picks.asked, work.start, round(work.credit, 6)))
        self.assertEqual(states[0], (4160, 'drink'))  # 2040 + 1000 + the gap's other side, 600, then 560 more
        self.assertEqual(len(set(states[1:])), 1, states)
        self.assertEqual(states[1], ((14600, 'stretch'), 2, 11000, 3700.0))

    def test_rises_summed_up_after_hours_count_as_they_did(self):
        long = Work(active=ACTIVE)
        for t in range(0, 4 * WORK, 60):  # four hours at work, the reminder never shown (no clock, say)
            long.observe({'a': {'rose_at': t}}, t)
        self.assertLess(len(long.rises), 2 * Work.KEEP // 60 + 20)  # (the older rises summed up)
        self.assertEqual(long.due, (WORK, 'drink'))  # due since the first hour, that one reminder
        long.shown(4 * WORK)
        for t in range(4 * WORK + 60, 5 * WORK + 60, 60):
            long.observe({'a': {'rose_at': t}}, t)
        self.assertEqual(long.due, (5 * WORK, 'stretch'))  # an hour from its showing

    def fail(self, start, end, good, rose, key='a', status='stale', every=60):
        """`key`'s readings failing every `every` seconds over [start, end): its last good one at `good`, its last
        rise at `rose` (as a failed reading keeps them)."""
        for t in range(start, end, every):
            self.w.observe({key: {'status': status, 'rose_at': rose, 'last_success_at': good}}, t)

    def test_an_account_at_work_whose_readings_fail_is_neither_at_work_nor_resting(self):
        self.work(0, 1800)  # at work until 1800 + ACTIVE
        self.fail(1860, 3060, good=1800, rose=1800)  # then twenty minutes of failed readings (rate limited, say)
        self.assertFalse(self.w.rested(3060))  # no break counted through them
        self.w.observe({'a': {'status': 'ok', 'rose_at': 3060, 'last_success_at': 3060}}, 3060)  # in again, at work
        self.assertEqual(self.w.start, 0)  # the hour goes on
        self.work(3120, 3 * WORK)
        self.assertEqual(self.w.due[0], 3060 + WORK - (1800 + ACTIVE))  # and the time it failed was no work either

    def test_an_account_idle_as_its_readings_began_to_fail_rests_meanwhile(self):
        self.work(0, 1800)
        for t in range(1860, 2700, 60):  # readings in, no rise: idle from 1800 + ACTIVE
            self.w.observe({'a': {'status': 'ok', 'rose_at': 1800, 'last_success_at': t}}, t)
        self.fail(2700, 3120, good=2640, rose=1800, status='rate_limited')
        self.w.observe({'a': {'status': 'ok', 'rose_at': 3120, 'last_success_at': 3120}}, 3120)
        self.assertEqual(self.w.start, 3120)  # a break all the same: the hour starts over

    def test_readings_failing_past_an_hour_count_as_rest_after_it(self):
        self.work(0, 1800)
        self.fail(1860, 1800 + WORK + BREAK + 60, good=1800, rose=1800, status='error')
        self.assertFalse(self.w.rested(1800 + WORK + BREAK - 1))
        self.assertTrue(self.w.rested(1800 + WORK + BREAK))  # held for WORK, then BREAK of rest
        self.w.observe({'a': {'status': 'ok', 'rose_at': 1800 + WORK + BREAK + 60}}, 1800 + WORK + BREAK + 60)
        self.assertEqual(self.w.start, 1800 + WORK + BREAK + 60)

    def test_a_rate_limited_account_at_work_holds_the_hour_through_the_store(self):
        from token_tv.state import UsageStore
        reading = {'status': 'ok', 'used': 10.0, 'at': 0}

        def fetch(account):
            ok = reading['status'] == 'ok'
            return {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'status': reading['status'],
                    'fetched_at': reading['at'], 'identity_verified': ok, 'source': 'mini',
                    'windows': [{'label': '5H', 'used_percent': reading['used'], 'resets_at': reading['at'] + 4 * H}]
                    if ok else []}
        store = UsageStore([{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex'}], fetch=fetch)

        def read(t, status='ok', more=.01):
            reading.update(status=status, at=NOW + t, used=reading['used'] + (more if status == 'ok' else 0))
            with mock.patch.object(state, 'time', SyntheticWall(NOW + t)):
                store.fetched.clear()
                store.waits.clear()  # (read again at once, whatever its back-off)
                store.refresh()
                self.w.observe(store.snapshot()['accounts'], NOW + t)
        for t in range(0, 1860, 60):
            read(t)  # at work, its usage rising each minute (the first rise with the second reading)
        for t in range(1860, 3060, 60):
            read(t, 'rate_limited')  # twenty minutes of 429s
        self.assertEqual(store.snapshot()['accounts']['codex_a']['status'], 'stale')
        for t in range(3060, 2 * WORK, 60):
            read(t)
        worked = 1800 + ACTIVE - 60  # before the 429s
        self.assertEqual(self.w.due[0], NOW + 3060 + WORK - worked)  # no break, and no work while it failed

    def test_a_shown_reminder_starts_the_next_hour_where_it_went_on(self):
        self.work(0, WORK)
        self.assertEqual(self.w.due[0], WORK)
        shown = WORK + 1300  # deferred (by a wait, say): the next hour counts from its showing, not its due time
        self.work(WORK + 60, shown - 60)
        self.w.shown(shown)
        self.assertIsNone(self.w.due)
        self.work(shown + 20, shown + 2 * WORK)
        self.assertEqual(self.w.due, (shown + WORK, 'stretch'))  # and its break picked anew

    def test_a_break_lets_a_reminder_not_yet_shown_go_and_needs_a_new_hour(self):
        self.work(0, WORK)
        self.assertIsNotNone(self.w.due)
        edge = WORK + ACTIVE
        self.assertFalse(self.w.rested(edge + BREAK - .001))
        self.assertTrue(self.w.rested(edge + BREAK))  # (not shown meanwhile)
        self.rise(edge + BREAK + 30)
        self.assertIsNone(self.w.due)
        self.work(edge + BREAK + 90, edge + BREAK + 30 + WORK - 1)
        self.assertIsNone(self.w.due)
        self.rise(edge + BREAK + 30 + WORK)
        self.assertEqual(self.w.due[0], edge + BREAK + 30 + WORK)

    def test_only_a_rise_is_work(self):
        for row in ({}, {'rose_at': None}, {'rose_at': True}, {'rose_at': float('nan')}, {'rose_at': 'x'}, 'x'):
            self.w.observe({'a': row}, 100)
        self.assertEqual((self.w.credit, self.w.last), (0.0, None))
        self.rise(100)
        for t in range(160, WORK + 1000, 60):
            self.w.observe({'a': {'rose_at': 100}}, t)  # the same rise read again and again: no more work
        self.assertEqual(self.w.credit, ACTIVE)
        self.assertIsNone(self.w.due)

    def test_the_next_due_time_is_known_while_work_goes_on(self):
        self.work(0, 600)
        self.assertEqual(self.w.next_due(600), None)  # (not reachable before this rise's activity ends)
        self.work(660, WORK - ACTIVE)
        self.assertEqual(self.w.next_due(WORK - ACTIVE), WORK)
        self.assertIsNone(Work(active=ACTIVE).next_due(0))

    def test_the_break_has_a_length_of_its_own(self):
        with mock.patch.object(moments, 'BREAK', BREAK // 2):  # the owner's number, apart from ACTIVE_SECONDS
            self.work(0, 1800)
            self.rise(1800 + ACTIVE + BREAK // 2)
            self.work(1800 + ACTIVE + BREAK // 2 + 60, 1800 + 2 * WORK)
            self.assertEqual(self.w.due[0], 1800 + ACTIVE + BREAK // 2 + WORK)
        self.assertEqual(self.w.active, ACTIVE)


class BreakStateTests(unittest.TestCase):
    """The break among the moments, on moments.CLOCK, with the wall clock moving with it."""
    def setUp(self):
        self.clock = FakeClock()
        self.wall0 = 1_800_000_000.0
        for patcher in (mock.patch.object(moments, 'CLOCK', self.clock),
                        mock.patch.object(moments, 'time', SyntheticTime(self.clock, self.wall0)),
                        mock.patch.object(moments, 'RANDOM', Picks('stretch', 'drink', 'stretch'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.woken = []
        self.m = Moments({'claude', 'codex'}, wake=lambda: self.woken.append(self.clock.t), active=ACTIVE)

    def wall(self):
        return self.wall0 + (self.clock.t - 10_000.0)

    def work_until(self, t, every=60):
        """A Codex account rising every `every` seconds (moments.CLOCK) up to `t`, each reading taken at once."""
        while self.clock.t + every <= t:
            self.clock.t += every
            self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})

    def test_after_an_hour_the_break_is_due_for_every_pet_once(self):
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})
        start = self.clock.t
        self.assertIsNone(self.m.next_change())  # the hour is not reachable on this rise alone
        self.work_until(start + WORK - 300)
        self.assertEqual(self.m.next_change(), start + WORK)  # it is now: TokenTV wakes for it, no reading needed
        self.work_until(start + WORK - 1)
        self.assertIsNone(self.m.wanted()[0])
        self.clock.t = start + WORK
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since, mark), (('break', 'stretch'), start + WORK, {'kind': 'stretch'}))
        self.assertTrue(self.m.busy())
        drawn = overlay(snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)]),
                                       ('codex_a', 'CODEX A', 'codex', [('5H', 20, 2 * H)])]), what, mark)
        self.assertEqual({key: row.get('moment') for key, row in drawn['accounts'].items()},
                         {'claude_a': {'kind': 'stretch'}, 'codex_a': {'kind': 'stretch'}})
        for _ in range(5):
            self.assertEqual(self.m.wanted()[0], ('break', 'stretch'))  # the same choice however often looked at
        self.m.shown(what, self.clock.t + 2)
        self.assertEqual(self.m.wanted()[:2], (None, self.clock.t + 2))  # one loop, then the usual face
        self.assertFalse(self.m.busy())

    def test_a_wait_outranks_it_and_it_plays_after_the_wait(self):
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})
        start = self.clock.t
        self.work_until(start + WORK - 120)
        self.m.note('claude.ask')
        self.work_until(start + WORK + 300)
        self.assertEqual(self.m.wanted()[0], ('needs', 2))  # due meanwhile, but the wait is on the clock
        self.m.note('claude.answered')
        answered = self.clock.t
        self.assertEqual(self.m.wanted()[:2], (('break', 'stretch'), answered))  # from the wait's end
        self.m.shown(('break', 'stretch'), answered + 3)
        self.work_until(answered + 3 + WORK - 60)
        self.assertIsNone(self.m.wanted()[0])
        self.work_until(answered + 3 + WORK + 60)
        self.assertEqual(self.m.wanted()[0], ('break', 'drink'))  # an hour from its showing

    def test_a_break_while_the_wait_was_on_lets_it_go(self):
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})
        start = self.clock.t
        self.work_until(start + WORK)
        self.m.note('claude.ask')
        last = self.clock.t
        self.clock.t = last + ACTIVE + BREAK + 5  # nobody at work meanwhile
        self.m.note('claude.answered')
        self.assertIsNone(self.m.wanted()[0])
        self.assertFalse(self.m.busy())
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})  # work again
        back = self.clock.t
        self.work_until(back + WORK - 60)
        self.assertIsNone(self.m.wanted()[0])  # a new hour from the work after the break
        self.work_until(back + WORK)
        self.assertEqual(self.m.wanted()[0], ('break', 'drink'))

    def test_a_reading_that_makes_it_due_wakes_the_publisher(self):
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})
        start = self.clock.t
        self.work_until(start + WORK - 30)
        self.woken.clear()
        self.clock.t = start + WORK + 30  # the next reading, late
        self.assertTrue(self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}}))
        self.assertEqual(self.woken, [self.clock.t])
        self.assertEqual(self.m.wanted()[:2], (('break', 'stretch'), start + WORK))

    def test_with_no_clock_to_show_it_on_the_break_stays_due_and_its_hour_counts_from_its_showing(self):
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})
        start = self.clock.t
        self.work_until(start + WORK)
        self.assertTrue(self.m.busy())
        count = self.m.count
        self.m.drop_bow()  # another face, no clock, or the clock not answering, as it came due
        self.assertEqual(self.m.count, count)  # nothing changed:
        self.assertEqual(self.m.wanted()[:2], (('break', 'stretch'), start + WORK))  # still due, the same break
        self.work_until(start + WORK + 900)  # a quarter of an hour more of work without a clock
        self.m.drop_bow()
        self.assertEqual(self.m.wanted()[:2], (('break', 'stretch'), start + WORK))  # that one reminder still, no other
        shown = self.clock.t
        self.m.shown(('break', 'stretch'), shown)  # a clock takes it at last
        self.work_until(shown + WORK - 60)
        self.assertIsNone(self.m.wanted()[0])
        self.work_until(shown + WORK + 60)
        self.assertEqual(self.m.wanted()[0], ('break', 'drink'))  # an hour from when it went on

    def test_it_takes_nothing_from_the_bows_minute(self):
        self.m.note('claude.end')
        self.m.shown(('done', 'claude'), self.clock.t)
        self.m.observe({'accounts': {'codex_a': {'provider': 'codex', 'rose_at': self.wall()}}})
        start = self.clock.t
        self.work_until(start + WORK)
        self.assertEqual(self.m.wanted()[0], ('break', 'stretch'))
        self.m.shown(('break', 'stretch'), self.clock.t)
        self.assertFalse(self.m.cooling(self.clock.t))  # a break starts no bow's minute
        self.m.note('claude.end')
        self.assertEqual(self.m.wanted()[0], ('done', 'claude'))


class BreakDrawingTests(unittest.TestCase):
    def picture(self, provider, kind):
        data = snapshot(NOW, [(f'{provider}_a', f"{arcade.SHORT_NAME.get(provider, provider.upper())} A", provider,
                               [('5H', 30, 2 * H)])])
        data['accounts'][f'{provider}_a']['moment'] = {'kind': kind}
        return arcade.render_arcade(data, NOW)

    def test_every_pet_drinks_and_stretches_moving_through_one_loop(self):
        water = (52, 140, 255)  # the glass's water, the same for every pet
        for provider in PETS:
            stages = {}
            for kind in BREAKS:
                gif = Image.open(io.BytesIO(self.picture(provider, kind)))
                shots = []
                for n in range(gif.n_frames):
                    gif.seek(n)
                    shots.append(gif.convert('RGB').crop((0, 28, 240, 170)))
                self.assertGreaterEqual(len({s.tobytes() for s in shots}), 10, (provider, kind))  # visibly moving
                colours = set().union(*({c for _, c in s.getcolors(65536)} for s in shots))
                self.assertEqual(water in colours, kind == 'drink', (provider, kind))
                stages[kind] = shots
            self.assertNotEqual(stages['drink'][len(stages['drink']) // 2].tobytes(),
                                stages['stretch'][len(stages['stretch']) // 2].tobytes())

    def test_its_readout_says_which_break(self):
        data = snapshot(NOW, [('grok_a', 'GROK A', 'grok', [('BUDGET', 30, 3 * D)])])
        row = dict(data['accounts']['grok_a'], key='grok_a')
        for kind, word in (('drink', 'DRINKING'), ('stretch', 'STRETCHING')):
            moved = dict(row, moment={'kind': kind})
            self.assertEqual(arcade.action_label(moved, arcade.scene_plan(moved, NOW), None, 0, 120), word)

    def test_the_pets_that_would_be_on_the_clock_take_it_and_nobody_else_joins(self):
        mark = {'kind': 'drink'}
        accounts = [(f'{p}_a', f'{p.upper()} A', p, [('5H', 20 + 5 * k, 2 * H)]) for k, p in enumerate(PETS)]
        data = snapshot(NOW, accounts)
        for minute in range(0, 30, 6):  # all idle, more than four: the four the rotation shows
            at = NOW + minute * 60
            usual = [row['key'] for row in arcade.shown_rows(data, at)]
            self.assertEqual([row['key'] for row in arcade.shown_rows(overlay(data, ('break', 'drink'), mark), at)],
                             usual)
        data['accounts']['codex_a']['active'] = True  # one at work: it alone is on the clock, and takes the break
        self.assertEqual([row['key'] for row in arcade.shown_rows(overlay(data, ('break', 'drink'), mark), NOW)],
                         ['codex_a'])

    def test_one_picture_holds_every_pet_on_the_clock(self):
        accounts = [('claude_a', 'CLAUDE A', 'claude', [('5H', 20, 2 * H)]), ('grok_a', 'GROK A', 'grok', [('BUDGET', 40, D)])]
        data = overlay(snapshot(NOW, accounts), ('break', 'stretch'), {'kind': 'stretch'})
        image = arcade.render_arcade(data, NOW)
        self.assertEqual(image[:4], b'GIF8')
        shots = arcade.arcade_frames(data, NOW)
        labels = {arcade.action_label(row, arcade.scene_plan(row, NOW), None, 0, 60)
                  for row in arcade.shown_rows(data, NOW)}
        self.assertEqual(labels, {'STRETCHING'})
        self.assertEqual(len(shots), 60)


class BreakTimingTests(unittest.TestCase):
    """Through live.main on the fake SD_PRO, from the readings alone: an hour of a Codex account's work."""
    def test_an_hour_of_work_brings_the_break_at_the_loops_end_then_the_usual_face_and_an_hour_more(self):
        picks = Picks('drink', 'stretch')
        patcher = mock.patch.object(moments, 'RANDOM', picks)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('5H', 20, 4 * H)]})
        used = 20.0

        def reading(n):  # the n-th poll's reading, a little more used than the last
            nonlocal used
            used += .004  # (never enough to change the picture: only the break does)
            rig.set('codex_a', '5H', used)
            rig.write(rig.now() + rig.poll_at(n) - rig.clock.now())
            rig.clock.to(rig.poll_at(n) + .5)

        reading(1)
        first_rise = rig.poll_at(1)  # the baseline was read at t0; this is the first rise
        n = 1
        while rig.poll_at(n + 1) < first_rise + WORK:
            n += 1
            reading(n)
        due = first_rise + WORK
        self.assertNotEqual(rig.showing()[0], rig.picture(('break', 'drink'), snapshot=rig.held()))
        before = rig.clock.now()
        rig.set('codex_a', '5H', used + .004)
        rig.write(rig.now() + due - rig.clock.now())
        rig.clock.to(due - .001)
        self.assertEqual([t for t in rig.switches(before) if t < due], [])  # not a moment before the hour
        boundary = rig.end_of_loop(due)
        rig.clock.to(boundary + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('break', 'drink'), snapshot=rig.held()))
        self.assertGreaterEqual(began, boundary)
        self.assertLess(began, boundary + .25)
        end = began + physical(image)
        rig.clock.to(end + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture(snapshot=rig.held()))  # one loop of it, then the usual face
        self.assertGreaterEqual(returned, end)
        self.assertLess(returned, end + .25)
        self.assertEqual(len(rig.switches(before)), 2)  # its entry and the return, nothing else
        self.assertEqual(picks.asked, 1)
        # the next hour counts from the break's showing
        n = max(k for k in range(n, n + 100) if rig.poll_at(k) <= rig.clock.now())
        while rig.poll_at(n + 1) < began + WORK:
            n += 1
            reading(n)
        self.assertEqual(picks.asked, 1)
        self.assertEqual(rig.showing()[0], rig.picture(snapshot=rig.held()))
        rig.set('codex_a', '5H', used + .004)
        rig.write(rig.now() + began + WORK - rig.clock.now())
        rig.clock.to(rig.end_of_loop(began + WORK) + .3)
        self.assertEqual(rig.showing()[0], rig.picture(('break', 'stretch'), snapshot=rig.held()))


if __name__ == '__main__':
    unittest.main()


class ClaudeBreakTimingTests(unittest.TestCase):
    """Claude's readings come at most every five minutes (state.MIN_FETCH_SECONDS): its rises still keep it at work
    the whole hour, and its pet gets the break."""
    def test_claude_alone_at_its_own_pace_of_readings(self):
        patcher = mock.patch.object(moments, 'RANDOM', Picks('stretch'))
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('claude',), wall=True, windows={'claude': [('5H', 30, 4 * H)]})
        every = state.MIN_FETCH_SECONDS['claude']
        used, k = 30.0, 0
        while True:
            k += 1
            at = rig.t0 + k * every  # a reading every five minutes, each a little higher
            used += .01
            rig.set('claude_a', '5H', used)
            rig.write(rig.now() + at - rig.clock.now())
            rig.clock.to(at + .5)
            if k == 1:
                first_rise = at
            if at + every > first_rise + WORK:
                break
        self.assertTrue(rig.held()['accounts']['claude_a']['active'])
        boundary = rig.end_of_loop(first_rise + WORK)
        rig.clock.to(boundary + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('break', 'stretch'), snapshot=rig.held()))
        self.assertGreaterEqual(began, boundary)
        self.assertLess(began, boundary + .25)


class BreakDuringOneOffTests(unittest.TestCase):
    """The hour of work done while a hidden one-off's quiet aftermath plays: the break goes in at that loop's end,
    not when the aftermath is over or at the next reading (time alone makes it due; TokenTV wakes for it)."""
    def test_a_break_due_during_a_quiet_aftermath_goes_at_its_loops_end(self):
        from PIL import Image as PILImage
        from token_tv import live
        from token_tv.lockbox import Box
        patcher = mock.patch.object(moments, 'RANDOM', Picks('drink'))
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('5H', 20, 4 * H)]})
        stage = lambda colour: PILImage.new('RGB', (120, 71), colour)  # noqa: E731
        box = Box('Test', 'unique', 'codex_a', tuple(stage((200, 40, 40)) for _ in range(4)), 100,
                  after=(stage((40, 40, 200)), stage((40, 200, 40))))
        opened = []

        def pick(snap):  # the box opens with the reading half a minute before the hour is done
            if not opened and moments.CLOCK.now() >= rig.poll_at(60):
                opened.append(moments.CLOCK.now())
                return box
            return None
        patcher = mock.patch.object(live.Lockbox, 'pick', side_effect=pick)
        patcher.start()
        self.addCleanup(patcher.stop)
        used = 20.0
        for k in range(1, 61):  # each reading measured half a minute before it is read: the hour ends between polls
            used += .004
            rig.set('codex_a', '5H', used)
            rig.write(rig.now() + rig.poll_at(k) - 30 - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        due = rig.poll_at(1) - 30 + WORK
        self.assertTrue(opened and opened[0] < due)
        rig.clock.to(due - .001)
        quiet, began = rig.showing()  # the one-off's quiet loop, on since its event's loop ended
        self.assertEqual(quiet, rig.picture(egg=__import__('dataclasses').replace(box, frames=box.after, after=(),
                                                                                    intro=False), snapshot=rig.held()))
        boundary = rig.end_of_loop(due)
        rig.clock.to(boundary + .3)
        image, at = rig.showing()
        self.assertEqual(image, rig.picture(('break', 'drink'), snapshot=rig.held()))
        self.assertGreaterEqual(at, boundary)
        self.assertLess(at, boundary + .25)


class BreakSendFailureTests(unittest.TestCase):
    """The break goes on, then the old picture fails to go off: the clock has shown it, so it does not come again.
    The break's send fails: it is still due, and goes as the next loop ends; its hour counts from then."""
    def test_a_break_the_clock_does_not_take_goes_at_the_next_loop_end_and_its_hour_counts_from_then(self):
        from token_tv.device import PhotoDisplay
        picks = Picks('drink', 'stretch')
        patcher = mock.patch.object(moments, 'RANDOM', picks)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('5H', 20, 4 * H)]})
        used = 20.0

        def reading(k):  # the k-th poll's reading, a little more used (never enough to change the picture)
            nonlocal used
            used += .004
            rig.set('codex_a', '5H', used)
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
        for k in range(1, 61):
            reading(k)
            rig.clock.to(rig.poll_at(k) + .5)
        upload, refuse = PhotoDisplay.upload, []

        def busy(self, name, image):  # the clock refuses one send (the break's), then takes them again
            if refuse:
                refuse.clear()
                raise OSError('the clock is busy')
            return upload(self, name, image)
        patcher = mock.patch.object(PhotoDisplay, 'upload', busy)
        patcher.start()
        self.addCleanup(patcher.stop)
        refuse.append(True)
        due = rig.poll_at(61)  # the hour of work since the first rise (the first poll's) is done
        reading(61)
        normal = rig.showing()[0]
        first = rig.end_of_loop(due)
        rig.clock.to(first + .3)
        self.assertEqual(refuse, [])  # (the break's send was refused)
        self.assertEqual(rig.showing()[0], normal)  # the clock kept its picture
        brk = rig.picture(('break', 'drink'), snapshot=rig.held())
        nxt = first + physical(normal)  # the next loop's end
        rig.clock.to(nxt + .3)
        image, began = rig.showing()
        self.assertEqual(image, brk)  # the break, still due, as that loop ended
        self.assertGreaterEqual(began, nxt - 1e-6)  # (its own sum of the loop, to the last bit)
        self.assertLess(began, nxt + .25)
        self.assertEqual(picks.asked, 1)
        k = 62
        while rig.poll_at(k) < began + WORK:
            reading(k)
            rig.clock.to(rig.poll_at(k) + .5)
            k += 1
        self.assertEqual([image for _, image in rig.played].count(brk), 1)  # once, and no other yet
        self.assertEqual(picks.asked, 1)
        reading(k)
        rig.clock.to(rig.end_of_loop(began + WORK) + .3)
        self.assertEqual(rig.showing()[0], rig.picture(('break', 'stretch'), snapshot=rig.held()))  # an hour on


    def test_a_break_on_the_clock_is_not_played_again_after_a_lost_answer(self):
        from token_tv.device import PhotoDisplay
        patcher = mock.patch.object(moments, 'RANDOM', Picks('drink', 'stretch'))
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('5H', 20, 4 * H)]})
        used = 20.0
        for k in range(1, 61):
            used += .004
            rig.set('codex_a', '5H', used)
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        toggle, lose = PhotoDisplay.toggle, []

        def flaky(self, category, key, value, enabled):  # the old one's switch-off: done, its answer lost
            toggle(self, category, key, value, enabled)
            if lose and not enabled:
                lose.clear()
                raise OSError('answer lost')
        patcher = mock.patch.object(PhotoDisplay, 'toggle', flaky)
        patcher.start()
        self.addCleanup(patcher.stop)
        lose.append(True)
        rig.set('codex_a', '5H', used + .004)
        rig.write(rig.now() + rig.poll_at(61) - rig.clock.now())
        rig.clock.to(rig.poll_at(61) + 30)
        self.assertEqual(lose, [])  # (the switch-off's answer was lost)
        drawn = [image for _, image in rig.played]
        brk = rig.picture(('break', 'drink'), snapshot=rig.held())
        self.assertEqual(drawn.count(brk), 1)  # it went on once
        for k in range(62, 66):  # the next readings: the usual face back, the break not again
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        rig.clock.advance(30)
        self.assertEqual([image for _, image in rig.played].count(brk), 1)
        self.assertEqual(rig.showing()[0], rig.picture(snapshot=rig.held()))
