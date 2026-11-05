"""v2 phase 2, x3: a window that, at its pace over the last RATE_WINDOW, would reach 100% in under HORIZON (and is
still under 100%) blinks its battery beside SLOW, until the pace says otherwise or the window resets. The pet goes
on as it was. The pace is each window's own, from its readings' own times."""
import datetime
import io
import sys
import time
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import Rig  # noqa: E402

from token_tv import arcade, moments, readout, sources, state  # noqa: E402
from token_tv.moments import WORK, overlay  # noqa: E402
from token_tv.sample import H, snapshot  # noqa: E402
from token_tv.state import HORIZON, RATE_WINDOW, UsageStore, running_out  # noqa: E402

LIMIT = 100
NOW = int(time.mktime((2026, 11, 1, 14, 1, 0, 0, 0, -1)))  # Sunday 2:01 pm wherever the tests run (the stage dims at night)
T0 = 1_800_000_000  # the readings' clock in the history tests


def linear(eta, final=70.0, at=T0, samples=4):
    """A whole RATE_WINDOW of readings ending at `at` with `final` % used, rising at the pace that reaches LIMIT in
    `eta` seconds; their times and values as (measured at, used %, resets at)."""
    rate = Fraction(LIMIT - final) / Fraction(eta)
    times = [at - RATE_WINDOW + Fraction(RATE_WINDOW) * k / (samples - 1) for k in range(samples)]
    return [(float(t), float(Fraction(final) - rate * (at - t)), at + 3 * H) for t in times]


class SyntheticWall:
    """The time module with its wall clock stopped at `at`."""
    def __init__(self, at):
        self.at = at

    def time(self):
        return self.at

    def __getattr__(self, name):
        import time
        return getattr(time, name)


class Readings:
    """A UsageStore read through its own refresh, its readings the test's: {key: [(label, used, resets_at)]} at `at`."""
    def __init__(self, keys=('codex_a',)):
        self.now, self.rows = T0, {}
        accounts = [{'key': key, 'alias': key.upper(), 'provider': key.split('_')[0]} for key in keys]
        self.store = UsageStore(accounts, fetch=self.fetch)

    def fetch(self, account):
        windows = self.rows[account['key']]
        return {'key': account['key'], 'alias': account['alias'], 'provider': account['provider'], 'status': 'ok',
                'fetched_at': self.now, 'identity_verified': True, 'source': 'mini',
                'windows': [{'label': label, 'used_percent': used, 'resets_at': resets} for label, used, resets in windows]}

    def read(self, at, **windows):
        self.now = at
        self.rows.update(windows)
        self.store.refresh()
        return {key: row['slow'] for key, row in self.store.snapshot()['accounts'].items()}


class CachedReadings:
    """A UsageStore reading one Codex account through CodexBar, whose reply is its cache: as old as CodexBar's own
    measurement (`updatedAt`), OLD once that is over a quarter of an hour old. The replies are the test's."""
    ACCOUNT = {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'a@example.com',
               'codexbar_command': 'codexbar'}

    def __init__(self, test):
        self.wall = SyntheticWall(T0)
        self.store = UsageStore([self.ACCOUNT])
        self.reply = {}
        for patcher in (mock.patch.object(sources, 'time', self.wall), mock.patch.object(state, 'time', self.wall),
                        mock.patch.object(sources, 'codexbar_payload', lambda account: [{'provider': 'codex', 'usage': {
                            'updatedAt': self.reply['measured'], 'primary': {
                                'usedPercent': self.reply['used'], 'windowMinutes': 300, 'resetsAt': self.reply['resets']}}}])):
            patcher.start()
            test.addCleanup(patcher.stop)

    @staticmethod
    def iso(at):
        return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).isoformat()

    def read(self, at, used, resets, measured=None):
        """The row after a reply at `at` of CodexBar's 5H window, `used` %, resetting at `resets`, as measured at
        `measured` (default: just now)."""
        self.wall.at = at
        self.reply.update(measured=self.iso(at if measured is None else measured), used=used, resets=self.iso(resets))
        self.store.refresh()
        return self.store.snapshot()['accounts']['codex_a']

    def at(self, when):
        """The row as the dashboard and the clock see it at `when`, with no reply since."""
        self.wall.at = when
        return self.store.snapshot()['accounts']['codex_a']

    def warned(self, test, resets):
        """Four good readings over RATE_WINDOW, 40 % to 70 % by T0: running out (SLOW)."""
        for at, used in ((T0 - 900, 40), (T0 - 600, 50), (T0 - 300, 60), (T0, 70)):
            row = self.read(at, used, resets)
        test.assertEqual((row['status'], row['slow']), ('ok', ['5H']))


class ProjectionTests(unittest.TestCase):
    def test_the_threshold_is_strict_and_exact(self):
        for eta, warns in ((HORIZON / 2, True), (HORIZON * .99, True), (HORIZON, False), (HORIZON * 1.01, False),
                           (HORIZON * 2, False)):
            readings = linear(eta)
            self.assertEqual(running_out(readings), warns, eta)
            (t0, u0, _), (t1, u1, _) = readings[0], readings[-1]
            exact = (LIMIT - Fraction(u1)) * (Fraction(t1) - Fraction(t0)) / (Fraction(u1) - Fraction(u0))
            self.assertEqual(exact < HORIZON, warns, (eta, float(exact)))  # the oracle from the endpoints alone
        flat = [(T0 - RATE_WINDOW + k * 300, 70.0, T0 + H) for k in range(4)]
        self.assertFalse(running_out(flat))
        self.assertFalse(running_out([(T0 - RATE_WINDOW, 99.0, T0 + H), (T0, 100.0, T0 + H)]))  # at the limit
        self.assertFalse(running_out([(T0 - RATE_WINDOW, 99.0, T0 + H), (T0, 104.0, T0 + H)]))  # past it
        self.assertFalse(running_out(linear(HORIZON / 4)[1:]))  # less than a whole RATE_WINDOW: nothing to say
        self.assertFalse(running_out(linear(HORIZON / 4)[-1:]))

    def test_a_tie_in_the_decimals_read_is_a_tie(self):
        # Readings such as 55.3 -> 70.2 over RATE_WINDOW reach the limit in just HORIZON, as written; the binary
        # floats nearest them would make some a hair faster and warn.
        for u0, u1 in ((55.3, 70.2), (77.05, 84.7), (70.9, 80.6), (49.9, 66.6), (70.0, 80.0)):
            rise, left = Fraction(str(u1)) - Fraction(str(u0)), LIMIT - Fraction(str(u1))
            self.assertEqual(left * RATE_WINDOW, rise * HORIZON, (u0, u1))  # (each is a tie at these numbers)
            middle = round((u0 + u1) / 2, 3)
            self.assertFalse(running_out([(T0 - RATE_WINDOW, u0, T0 + H), (T0 - RATE_WINDOW / 2, middle, T0 + H),
                                          (T0, u1, T0 + H)]), (u0, u1))
            store = Readings()
            for at, used in ((T0 - RATE_WINDOW, u0), (T0 - RATE_WINDOW / 2, middle), (T0, u1)):
                slow = store.read(at, codex_a=[('5H', used, T0 + H)])
            self.assertEqual(slow, {'codex_a': []}, (u0, u1))
        self.assertTrue(running_out([(T0 - RATE_WINDOW, 55.29, T0 + H), (T0, 70.2, T0 + H)]))  # a hair faster: warns

    def test_the_pace_is_the_whole_trailing_window_not_the_last_step_or_the_earlier_past(self):
        recent = linear(HORIZON / 2)
        steep = [(T0 - 3 * RATE_WINDOW, 1.0, T0 + 3 * H)] + recent  # A: a long steep past
        gentle = [(T0 - 3 * RATE_WINDOW, recent[0][1] - .1, T0 + 3 * H)] + recent  # B: a gentle one
        r = Fraction(LIMIT - 70) / (2 * HORIZON)
        low = float(70 - r * RATE_WINDOW)
        burst = [(T0 - RATE_WINDOW, low, T0 + H), (T0 - RATE_WINDOW / 3, low, T0 + H), (T0, 70.0, T0 + H)]  # C
        for name, readings, warns in (('A', steep, True), ('B', gentle, True), ('C', burst, False)):
            store = Readings()
            for at, used, resets in readings:
                slow = store.read(at, codex_a=[('5H', used, resets)])
            self.assertEqual(slow['codex_a'] == ['5H'], warns, name)

    def test_more_or_fewer_readings_of_the_same_history_change_nothing(self):
        for spacing in ([0, 1], [0, .2, .9, 1], [0, .5, .5, .5, 1], [0, .1, .3, .35, .6, .61, .95, 1]):
            store = Readings()
            for k in spacing:
                at = T0 - RATE_WINDOW + RATE_WINDOW * k
                used = 40 + 30 * k  # one pace: 30% a RATE_WINDOW, so 30% left is one RATE_WINDOW off
                slow = store.read(at, codex_a=[('5H', used, T0 + H)])
                slow = store.read(at, codex_a=[('5H', used, T0 + H)])  # the same reading again: nothing new
            self.assertEqual(slow, {'codex_a': ['5H']}, spacing)

    def test_each_window_and_account_has_its_own_pace(self):
        store = Readings(('codex_a', 'codex_b'))
        hot = linear(HORIZON / 3)
        for k, (at, used, resets) in enumerate(hot):
            order = ('codex_b', 'codex_a') if k % 2 else ('codex_a', 'codex_b')  # read in either order
            for key in order:
                windows = ([('5H', used, resets), ('WEEK', 30.0, T0 + 4 * 86400)] if key == 'codex_a'
                           else [('5H', 30.0 + k * .01, resets)])
                slow = store.read(at, **{key: windows})
        self.assertEqual(slow, {'codex_a': ['5H'], 'codex_b': []})

    def test_a_reset_clears_the_warning_and_its_pace_starts_over(self):
        for reset_value in (5.0, 90.0):  # a new window lower, or one whose first reading is not lower
            store = Readings()
            for at, used, resets in linear(HORIZON / 3):
                slow = store.read(at, codex_a=[('5H', used, resets)])
            self.assertEqual(slow, {'codex_a': ['5H']})
            new = T0 + 5 * H  # a new reset time: a new window
            slow = store.read(T0 + 60, codex_a=[('5H', reset_value, new)])
            self.assertEqual(slow, {'codex_a': []}, reset_value)  # neither the old growth nor the jump counts
            for k in range(1, 20):  # flat in the new window
                slow = store.read(T0 + 60 + 60 * k, codex_a=[('5H', reset_value, new)])
                self.assertEqual(slow, {'codex_a': []})
            start, last = T0 + 60 * 20, reset_value
            for k in range(16):  # then a whole new history running out fast
                last = reset_value + (100 - reset_value) * .9 * k / 15 if reset_value < 50 else 90 + .6 * k
                slow = store.read(start + 60 * k, codex_a=[('5H', last, new)])
            self.assertEqual(slow, {'codex_a': ['5H']}, reset_value)

    def test_old_rises_age_out_with_flat_readings(self):
        store = Readings()
        readings = linear(HORIZON / 3, samples=16)
        for at, used, resets in readings:
            slow = store.read(at, codex_a=[('5H', used, resets)])
        self.assertEqual(slow, {'codex_a': ['5H']})
        at, used, resets = readings[-1]
        seen = []
        for k in range(1, 17):
            seen.append(store.read(at + 60 * k, codex_a=[('5H', used, resets)])['codex_a'])
        self.assertEqual(seen[-1], [])  # a whole flat RATE_WINDOW later: no warning
        cleared = seen.index([])
        self.assertTrue(all(s == [] for s in seen[cleared:]))  # once cleared, it stays so
        # the oracle at the reading where it cleared: the whole window's rise over its own RATE_WINDOW
        start = at + 60 * (cleared + 1) - RATE_WINDOW
        before = max(r for r in readings if r[0] <= start)
        after = min(r for r in readings + [(at + 60 * j, used, resets) for j in range(1, 17)] if r[0] > start)
        begun = Fraction(before[1]) + (Fraction(after[1]) - Fraction(before[1])) * (start - Fraction(before[0])) / (
            Fraction(after[0]) - Fraction(before[0]))
        self.assertGreaterEqual((LIMIT - Fraction(used)) * RATE_WINDOW, (Fraction(used) - begun) * HORIZON)

    def test_a_reading_grown_old_keeps_slow_till_the_last_good_one_is_horizon_old(self):
        store = Readings()
        for at, used, resets in linear(HORIZON / 3):
            store.read(at, codex_a=[('5H', used, resets)])
        for after, slow in ((state.STALE_SECONDS + 1, ['5H']), (HORIZON - 1, ['5H']), (HORIZON, [])):
            with mock.patch.object(state, 'time', SyntheticWall(T0 + after)):  # no new reading since: OLD
                row = store.store.snapshot()['accounts']['codex_a']
            self.assertEqual((row['status'], row['slow']), ('stale', slow), after)

    def test_a_failed_reading_keeps_slow_and_readings_failing_past_the_horizon_let_it_go(self):
        store = Readings()
        for at, used, resets in linear(HORIZON / 3):
            store.read(at, codex_a=[('5H', used, resets)])
        failed = {'at': T0}
        store.store.fetch = lambda account: {'key': account['key'], 'alias': account['alias'], 'provider': 'codex',
                                             'status': 'error', 'windows': [], 'fetched_at': failed['at']}
        for after, slow in ((60, ['5H']), (HORIZON - 1, ['5H']), (HORIZON, [])):
            failed['at'] = T0 + after
            with mock.patch.object(state, 'time', SyntheticWall(T0 + after)):
                store.store.fetched.clear()  # (read again at once, whatever its back-off)
                store.store.waits.clear()
                store.store.refresh()
                row = store.store.snapshot()['accounts']['codex_a']
            self.assertEqual((row['status'], row['slow']), ('stale', slow), after)  # OLD, SLOW as it was
        store.store.fetch = store.fetch  # a good reading again, no higher: its own pace says it, from its history
        self.assertEqual(store.read(T0 + HORIZON + 60, codex_a=[('5H', 70.0, T0 + 3 * H)]), {'codex_a': []})

    def test_an_old_copy_that_brings_a_new_window_lets_slow_go_and_the_old_copies_after_it_bring_none_back(self):
        # Codex's review: CodexBar's cache, newer than the last good reading but read 16 minutes after it measured,
        # brings the window that began at its reset, at 0 %; then old copies of it every minute for 45 minutes.
        readings = CachedReadings(self)
        readings.warned(self, T0 + 60)
        row = readings.read(T0 + 1020, 0, T0 + 18060, measured=T0 + 60)
        self.assertEqual((row['status'], row['windows'][0]['used_percent'], row['slow']), ('stale', 0, []))
        for after in range(1080, 3721, 60):
            row = readings.read(T0 + after, 0, T0 + 18060, measured=T0 + after - 960)
            self.assertEqual((row['status'], row['slow']), ('stale', []), after)

    def test_old_copies_of_the_same_window_keep_slow_only_till_the_last_good_reading_is_horizon_old(self):
        readings = CachedReadings(self)
        readings.warned(self, T0 + 2 * H)
        for after in range(1020, HORIZON + 1, 60):  # copies 16 minutes old, each newer than the last, a little higher
            row = readings.read(T0 + after, 72, T0 + 2 * H + 30, measured=T0 + after - 960)  # (its reset 30 s off)
            self.assertEqual((row['status'], row['slow']), ('stale', ['5H'] if after < HORIZON else []), after)
        readings = CachedReadings(self)
        readings.warned(self, T0 + 2 * H)
        readings.read(T0 + HORIZON - 60, 72, T0 + 2 * H, measured=T0 + HORIZON - 1020)
        for after, slow in ((HORIZON - 1, ['5H']), (HORIZON, [])):  # time alone, with no reply since
            self.assertEqual(readings.at(T0 + after)['slow'], slow, after)

    def test_an_old_copy_with_a_lower_use_or_another_reset_time_lets_slow_go(self):
        for used, resets, slow in ((69.9, T0 + 2 * H, []),  # lower: a correction
                                   (75, T0 + 3 * H, []),  # higher, but another window (its reset an hour off)
                                   (70, T0 + 2 * H - 30, ['5H'])):  # the same window, as high (its reset 30 s off)
            readings = CachedReadings(self)
            readings.warned(self, T0 + 2 * H)
            row = readings.read(T0 + 1020, used, resets, measured=T0 + 60)
            self.assertEqual((row['status'], row['slow']), ('stale', slow), (used, resets))
            store = readings.store  # and a failed reading after it keeps what that one kept
            store.fetch = lambda account: {'key': account['key'], 'alias': account['alias'], 'provider': 'codex',
                                           'status': 'error', 'windows': [], 'fetched_at': T0 + 1080}
            readings.wall.at = T0 + 1080
            store.refresh()
            self.assertEqual(store.snapshot()['accounts']['codex_a']['slow'], slow, (used, resets))


class WarningDrawingTests(unittest.TestCase):
    def pictures(self, slow, provider='codex', windows=(('5H', 84, 80 * 60), ('WEEK', 40, 4 * 86400)), **extra):
        data = snapshot(NOW, [(f'{provider}_a', f'{provider.upper()} A', provider, list(windows))])
        data['accounts'][f'{provider}_a'].update(active=True, slow=slow, **extra)
        return arcade.arcade_frames(data, NOW), data

    def test_the_battery_blinks_beside_slow_and_the_pet_goes_on_as_it_was(self):
        warned, data = self.pictures(['5H'])
        calm, _ = self.pictures([])
        stage = lambda frame: frame.crop((0, 28, 240, 170)).tobytes()  # noqa: E731
        self.assertEqual([stage(f) for f in warned], [stage(f) for f in calm])  # the same pet, the same moves
        case = lambda frame: {frame.getpixel((x, 196)) for x in range(26, 66)}  # the 5H battery's top edge  # noqa: E731
        phases = [readout.WARN in case(frame) for frame in warned]
        self.assertTrue(any(phases) and not all(phases))  # red, then not, inside the one GIF
        self.assertFalse(any(readout.WARN in case(frame) for frame in calm))
        week = lambda frame: {frame.getpixel((x, 217)) for x in range(26, 66)}  # noqa: E731
        self.assertFalse(any(readout.WARN in week(frame) for frame in warned))  # only the window running out
        label = arcade.action_label(dict(data['accounts']['codex_a'], key='codex_a'),
                                    arcade.scene_plan(data['accounts']['codex_a'], NOW), None, 0, 120)
        self.assertEqual(label, 'SLOW')
        words = warned[0].crop((70, 174, 230, 192))
        self.assertIn(readout.WARN, {c for _, c in words.getcolors(65536)})  # SLOW in red

    def test_a_wait_keeps_needs_you_and_the_battery_still(self):
        data = snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('5H', 84, 80 * 60), ('WEEK', 40, 4 * 86400)])])
        data['accounts']['claude_a'].update(slow=['5H'])
        waiting = overlay(data, ('needs', 1), {'kind': 'needs', 'since': 0, 'level': 1})
        row = dict(waiting['accounts']['claude_a'], key='claude_a')
        self.assertEqual(arcade.action_label(row, arcade.scene_plan(row, NOW), None, 0, 120), 'NEEDS YOU')
        frames = arcade.arcade_frames(waiting, NOW)
        self.assertFalse(any(readout.WARN in {f.getpixel((x, 196)) for x in range(26, 66)} for f in frames))

    def test_one_gif_of_it_needs_no_more_sends_to_keep_blinking(self):
        frames, _ = self.pictures(['5H'])
        image = arcade.encode(frames)
        self.assertLess(len(image), arcade.BUDGET)
        gif = Image.open(io.BytesIO(image))
        self.assertGreater(gif.n_frames, 10)  # the blink is in its pictures


class WarningTimingTests(unittest.TestCase):
    """Through live.main and the store's own readings: SLOW goes on once at a loop's end, stays without a send while
    it holds, and goes off once, as the pace over the last RATE_WINDOW stops saying the window runs out."""
    def test_slow_comes_on_once_holds_without_sends_and_goes_off_once(self):
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('5H', 60, 4 * H)]})
        polls = RATE_WINDOW // rig.poll  # a whole RATE_WINDOW of readings
        used, k = 60.0, 0
        for k in range(1, polls + 1):  # 1.5% a minute: 17.5% left at the end is under 12 minutes away
            used = 60 + 1.5 * k
            rig.set('codex_a', '5H', used)
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        self.assertEqual(rig.held()['accounts']['codex_a']['slow'], ['5H'])
        rig.clock.to(rig.end_of_loop() + .3)
        on, began = rig.showing()
        self.assertEqual(on, rig.picture(snapshot=rig.held()))
        frames = Image.open(io.BytesIO(on))
        self.assertGreater(frames.n_frames, 1)
        held = []
        while True:  # flat now: the pace over the window falls, reading by reading
            k += 1
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
            held.append(rig.held()['accounts']['codex_a']['slow'])
            if not held[-1]:
                break
            self.assertEqual(rig.switches(began + .001), [])  # unchanged SLOW: nothing sent, nothing restarted
        cleared = rig.poll_at(k)
        self.assertLess(len(held), polls)  # gone within a RATE_WINDOW of flat readings
        boundary = rig.end_of_loop(cleared)
        rig.clock.to(boundary + .3)
        off, at = rig.showing()
        self.assertEqual(off, rig.picture(snapshot=rig.held()))
        self.assertNotEqual(off, on)
        self.assertGreaterEqual(at, boundary)
        self.assertLess(at, boundary + .25)
        self.assertEqual(len(rig.switches(began + .001)), 1)  # off once
        for j in range(1, 4):  # and flat readings after: nothing more
            rig.write(rig.now() + rig.poll_at(k + j) - rig.clock.now())
            rig.clock.to(rig.poll_at(k + j) + .5)
        self.assertEqual(len(rig.switches(began + .001)), 1)

    def test_one_failed_reading_keeps_slow_on_the_clock(self):
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('5H', 60, 4 * H)]})
        polls = RATE_WINDOW // rig.poll
        for k in range(1, polls + 1):
            rig.set('codex_a', '5H', 60 + 1.5 * k)
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.held()['accounts']['codex_a']['slow'], ['5H'])
        rig.readings['codex_a']['status'] = 'error'  # the next reading fails
        rig.write(rig.now() + rig.poll_at(polls + 1) - rig.clock.now())
        rig.clock.to(rig.poll_at(polls + 1) + .5)
        row = rig.held()['accounts']['codex_a']
        self.assertEqual((row['status'], row['slow']), ('stale', ['5H']))  # OLD, and still running out
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.showing()[0], rig.picture(snapshot=rig.held()))  # on the clock so: SLOW does not drop
        rig.readings['codex_a']['status'] = 'ok'
        rig.set('codex_a', '5H', 60 + 1.5 * (polls + 2))
        rig.write(rig.now() + rig.poll_at(polls + 2) - rig.clock.now())
        rig.clock.to(rig.poll_at(polls + 2) + .5)
        self.assertEqual(rig.held()['accounts']['codex_a']['slow'], ['5H'])  # and the next good one says it again


class WaitPriorityTests(unittest.TestCase):
    """SLOW on the clock, then Claude asks for you while the hour of work comes due and presses come in: NEEDS YOU
    keeps the readout, the presses are dropped, the warning goes on being worked out, and once you answer the break
    plays, then the usual face with SLOW again as it still holds (v2p2-42)."""
    def test_a_wait_over_slow_and_a_due_break(self):
        patcher = mock.patch.object(moments, 'RANDOM', type('Pick', (), {'choice': lambda self, options: 'drink'})())
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('claude',), wall=True, windows={'claude': [('5H', 40, 4 * H)]})
        every = state.MIN_FETCH_SECONDS['claude']

        def reading(k, used):
            rig.set('claude_a', '5H', used)
            rig.write(rig.now() + rig.t0 + k * every - rig.clock.now())
            rig.clock.to(rig.t0 + k * every + .5)

        used = 40.0
        for k in range(1, 14):  # slowly for 45 minutes, then fast: SLOW by the hour
            used += .2 if k <= 9 else 10
            reading(k, used)
            if k == 12:
                rig.clock.to(rig.end_of_loop() + .3)
                self.assertEqual(rig.held()['accounts']['claude_a']['slow'], ['5H'])
                self.assertEqual(rig.showing()[0], rig.picture(snapshot=rig.held()))  # the battery blinking, SLOW
                asked = rig.t0 + 12 * every + 100
                rig.clock.to(asked)
                rig.say('claude.ask')
                rig.clock.to(rig.end_of_loop() + .3)
                self.assertEqual(rig.showing()[0], rig.picture(('needs', 1), snapshot=rig.held()))
                rig.clock.advance(60)
                rig.say('claude.pet')
        due = rig.t0 + every + WORK  # the first rise's hour, at the 13th reading
        rig.clock.to(due + 50)
        rig.say('claude.snack')
        self.assertEqual(rig.held()['accounts']['claude_a']['slow'], ['5H'])  # still worked out meanwhile
        waiting = rig.picture(('needs', 1), snapshot=rig.held())
        self.assertEqual(rig.showing()[0], waiting)  # NEEDS YOU, not SLOW, not the break, not a treat
        answered = rig.clock.now()
        rig.say('claude.answered')
        boundary = rig.end_of_loop(answered)
        rig.clock.to(boundary + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('break', 'drink'), snapshot=rig.held()))  # straight to the break
        self.assertLess(began, boundary + .25)
        rig.clock.to(began + rig.loop(image) + .3)
        self.assertEqual(rig.showing()[0], rig.picture(snapshot=rig.held()))  # then SLOW again, as it holds
        self.assertEqual(rig.held()['accounts']['claude_a']['slow'], ['5H'])
        self.assertEqual(len(rig.switches(answered)), 2)  # the break and the usual face: nothing between


if __name__ == '__main__':
    unittest.main()
