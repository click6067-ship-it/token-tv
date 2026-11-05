"""v2: the agents' moments. The state machine (time injected), the endpoint, Codex's notify program, and when the
clock gets each picture (a fake SD_PRO and a fake clock, through live.main itself)."""
import http.client
import io
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import own_tmp, temp_dir
from test_device import sd_pro_clock, serve, ultra_clock

from token_tv import arcade, display, live, moments, readout, sources, state
from token_tv.arcade import gif_seconds
from token_tv.display import render_page
from token_tv.moments import Moments, loop_end, overlay
from token_tv.state import MIN_FETCH_SECONDS, UsageStore

ROOT = Path(__file__).resolve().parent.parent
FRAME_SD = .142  # the shortest an SD_PRO shows a picture, in seconds (live.DEVICE_FRAME_MS): the fake clock's own tick


def physical(image, frame=FRAME_SD):
    """How long an SD_PRO plays one loop of `image`: each of its pictures, as encoded, for the delay the GIF gives it
    but at least `frame` seconds (m1), read from the GIF here, apart from live.loop_seconds. The sum is in whole ms,
    as the GIF gives its delays: exact, so a loop's end here and TokenTV's agree to the last bit."""
    from PIL import Image
    source, total = Image.open(io.BytesIO(image)), 0
    for n in range(source.n_frames):
        source.seek(n)
        total += max(source.info['duration'], frame * 1000)
    return total / 1000


class FakeClock:
    """moments.CLOCK for tests: time moves only when the test moves it, and each wait that comes due on the way
    runs in turn, so a jump to thirty minutes still passes five and fifteen."""
    def __init__(self, start=10_000.0):
        self.t = start
        self.cond = threading.Condition()
        self.sleepers = {}  # thread -> (when its wait ends, the event that ends it sooner)
        self.held = set()  # usage readings a test holds up on purpose (their threads): no reason not to settle

    def now(self):
        with self.cond:
            return self.t

    def wait(self, event, seconds):
        me = threading.get_ident()
        with self.cond:
            self.sleepers[me] = (self.t + max(0.0, seconds), event)
            self.cond.notify_all()
            try:
                while not event.is_set() and self.t < self.sleepers[me][0]:
                    self.cond.wait(.002)
                return event.is_set()
            finally:
                del self.sleepers[me]

    def settle(self, timeout=20):
        """Return once every waiting thread sleeps towards a time still to come (seen so a few times in a row), and
        no usage reading is under way but those the test holds: TokenTV never waits for one, so it would land at
        whatever time the test has moved on to."""
        end, calm = time.monotonic() + timeout, 0
        while time.monotonic() < end:
            with self.cond:
                quiet = bool(self.sleepers) and all(d > self.t and not e.is_set() for d, e in self.sleepers.values())
            quiet = quiet and not any(thread.name == 'TokenTV reading' and thread not in self.held
                                      for thread in threading.enumerate())
            calm = calm + 1 if quiet else 0
            if calm >= 4:
                return
            time.sleep(.004)
        raise AssertionError('TokenTV did not settle')

    def advance(self, seconds):
        target = self.now() + seconds
        while True:
            self.settle()
            with self.cond:
                due = min((d for d, _ in self.sleepers.values()), default=target)
                self.t = min(max(due, self.t), target)
                self.cond.notify_all()
                if self.t >= target:
                    break
        self.settle()

    def to(self, when):
        self.advance(max(0.0, when - self.now()))

    def bump(self, seconds):
        """Move on by `seconds` now, as the real time something took (a test maps real waits onto this clock)."""
        with self.cond:
            self.t += seconds
            self.cond.notify_all()


class StateTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        patcher = mock.patch.object(moments, 'CLOCK', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.woken = []
        self.m = Moments({'claude', 'codex'}, wake=lambda: self.woken.append(self.clock.t))

    def at(self, t):
        self.clock.t = t

    def test_a_wait_grows_more_insistent_and_is_let_go_after_thirty_minutes(self):
        m, t0 = self.m, self.clock.t
        self.assertTrue(m.note('claude.ask'))
        what, since, mark = m.wanted()
        self.assertEqual((what, since), (('needs', 1), t0))
        self.assertEqual((mark['kind'], mark['level']), ('needs', 1))
        self.assertEqual(m.next_change(), t0 + 300)
        for t, level, since in ((59.999, 1, 0), (60, 1, 0), (299.999, 1, 0), (300, 2, 300), (899.999, 2, 300),
                                (900, 3, 900), (1799.999, 3, 900)):
            self.at(t0 + t)
            self.assertEqual(m.wanted()[:2], (('needs', level), t0 + since), t)
        self.assertEqual(m.next_change(), t0 + 1800)
        self.at(t0 + 1830)  # looked at late: still due from the deadline itself
        self.assertEqual(m.wanted()[:2], (None, t0 + 1800))
        self.assertIsNone(m.next_change())

    def test_waits_are_counted_across_sessions_and_keep_the_first_ones_age(self):
        m, t0 = self.m, self.clock.t
        m.note('claude.ask')
        self.at(t0 + 10)
        self.assertFalse(m.note('claude.ask'))  # a second session waiting: the same picture
        self.at(t0 + 20)
        self.assertFalse(m.note('claude.answered'))  # the first answered: the second still waits, as old as the first
        self.at(t0 + 301)
        self.assertEqual(m.wanted()[:2], (('needs', 2), t0 + 300))
        self.assertTrue(m.note('claude.answered'))
        self.assertEqual(m.wanted()[:2], (None, t0 + 301))
        self.assertFalse(m.note('claude.answered'))  # one answer too many (from a wait let go): never below none
        self.at(t0 + 400)
        m.note('claude.ask')  # a new wait starts afresh
        self.assertEqual((m.wanted()[:2], m.next_change()), ((('needs', 1), t0 + 400), t0 + 700))
        self.assertEqual(len(self.woken), 3)  # the first wait, its clearing, the new one

    def test_an_expired_wait_is_forgotten_and_a_new_one_starts_at_the_hand(self):
        m, t0 = self.m, self.clock.t
        m.note('claude.ask')
        m.note('claude.ask')
        self.at(t0 + 1800)
        self.assertIsNone(m.wanted()[0])
        m.note('claude.ask')
        self.assertEqual(m.wanted()[:2], (('needs', 1), t0 + 1800))
        m.note('claude.answered')
        self.assertIsNone(m.wanted()[0])  # the two let go are not counted any more

    def test_the_waits_are_let_go_thirty_minutes_after_the_continuous_wait_began(self):
        m, t0 = self.m, self.clock.t
        m.note('claude.ask')  # session A, never answered
        self.at(t0 + 1700)
        self.assertFalse(m.note('claude.ask'))  # session B joins the wait: as old as A's
        self.assertEqual(m.next_change(), t0 + 1800)  # B's ask does not put it off
        self.at(t0 + 1799.999)
        self.assertEqual(m.wanted()[:2], (('needs', 3), t0 + 900))
        self.at(t0 + 1800)  # thirty minutes of waiting in all: both are let go, B's with A's
        self.assertEqual(m.wanted()[:2], (None, t0 + 1800))
        self.assertEqual((m.waits, m.next_change()), (0, None))
        self.at(t0 + 1850)
        self.assertFalse(m.note('claude.answered'))  # B answered after all: none counted, nothing to close
        self.at(t0 + 1900)
        self.assertTrue(m.note('claude.ask'))  # session C: a new wait, at the hand, as old as itself
        self.assertEqual((m.wanted()[:2], m.next_change()), ((('needs', 1), t0 + 1900), t0 + 2200))
        self.at(t0 + 1950)
        self.assertTrue(m.note('claude.answered'))
        self.assertEqual(m.wanted()[:2], (None, t0 + 1950))

    def test_waits_never_answered_are_let_go_together_and_a_new_ask_starts_afresh(self):
        m, t0 = self.m, self.clock.t
        m.note('claude.ask')
        self.at(t0 + 1200)
        m.note('claude.ask')  # neither is ever answered (the sessions were killed)
        self.at(t0 + 3000)  # looked at late: let go from the deadline itself
        self.assertEqual(m.wanted()[:2], (None, t0 + 1800))
        self.assertEqual(m.waits, 0)
        m.note('claude.ask')
        self.assertEqual(m.wanted()[:2], (('needs', 1), t0 + 3000))  # a new wait starts afresh
        self.assertTrue(m.note('claude.answered'))  # one answer closes it: the two let go are not counted
        self.assertIsNone(m.wanted()[0])

    def test_tokentvs_own_waits_look_again_at_the_time_every_few_seconds(self):
        event = threading.Event()
        began = time.monotonic()
        self.assertFalse(moments.Clock().wait(event, .05))
        self.assertGreaterEqual(time.monotonic() - began, .04)
        event.set()
        self.assertTrue(moments.Clock().wait(event, 30))

    def test_the_clock_counts_the_time_the_computer_sleeps(self):
        if sys.platform.startswith('linux') and hasattr(time, 'CLOCK_BOOTTIME'):
            self.assertAlmostEqual(moments.Clock().now(), time.clock_gettime(time.CLOCK_BOOTTIME), delta=1)
        elif sys.platform == 'darwin':
            self.assertAlmostEqual(moments.Clock().now(), time.clock_gettime(time.CLOCK_MONOTONIC), delta=1)

    def test_one_bow_in_any_rolling_minute_shared_by_claude_and_codex_none_queued(self):
        m, t0 = self.m, self.clock.t
        self.assertTrue(m.note('claude.end'))
        self.assertEqual(m.wanted()[:2], (('done', 'claude'), t0))
        self.assertFalse(m.note('codex.end'))  # one is due already: dropped
        self.at(t0 + 3)
        m.shown(('done', 'claude'), t0 + 3)  # it went on the clock: one loop, then the usual face
        self.assertEqual(m.wanted()[:2], (None, t0 + 3))
        for later in (20, 59.999):
            self.at(t0 + 3 + later)
            self.assertFalse(m.note('codex.end'))
            self.assertFalse(m.note('claude.end'))
        self.at(t0 + 3 + 60)
        self.assertIsNone(m.wanted()[0])  # nothing comes back when the minute is up
        self.assertTrue(m.note('codex.end'))
        self.assertEqual(m.wanted()[:2], (('done', 'codex'), t0 + 63))

    def test_a_wait_outranks_a_bow_and_nothing_put_off_comes_back(self):
        m = self.m
        m.note('claude.end')
        m.note('claude.ask')  # the bow not yet on the clock is dropped
        self.assertEqual(m.wanted()[0], ('needs', 1))
        self.assertFalse(m.note('codex.end'))
        self.assertFalse(m.note('claude.end'))
        m.note('claude.answered')
        self.assertIsNone(m.wanted()[0])
        self.assertIsNone(m.bowed)  # and nothing dropped counts against the next bow
        self.assertTrue(m.note('claude.end'))  # a turn's end after its answer bows
        self.assertEqual(m.wanted()[0], ('done', 'claude'))

    def test_a_bow_with_no_clock_to_bow_on_is_dropped_and_holds_nothing_back(self):
        m = self.m
        m.note('claude.end')
        m.drop_bow()
        self.assertIsNone(m.wanted()[0])
        self.assertTrue(m.note('codex.end'))

    def test_moments_of_a_service_not_shown_are_ignored_and_cost_nothing(self):
        m = Moments({'codex'})
        for name in ('claude.ask', 'claude.answered', 'claude.end'):
            self.assertFalse(m.note(name))
        self.assertEqual((m.wanted()[0], m.next_change(), m.busy()), (None, None, False))
        self.assertTrue(m.note('codex.end'))
        self.assertEqual(m.wanted()[0], ('done', 'codex'))
        for name in ('claude.Ask', 'claude', '', 'codex.ask', 'claude.ask '):
            with self.assertRaises(ValueError):
                m.note(name)

    def test_the_moment_is_drawn_on_its_services_rows_only_and_adds_none(self):
        snapshot = {'accounts': {'ca': {'provider': 'claude'}, 'cb': {'provider': 'claude'}, 'x': {'provider': 'codex'}}}
        mark = {'kind': 'needs', 'since': 1.0, 'level': 2}
        drawn = overlay(snapshot, ('needs', 2), mark)
        self.assertEqual([k for k, row in drawn['accounts'].items() if row.get('moment')], ['ca', 'cb'])
        self.assertNotIn('moment', snapshot['accounts']['ca'])  # a copy, for drawing only
        bow = overlay(snapshot, ('done', 'codex'), {'kind': 'done', 'at': 1.0})
        self.assertEqual([k for k, row in bow['accounts'].items() if row.get('moment')], ['x'])
        self.assertIs(overlay(snapshot, None, None), snapshot)
        self.assertEqual(overlay({'accounts': {'x': {'provider': 'codex'}}}, ('needs', 1), mark)['accounts'],
                         {'x': {'provider': 'codex'}})

    def test_a_change_goes_at_the_end_of_the_loop_playing_when_it_came(self):
        shown = {'at': 100.0, 'loop': 4.2}
        self.assertAlmostEqual(loop_end(shown, 101.05), 104.2)
        self.assertAlmostEqual(loop_end(shown, 104.2), 104.2)  # right at an end: that end
        self.assertAlmostEqual(loop_end(shown, 104.21), 108.4)  # just after: the next one, never mid-loop
        self.assertAlmostEqual(loop_end(shown, 100.0), 104.2)  # as a picture starts: its first loop plays out
        self.assertAlmostEqual(loop_end(shown, 90.0), 104.2)  # wanted before it went on: it still plays one loop
        self.assertIsNone(loop_end({'at': None, 'loop': None}, 5))

    def test_a_moment_joins_the_pets_on_the_clock_and_leaves_none_out(self):
        def row(provider, **extra):
            return dict({'provider': provider, 'alias': provider.upper(), 'status': 'ok', 'windows': []}, **extra)
        waiting, bowing = {'kind': 'needs', 'since': 0, 'level': 1}, {'kind': 'done', 'at': 0}
        shown = lambda accounts: [r['key'] for r in arcade.shown_rows({'accounts': accounts})]  # noqa: E731
        others = {'x': row('codex', active=True), 'g': row('grok'), 'p': row('copilot'), 'a': row('antigravity')}
        # Claude waiting: its rows alone, the whole loop, however many services there are and whoever works
        self.assertEqual(shown({'c': row('claude', moment=waiting), **others}), ['c'])
        self.assertEqual(shown({'c': row('claude', moment=waiting), 'd': row('claude', moment=waiting), 'x': row('codex')}),
                         ['c', 'd'])
        self.assertEqual(shown({'c': row('claude'), **others}), ['x'])  # answered: back as before (Codex at work)
        self.assertEqual(shown({'c': row('claude'), 'x': row('codex'), 'g': row('grok')}), ['c', 'x', 'g'])  # all idle
        # a bow shares the loop as ever: beside the working ones, or with every pet while all are idle
        self.assertEqual(shown({'c': row('claude', moment=bowing), 'x': row('codex', active=True), 'g': row('grok')}),
                         ['c', 'x'])
        self.assertEqual(shown({'c': row('claude'), 'x': row('codex', moment=bowing), 'g': row('grok')}), ['c', 'x', 'g'])

    def test_needs_you_is_on_the_clock_the_whole_loop_beside_other_services(self):
        claude = {'claude_a': {'provider': 'claude', 'alias': 'C', 'status': 'ok', 'windows': []}}
        rows = dict(claude, **{p + '_a': {'provider': p, 'alias': p, 'status': 'ok', 'windows': []}
                               for p in ('codex', 'grok', 'copilot')})
        mark = {'kind': 'needs', 'since': 0, 'level': 1}
        frames = arcade.arcade_frames(overlay({'accounts': rows}, ('needs', 1), mark), 10_000)
        alone = arcade.arcade_frames(overlay({'accounts': claude}, ('needs', 1), mark), 10_000)
        # every frame of the loop is Clawd waiting, as if Claude were the only service on the clock
        self.assertEqual(len(frames), len(alone))
        self.assertEqual([k for k, (a, b) in enumerate(zip(frames, alone)) if a.tobytes() != b.tobytes()], [])

    def test_a_bow_dips_once_a_loop_then_stands_proud(self):
        def turns(providers, bowing):
            """For each pet's turn in the loop: the frames, cut to where the pet is (for Codex, its cloud above the
            garden, whose flowers lean on their own)."""
            rows = {p + '_a': {'provider': p, 'alias': p, 'status': 'ok',
                               'windows': [{'label': 'WEEK', 'used_percent': 50, 'resets_at': 10_000 + 86400}]}
                    for p in providers}
            frames = arcade.arcade_frames(overlay({'accounts': rows}, ('done', bowing), {'kind': 'done', 'at': 0}), 10_000)
            share = len(frames) // len(providers)
            where = (0, 28, 240, 108) if bowing == 'codex' else (0, 28, 240, 170)
            index = providers.index(bowing)
            return [frame.crop(where).tobytes() for frame in frames[index * share:(index + 1) * share]]

        def dips(turn):
            """The runs of frames in which the pet is not as it stands at the end of its turn: (first, last)."""
            runs, first = [], None
            for k, frame in enumerate(turn + [turn[-1]]):
                if frame != turn[-1] and first is None:
                    first = k
                elif frame == turn[-1] and first is not None:
                    runs.append((first, k - 1))
                    first = None
            return runs
        four = ('claude', 'codex', 'grok', 'copilot')
        for style in ('low', 'tilt'):
            with mock.patch.object(arcade, 'BOW_STYLE', style):
                for providers in (('claude',), ('claude', 'codex'), four):
                    turn = turns(providers, 'claude')
                    runs = dips(turn)
                    self.assertEqual(len(runs), 1, (style, providers, runs))
                    self.assertGreaterEqual(runs[0][1] - runs[0][0], 3, (style, providers))  # a dip, not a twitch
                    self.assertLess(runs[0][1], len(turn) - 3, (style, providers))  # then standing to the end
        for providers in (('codex',), ('claude', 'codex'), four):
            turn = turns(providers, 'codex')
            runs = dips(turn)
            self.assertEqual(len(runs), 1, (providers, runs))
            self.assertGreaterEqual(runs[0][1] - runs[0][0], 3, providers)
            self.assertLess(runs[0][1], len(turn) - 3, providers)

    def test_each_bow_picks_one_of_the_two_at_random_and_keeps_it_while_it_plays(self):
        rows = {'claude_a': {'provider': 'claude', 'alias': 'C', 'status': 'ok',
                             'windows': [{'label': 'WEEK', 'used_percent': 50, 'resets_at': 10_000 + 86400}]}}

        def loop(at):
            frames = arcade.arcade_frames(overlay({'accounts': rows}, ('done', 'claude'), {'kind': 'done', 'at': at}),
                                          10_000)
            return [frame.tobytes() for frame in frames]
        drawn = {}
        for style in arcade.BOW_STYLES:
            with mock.patch.object(arcade, 'BOW_STYLE', style):
                drawn[style] = loop(0)
        self.assertNotEqual(drawn['low'], drawn['tilt'])
        picked = [arcade.bow_style({'kind': 'done', 'at': 1000.0 + k * 61}) for k in range(40)]
        self.assertEqual(set(picked), set(arcade.BOW_STYLES))  # both turn up
        for at, style in ((1000.0 + k * 61, p) for k, p in enumerate(picked[:6])):
            self.assertEqual(loop(at), drawn[style])  # the bow drawn is the one picked
            self.assertEqual(loop(at), loop(at))  # and every drawing of it is the same picture

    def test_the_hey_sign_rests_its_stick_on_clawds_head_however_high_the_hop(self):
        from PIL import ImageChops
        rows = {'claude_a': {'provider': 'claude', 'alias': 'C', 'status': 'ok',
                             'windows': [{'label': 'WEEK', 'used_percent': 50, 'resets_at': 10_000 + 86400}]}}

        def drawn():  # the scene of each frame of the loop, on the stage's own pixels (frames show it doubled)
            mark = {'kind': 'needs', 'since': 0, 'level': 3}
            return [frame.crop((0, 28, 240, 170)).resize((120, 71), 0)
                    for frame in arcade.arcade_frames(overlay({'accounts': rows}, ('needs', 3), mark), 10_000)]
        frames = drawn()
        with mock.patch.object(arcade, 'held_sign', lambda *args: None):
            hopping = drawn()  # Clawd, no sign
            with mock.patch.object(arcade, 'place_clawd', lambda *args, **kwargs: None):
                ground = drawn()  # the scene alone
        ends = set()
        for k, (frame, clawd, bare) in enumerate(zip(frames, hopping, ground)):
            sign = ImageChops.difference(frame, clawd)
            end = sign.getbbox()[3] - 1  # the stick's last row: the sign's lowest
            stick = [x for x in range(sign.width) if sign.getpixel((x, end)) != (0, 0, 0)]
            on_clawd = lambda x, y: clawd.getpixel((x, y)) != bare.getpixel((x, y))  # noqa: E731
            self.assertTrue(stick and all(on_clawd(x, end) for x in stick), k)  # its end on Clawd's head
            self.assertFalse(any(on_clawd(x, end - 1) for x in stick), k)  # resting there, not pushed into it
            ends.add(end)
        self.assertGreater(len(ends), 3)  # up and down with every hop

    def test_the_waits_thresholds_are_the_drawings(self):
        self.assertEqual(arcade.NEEDS_LEVELS, ((moments.SIGN, 3), (moments.HOP, 2), (0, 1)))
        row = {'key': 'c', 'alias': 'C', 'provider': 'claude', 'status': 'ok', 'windows': [],
               'moment': {'kind': 'needs', 'since': 0, 'level': 2}}
        self.assertEqual(arcade.scene_plan(row, 10_000)['moment']['level'], 2)  # live.py's level, not the wall clock's


def raw(port, data, timeout=4.0):
    """Send raw bytes over loopback; (status or None, the whole answer, seconds until it closed)."""
    began = time.monotonic()
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as conn:
        try:
            conn.sendall(data)
        except OSError:
            pass
        chunks = []
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError:
            pass
    answer = b''.join(chunks)
    status = int(answer.split(b' ', 2)[1]) if answer.startswith(b'HTTP/') else None
    return status, answer, time.monotonic() - began


def dripped(connect, first, rest=b'', every=0, limit=6.0):
    """A slow sender: `first` at once over a new connection (`connect()`), then `rest` a byte every `every` seconds.
    (What TokenTV answered, seconds until it closed the connection: `limit` if it kept it open.)"""
    conn = connect()
    conn.settimeout(limit)
    began, over = time.monotonic(), threading.Event()

    def send():
        try:
            conn.sendall(first)
            for k in range(len(rest)):
                if over.wait(every):
                    return
                conn.sendall(rest[k:k + 1])
        except OSError:
            pass
    threading.Thread(target=send, daemon=True).start()
    answer = b''
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            answer += chunk
    except OSError:  # reset, or still open at `limit`
        pass
    took = time.monotonic() - began
    over.set()
    conn.close()
    return answer, took


def post_bytes(port, body=b'{"moment":"claude.ask"}', host=None, headers=None, path='/moment', method='POST',
               content_type='application/json', length=True):
    lines = [f'{method} {path} HTTP/1.1']
    if host is not False:
        lines.append('Host: ' + (f'127.0.0.1:{port}' if host is None else host))
    if content_type:
        lines.append('Content-Type: ' + content_type)
    if length is True:
        lines.append(f'Content-Length: {len(body)}')
    elif length is not False:
        lines.append(f'Content-Length: {length}')
    lines += [f'{k}: {v}' for k, v in (headers or [])]
    return '\r\n'.join(lines).encode('latin-1') + b'\r\n\r\n' + body


class EndpointTests(unittest.TestCase):
    """POST /moment over loopback: what it takes, what it refuses, and that it answers fast whatever is sent."""
    def setUp(self):
        self.m = Moments({'claude', 'codex'})
        self.serve(live.handler(UsageStore([]), agents=self.m))

    def serve(self, handler):
        server = live.QuietServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port
        return server

    def send(self, **kwargs):
        return raw(self.port, post_bytes(self.port, **kwargs))

    def test_a_moment_is_taken_with_an_empty_204(self):
        status, answer, took = self.send()
        self.assertEqual(status, 204)
        self.assertTrue(answer.endswith(b'\r\n\r\n'))  # no body
        self.assertNotIn(b'Access-Control', answer)
        self.assertLess(took, 1)
        self.assertEqual(self.m.wanted()[0], ('needs', 1))
        for name in ('claude.answered', 'claude.end', 'codex.end'):
            self.assertEqual(self.send(body=json.dumps({'moment': name}).encode())[0], 204)
        self.assertEqual(self.m.wanted()[0], ('done', 'claude'))

    def test_only_this_computers_names_and_a_plain_host_header(self):
        for host in (f'127.0.0.1:{self.port}', f'localhost:{self.port}', f'[::1]:{self.port}', 'localhost'):
            self.assertEqual(self.send(host=host)[0], 204, host)
        self.assertEqual(self.m.waits, 4)
        for host in ('evil.example', f'localhost.evil.example:{self.port}', f'127.0.0.1.evil.example:{self.port}',
                     'mini.local', '192.168.0.20'):
            status, answer, _ = self.send(host=host)
            self.assertEqual(status, 403, host)
            self.assertNotIn(host.encode(), answer)
        for host in (False, '', '[::1', f'user@127.0.0.1:{self.port}', '127.0.0.1:80:80', '127.0.0.1 x'):
            status, answer, _ = self.send(host=host)
            self.assertTrue(400 <= status < 500, (host, status))
        status, _, _ = self.send(headers=[('Host', 'evil.example')])  # two Host headers: which one?
        self.assertEqual(status, 400)
        self.assertEqual(self.m.waits, 4)  # none of these changed anything
        self.assertEqual(self.send()[0], 204)  # and a valid one still works

    def test_in_brackets_only_ipv6s_loopback_for_a_moment_and_for_the_dashboard_alike(self):
        def get(host):
            return raw(self.port, f'GET /display HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode('latin-1'))[0]
        for host in ('[::1]', f'[::1]:{self.port}'):
            self.assertEqual(self.send(host=host)[0], 204, host)
            self.assertEqual(get(host), 200, host)
        for host in ('[127.0.0.1]', f'[127.0.0.1]:{self.port}', f'[127.0.0.1.]:{self.port}', f'[::2]:{self.port}',
                     f'[fe80::1]:{self.port}', '[evil]', '[localhost]', '[]', f'[::1]x:{self.port}', '[[::1]]'):
            status, answer, _ = self.send(host=host)
            self.assertTrue(400 <= status < 500, (host, status))
            self.assertNotIn(host.encode(), answer)
            self.assertEqual(get(host), 403, host)
        self.assertEqual(self.m.waits, 2)  # the two by [::1], nothing else

    def test_a_tokentv_open_to_the_network_takes_moments_by_its_own_names_only(self):
        m = Moments({'claude'})
        self.serve(live.handler(UsageStore([]), agents=m, local_only=False,
                                names={'mini', 'mini.local', '192.168.0.20', 'desktop_ab'}))
        self.assertEqual(self.send(host=f'mini:{self.port}')[0], 204)
        self.assertEqual(self.send(host=f'other-host:{self.port}')[0], 403)
        self.assertEqual(m.waits, 1)
        self.assertEqual(self.send(host=f'DESKTOP_AB:{self.port}')[0], 204)  # a Windows name may hold an underscore
        self.assertEqual(raw(self.port, f'GET /display HTTP/1.1\r\nHost: DESKTOP_AB:{self.port}\r\n\r\n'.encode())[0], 200)
        self.assertEqual(self.send(host=f'other_host:{self.port}')[0], 403)
        self.assertEqual(m.waits, 2)

    def test_an_ask_is_told_how_long_the_wait_it_joined_has_lasted(self):
        clock = FakeClock()
        patcher = mock.patch.object(moments, 'CLOCK', clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        age = lambda answer: [line for line in answer.split(b'\r\n') if line.lower().startswith(b'tokentv-wait-age:')]  # noqa: E731
        status, answer, _ = self.send()
        self.assertEqual((status, age(answer)), (204, [b'TokenTV-Wait-Age: 0.0']))
        clock.t += 1500
        status, answer, _ = self.send()  # another session's prompt joins the wait, 25 minutes in
        self.assertEqual((status, age(answer)), (204, [b'TokenTV-Wait-Age: 1500.0']))
        for name in ('claude.answered', 'claude.end', 'codex.end'):
            self.assertEqual(age(self.send(body=json.dumps({'moment': name}).encode())[1]), [], name)
        clock.t += 301  # the whole wait let go at its 30 minutes: the next prompt starts a new one
        self.assertEqual(age(self.send()[1]), [b'TokenTV-Wait-Age: 0.0'])

    def test_get_moment_is_no_moment(self):
        def check(**kwargs):
            return raw(self.port, post_bytes(self.port, method='GET', body=b'', content_type=None, length=False, **kwargs))

        def head(answer):
            return answer.split(b'\r\n\r\n')[0].lower().split(b'\r\n')[1:]
        status, answer, took = check()
        self.assertEqual(status, 405)
        self.assertIn(b'allow: post', head(answer))
        self.assertNotIn(b'tokentv', answer.lower())  # and it says nothing of whose endpoint this is
        self.assertTrue(answer.endswith(b'\r\n\r\n'))  # nothing more
        self.assertLess(took, 1)
        # refused as a moment is: another name, a web page, a query, no Host
        for kwargs, code in (({'host': 'evil.example'}, 403), ({'headers': [('Origin', 'https://evil.example')]}, 403),
                             ({'path': '/moment?moment=claude.ask'}, 400), ({'host': False}, 400)):
            status, answer, _ = check(**kwargs)
            self.assertEqual(status, code, kwargs)
            self.assertNotIn(b'tokentv', answer.lower(), kwargs)
        self.assertIsNone(self.m.wanted()[0])  # none of it changed anything
        status, answer, _ = self.send()  # a moment is a 204, as ever
        self.assertEqual(status, 204)
        self.assertNotIn(b'tokentv:', answer.lower())
        self.assertEqual(raw(self.port, f'GET /display HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n'.encode())[0], 200)
        self.assertEqual(check(path='/moment/')[0], 404)
        self.serve(live.handler(UsageStore([])))  # a TokenTV without the moments: nobody's endpoint
        status, answer, _ = check()
        self.assertEqual(status, 404)
        self.assertNotIn(b'tokentv', answer.lower())

    def test_moments_come_only_from_this_computer(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        b.sendall(post_bytes(8787))
        b.shutdown(socket.SHUT_WR)
        server = mock.Mock()
        handler = live.handler(UsageStore([]), agents=self.m)
        handler(a, ('192.168.0.33', 51000), server)  # from another computer on the network
        self.assertIn(b' 403 ', b.recv(65536))
        self.assertIsNone(self.m.wanted()[0])

    def test_no_web_page_can_send_one(self):
        for origin in ('https://evil.example', 'null', f'http://127.0.0.1:{self.port + 1}', 'http//127.0.0.1',
                       f'http://localhost:{self.port}'):
            status, _, _ = self.send(headers=[('Origin', origin)])
            self.assertEqual(status, 403, origin)
        self.assertEqual(self.send(headers=[('Origin', f'http://127.0.0.1:{self.port}')])[0], 204)  # its own page
        status, answer, _ = raw(self.port, post_bytes(self.port, method='OPTIONS', body=b'', content_type=None, headers=[
            ('Origin', 'https://evil.example'), ('Access-Control-Request-Method', 'POST')]))
        self.assertEqual(status, 405)
        self.assertNotIn(b'Access-Control-Allow', answer)
        for kind, body in (('text/plain', b'{"moment":"claude.ask"}'), ('application/x-www-form-urlencoded', b'moment=claude.ask'),
                           ('multipart/form-data; boundary=x', b'--x\r\n\r\nclaude.ask\r\n--x--'), (None, b'{"moment":"claude.ask"}')):
            self.assertEqual(self.send(body=body, content_type=kind)[0], 415, kind)
        self.assertEqual(self.m.waits, 1)

    def test_an_origin_that_does_not_even_parse_is_refused_like_a_foreign_one_without_a_traceback(self):
        self.serve(live.handler(UsageStore([]), mock.Mock(), agents=self.m))  # with display settings, as TokenTV runs
        said = io.StringIO()
        with mock.patch('sys.stderr', said):
            for origin in ('http://[::1', 'http://[evil', 'https://[', f'http://[::1]x:{self.port}',
                           f'http://[127.0.0.1:{self.port}'):
                status, answer, _ = self.send(headers=[('Origin', origin)])
                self.assertEqual(status, 403, origin)
                self.assertNotIn(origin.encode(), answer)
                for path, body in (('/display/style', b'{"style":"arcade"}'), ('/collection/replay', b'{"check":"x"}')):
                    status, answer, _ = self.send(path=path, body=body, headers=[('Origin', origin)])
                    self.assertEqual(status, 403, (path, origin))
                    self.assertNotIn(origin.encode(), answer)
        self.assertEqual(said.getvalue(), '')  # nothing went wrong in TokenTV, so nothing printed
        self.assertIsNone(self.m.wanted()[0])
        self.assertEqual(self.send()[0], 204)  # and a valid one still works

    def test_only_the_finite_names_and_nothing_beside_them(self):
        hostile = ['<script>alert(1)</script>', '$(touch /tmp/x)', '../../etc/passwd']
        bodies = [b'{"moment":"claude.asked"}', b'{"moment":""}', b'{"moment":"CLAUDE.ASK"}', b'{"moment":"Claude.ask"}',
                  b'{"moment":"claude.ask","prompt":"secret"}', b'{"moment":"claude.ask","session":"s1"}',
                  b'{"moment":1}', b'{"moment":null}', b'{"moment":["claude.ask"]}', b'["claude.ask"]',
                  b'[{"moment":"claude.ask"}]', b'"claude.ask"', b'{"moment":"claude.ask","moment":"claude.end"}',
                  b'{"moment":"claude.ask"', b'claude.ask', b'{"moment":"claude\xff.ask"}', b'\xfe\xff\x00{',
                  b'{"Moment":"claude.ask"}', b'{"moment":"claude.ask "}'] + \
                 [json.dumps({'moment': text}).encode() for text in hostile]
        for body in bodies:
            status, answer, _ = self.send(body=body)
            self.assertEqual(status, 400, body)
            for text in hostile + ['secret']:
                self.assertNotIn(text.encode(), answer)
        self.assertEqual(raw(self.port, post_bytes(self.port, method='GET', body=b''))[0], 405)  # GET is no moment
        self.assertEqual(self.send(path='/moment?moment=claude.ask')[0], 400)
        self.assertEqual(self.send(path='/moment/')[0], 404)
        self.assertIsNone(self.m.wanted()[0])
        self.assertEqual(self.send()[0], 204)  # a valid one afterwards still works

    def test_oversized_or_broken_bodies_are_refused_before_they_are_read(self):
        status, _, took = raw(self.port, post_bytes(self.port, body=b'{' + b' ' * (1 << 20) + b'}'))
        self.assertEqual(status, 413)
        self.assertLess(took, 2)
        for length, code in (('1000000000', 413), ('257', 413), ('-5', 400), ('abc', 400), ('0', 400), ('+24', 400)):
            status, _, took = raw(self.port, post_bytes(self.port, body=b'', length=length))
            self.assertEqual(status, code, length)
            self.assertLess(took, 2)
        self.assertEqual(raw(self.port, post_bytes(self.port, length=False))[0], 400)  # no length
        body = b'{"moment":"claude.ask"}'
        twice = post_bytes(self.port, body=body, headers=[('Content-Length', '5')])
        self.assertEqual(raw(self.port, twice)[0], 400)
        chunked = post_bytes(self.port, body=b'17\r\n' + body + b'\r\n0\r\n\r\n', length=False,
                             headers=[('Transfer-Encoding', 'chunked')])
        self.assertEqual(raw(self.port, chunked)[0], 400)
        both = post_bytes(self.port, body=body, headers=[('Transfer-Encoding', 'chunked')])
        self.assertEqual(raw(self.port, both)[0], 400)
        self.assertIsNone(self.m.wanted()[0])

    def test_a_sender_that_stops_part_way_is_let_go_and_others_are_answered_meanwhile(self):
        stalled = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        self.addCleanup(stalled.close)
        whole = post_bytes(self.port, body=b'{"moment":"claude.end"}')
        stalled.sendall(whole[:-10])  # the last ten bytes never come
        began = time.monotonic()
        status, _, took = self.send()  # another client meanwhile
        self.assertEqual(status, 204)
        self.assertLess(took, 1)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        conn.request('GET', '/display')
        self.assertEqual(conn.getresponse().status, 200)
        stalled.settimeout(4)
        answer = b''
        try:
            while True:
                chunk = stalled.recv(4096)
                if not chunk:
                    break
                answer += chunk
        except OSError:
            pass
        self.assertLess(time.monotonic() - began, 2.5)  # closed, not held open
        self.assertIn(b' 408 ', answer)  # it ran out of time
        self.assertEqual(self.m.wanted()[0], ('needs', 1))  # the cut-short end never counted

    def test_a_refused_sender_that_keeps_dripping_is_let_go_in_about_a_second(self):
        conn = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        self.addCleanup(conn.close)
        conn.sendall(post_bytes(self.port, body=b'', length='200', host='evil.example'))  # refused at its Host
        began = time.monotonic()
        while time.monotonic() - began < 4:
            try:
                conn.sendall(b'x')  # a byte every fifth of a second, for as long as it is let
            except OSError:
                break
            time.sleep(.2)
        self.assertLess(time.monotonic() - began, 2)

    def test_a_moment_has_two_seconds_to_arrive_wherever_it_dawdles_and_a_late_one_gets_a_408(self):
        tcp = lambda: socket.create_connection(('127.0.0.1', self.port), timeout=5)  # noqa: E731
        moment = post_bytes(self.port)
        line = moment.split(b'\r\n')[0] + b'\r\n'
        head = moment.split(b'\r\n\r\n')[0] + b'\r\n\r\n'
        slow = {'stops in its headers': (tcp, moment[:30]),
                'drips its headers': (tcp, line, moment[len(line):], .15),
                'drips its body': (tcp, head, moment[len(head):], .6)}
        got = {}
        threads = [threading.Thread(target=lambda name, args: got.__setitem__(name, dripped(*args)), args=item)
                   for item in slow.items()]
        for thread in threads:
            thread.start()
        time.sleep(.3)
        status, _, took = self.send(body=b'{"moment":"claude.ask"}')  # another client meanwhile
        self.assertEqual(status, 204)
        self.assertLess(took, 1)
        for thread in threads:
            thread.join(8)
        for name, (answer, took) in got.items():
            self.assertLess(took, live.READ_SECONDS + .6, name)  # let go, not held
            self.assertIn(b' 408 ', answer, name)
        self.assertEqual(self.m.waits, 1)  # only the client that sent its request in time

    def test_a_moment_that_comes_whole_but_late_is_a_408_and_counts_for_nothing(self):
        # Its first byte at once, the rest 8 s later in one go: while the first line is still coming it has the
        # dashboard's 10 s, so the rest lands in one read and the headers and body are read from what came.
        moment = post_bytes(self.port)
        conn = socket.create_connection(('127.0.0.1', self.port), timeout=15)
        self.addCleanup(conn.close)
        conn.sendall(moment[:1])
        time.sleep(8)
        conn.sendall(moment[1:])
        sent, answer = time.monotonic(), b''
        try:
            while chunk := conn.recv(65536):
                answer += chunk
        except OSError:
            pass
        self.assertTrue(answer.startswith(b'HTTP/'), answer)
        self.assertEqual(int(answer.split(b' ', 2)[1]), 408)
        self.assertLess(time.monotonic() - sent, 1)  # answered as it came
        self.assertEqual(self.m.waits, 0)  # the sender gave up on it long ago: nothing counted
        self.assertIsNone(self.m.wanted()[0])
        self.assertEqual(self.send()[0], 204)  # one in time is taken as ever
        self.assertEqual(self.m.waits, 1)

    def test_the_dashboards_other_requests_have_longer_so_a_slow_phone_is_answered(self):
        preferences = mock.Mock()
        preferences.snapshot.return_value = {'style': 'arcade', 'status': 'ok', 'styles': ['pixel', 'arcade']}
        self.serve(live.handler(UsageStore([]), preferences, agents=self.m))

        def late(head, rest, after):
            """`head` at once, `rest` `after` seconds later, as a phone on poor Wi-Fi sends; (the answer, seconds
            until it began)."""
            conn = socket.create_connection(('127.0.0.1', self.port), timeout=15)
            began, answered = time.monotonic(), None

            def rest_later():
                time.sleep(after)
                try:
                    conn.sendall(rest)
                except OSError:
                    pass
            with conn:
                conn.sendall(head)
                threading.Thread(target=rest_later, daemon=True).start()
                answer = b''
                try:
                    while chunk := conn.recv(65536):
                        answered = answered or time.monotonic() - began
                        answer += chunk
                except OSError:
                    pass
            return answer, answered
        host = f'Host: 127.0.0.1:{self.port}\r\n'.encode()
        answer, _ = late(b'GET /display HTTP/1.1\r\n', host + b'\r\n', 3)  # its headers three seconds late
        self.assertIn(b' 200 ', answer)
        body = b'{"style":"arcade"}'
        style = (b'POST /display/style HTTP/1.1\r\n' + host + b'Content-Type: application/json\r\n' +
                 f'Content-Length: {len(body)}\r\n\r\n'.encode())
        answer, _ = late(style, body, 2.3)  # its body 2.3 s after the headers
        self.assertIn(b' 200 ', answer)
        preferences.set_style.assert_called_once_with('arcade')
        with mock.patch.object(live, 'PAGE_SECONDS', 1.5):  # even the dashboard's own time runs out at last
            answer, took = late(style, body, 2.5)
            self.assertIn(b' 408 ', answer)  # a late body is no display choice that could not be saved
            self.assertNotIn(b' 500 ', answer)
            self.assertLess(took, 2.4)  # answered as its time ran out, not when the body came
            answer, took = late(b'GET /display HTTP/1.1\r\n', host + b'\r\n', 2.5)
            self.assertIn(b' 408 ', answer)
            answer, took = dripped(lambda: socket.create_connection(('127.0.0.1', self.port), timeout=5), b'')
            self.assertEqual(answer, b'')  # a connection that sends nothing is closed with nothing said
            self.assertLess(took, 2.1)
        preferences.set_style.assert_called_once()  # only the one that came in time
        self.assertEqual(self.send()[0], 204)

    def test_a_display_choice_that_cannot_be_saved_is_said_so_without_a_traceback(self):
        path = temp_dir(self) / 'config.json'
        path.write_text(json.dumps({'accounts': [], 'display_style': 'pixel', 'from_a_newer_tokentv': 1}), encoding='utf-8')
        self.serve(live.handler(UsageStore([]), live.DisplayPreferences(path, {'accounts': []}), agents=self.m))
        said = io.StringIO()
        with mock.patch('sys.stderr', said):  # the config cannot be read back to save the choice into
            status, answer, _ = self.send(path='/display/style', body=b'{"style":"arcade"}')
        self.assertEqual(status, 500)
        self.assertIn(b'Could not save display choice', answer)
        self.assertEqual(said.getvalue(), '')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['display_style'], 'pixel')  # untouched

    def test_what_the_server_could_not_take_never_comes_back_in_its_answer(self):
        status, answer, _ = raw(self.port, b'FOO<b>X</b> /moment HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        self.assertEqual(status, 405)
        self.assertNotIn(b'<b>', answer)
        self.assertNotIn(b'FOO', answer)
        status, answer, _ = raw(self.port, b'POST /moment HTTP/9<script>\r\n\r\n')  # (answered as HTTP/0.9)
        self.assertNotIn(b'<script>', answer)
        self.assertIn(b'400', answer)
        status, answer, _ = raw(self.port, post_bytes(self.port, method='PUT'))
        self.assertEqual(status, 405)
        self.assertIsNone(self.m.wanted()[0])

    def test_twenty_at_once_cannot_wedge_it(self):
        results = []

        def one(body):
            results.append(raw(self.port, post_bytes(self.port, body=body))[0])
        threads = [threading.Thread(target=one, args=(b'{"moment":"claude.nope"}',)) for _ in range(10)]
        threads += [threading.Thread(target=one, args=(b'{"moment":"claude.end"}',)) for _ in range(10)]
        began = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual(sorted(results), [204] * 10 + [400] * 10)
        self.assertEqual(self.m.wanted()[0], ('done', 'claude'))  # one bow; the other nine fell in its minute

    def test_a_collection_replay_waits_for_no_agent_but_is_refused_while_one_needs_the_clock(self):
        class Locks:
            def collection(self):
                return {'found': [{'check': 'box-1'}]}
        prefs = mock.Mock()
        prefs.snapshot.return_value = {'status': 'ok', 'applied_style': 'arcade', 'style': 'arcade'}
        replays = []
        self.serve(live.handler(UsageStore([]), prefs, Locks(), replays, threading.Event(), agents=self.m))
        body = b'{"check":"box-1"}'
        self.m.note('claude.ask')
        status, answer, _ = raw(self.port, post_bytes(self.port, body=body, path='/collection/replay'))
        self.assertEqual(status, 409)
        self.assertIn(b'Claude Code is waiting for you', answer)
        self.m.note('claude.answered')
        self.m.note('claude.end')
        self.assertEqual(raw(self.port, post_bytes(self.port, body=body, path='/collection/replay'))[0], 409)
        self.assertEqual(replays, [])
        self.m.drop_bow()
        self.assertEqual(raw(self.port, post_bytes(self.port, body=body, path='/collection/replay'))[0], 200)
        self.assertEqual(replays, ['box-1'])

    def test_the_dashboards_other_paths_still_answer(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET', '/display')
        self.assertEqual(conn.getresponse().status, 200)


def receiver(test, answer=b'HTTP/1.0 204 No Content\r\n\r\n', hold=0):
    """(port, requests): a loopback TCP server recording each whole request it gets, answering `answer` after
    `hold` seconds."""
    got = []
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)
    test.addCleanup(listener.close)

    def one(conn):
        with conn:
            conn.settimeout(3)
            data = b''
            try:
                while b'\r\n\r\n' not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                head = data.split(b'\r\n\r\n', 1)[0].lower()
                length = int(head.split(b'content-length:', 1)[1].split(b'\r\n', 1)[0]) if b'content-length:' in head else 0
                while len(data.split(b'\r\n\r\n', 1)[-1]) < length:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except (OSError, ValueError):
                pass
            got.append(data)
            time.sleep(hold)
            try:
                conn.sendall(answer)
            except OSError:
                pass

    def run():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            threading.Thread(target=one, args=(conn,), daemon=True).start()
    threading.Thread(target=run, daemon=True).start()
    return listener.getsockname()[1], got


class SocketTests(unittest.TestCase):
    """The same endpoint on TokenTV's own socket (Linux and macOS), and the sender Codex's notify uses."""
    def setUp(self):
        self.dir = temp_dir(self)
        self.m = Moments({'claude', 'codex'})

    def receiver(self, answer=b'HTTP/1.0 204 No Content\r\n\r\n', hold=0):
        """A loopback TCP server that records each request it is sent, and answers `answer` after `hold` seconds."""
        return receiver(self, answer, hold)

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX') and os.name != 'nt', 'a Unix socket')
    def test_a_moment_over_tokentvs_own_socket(self):
        state = self.dir / 'state'
        state.mkdir()
        path = state / 'live.sock'
        server = live.MomentSocket(str(path), live.handler(UsageStore([]), agents=self.m, moments_only=True))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port, got = self.receiver()  # the TCP address in live.url: never used while the socket is there
        (state / 'live.url').write_text(f'http://127.0.0.1:{port}', encoding='utf-8')
        self.assertTrue(moments.post(state, 'claude.end'))
        self.assertEqual((self.m.wanted()[0], got), (('done', 'claude'), []))
        conn = socket.socket(socket.AF_UNIX)
        conn.connect(str(path))
        conn.sendall(b'GET /snapshot HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
        self.assertIn(b' 404 ', conn.recv(4096))  # the socket serves moments, nothing else
        conn.close()
        conn = socket.socket(socket.AF_UNIX)
        conn.connect(str(path))
        conn.sendall(b'GET /moment HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
        answer = conn.recv(4096)
        self.assertIn(b' 405 ', answer)  # no moment, as on the port
        self.assertIn(b'allow: post', answer.lower())
        self.assertNotIn(b'tokentv', answer.lower())
        conn.close()
        stalled = socket.socket(socket.AF_UNIX)
        stalled.connect(str(path))
        stalled.sendall(b'POST /moment HTTP/1.1\r\nHost: 127.0.0.1')  # and stops in its headers
        stalled.settimeout(5)
        began = time.monotonic()
        try:
            while stalled.recv(4096):
                pass
        except OSError:
            pass
        self.assertLess(time.monotonic() - began, 3)  # let go, not held
        stalled.close()

        def unix():
            conn = socket.socket(socket.AF_UNIX)
            conn.connect(str(path))
            return conn
        moment = b'POST /moment HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 23\r\n\r\n'
        for first, rest, every in ((b'', moment + b'{"moment":"claude.ask"}', .15), (moment, b'{"moment":"claude.ask"}', .6)):
            answer, took = dripped(unix, first, rest, every)  # a byte now and then, never in time
            self.assertLess(took, live.READ_SECONDS + .6)
            self.assertNotIn(b' 204 ', answer)
        self.assertEqual(self.m.wanted()[0], ('done', 'claude'))  # neither counted
        path.unlink()  # gone: TokenTV stopped, and an old address is no reason to send anywhere

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX') and os.name != 'nt', 'a Unix socket')
    def test_a_stale_socket_is_no_reason_to_try_the_port(self):
        state = self.dir / 'state'
        state.mkdir()
        dead = socket.socket(socket.AF_UNIX)
        dead.bind(str(state / 'live.sock'))  # left by a TokenTV that ended without its cleanup
        dead.close()
        port, got = self.receiver()
        (state / 'live.url').write_text(f'http://127.0.0.1:{port}', encoding='utf-8')
        self.assertFalse(moments.post(state, 'codex.end'))
        time.sleep(.1)
        self.assertEqual(got, [])

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX') and os.name != 'nt', 'a Unix socket')
    def test_without_tokentvs_socket_nothing_goes_to_the_port_in_live_url(self):
        state = self.dir / 'state'
        state.mkdir()
        port, got = self.receiver()  # a TokenTV that stopped left its address; another program may have the port now
        (state / 'live.url').write_text(f'http://127.0.0.1:{port}', encoding='utf-8')
        self.assertFalse(moments.post(state, 'codex.end'))
        time.sleep(.1)
        self.assertEqual(got, [])

    @mock.patch.object(moments, 'WINDOWS', True)  # the port, as on Windows: http.client follows no redirect, no proxy
    def test_the_sender_goes_only_to_this_computers_address_and_never_follows_or_proxies(self):
        state = self.dir / 'state'
        state.mkdir()
        elsewhere, followed = self.receiver()  # where the redirect points, on this computer: a follow would land here
        port, got = self.receiver(answer=f'HTTP/1.0 307 Temporary Redirect\r\nLocation: http://127.0.0.1:{elsewhere}/stolen'
                                         f'\r\n\r\n'.encode())
        sink, caught = self.receiver()
        with mock.patch.dict(os.environ, {'HTTP_PROXY': f'http://127.0.0.1:{sink}', 'http_proxy': f'http://127.0.0.1:{sink}',
                                          'ALL_PROXY': f'http://127.0.0.1:{sink}', 'NO_PROXY': ''}):
            for bad in ('http://example.com:80', 'http://192.0.2.7:8787', f'http://user@127.0.0.1:{port}',
                        f'http://127.0.0.1@localhost.evil.example:{port}', f'http://localhost.evil.example:{port}',
                        f'https://127.0.0.1:{port}', f'http://127.0.0.1:{port}/x', 'http://127.0.0.1:0', ''):
                (state / 'live.url').write_text(bad, encoding='utf-8')
                self.assertFalse(moments.post(state, 'codex.end'), bad)
            (state / 'live.url').write_text(f'http://localhost:{port}\n', encoding='utf-8')  # as TokenTV writes it
            self.assertFalse(moments.post(state, 'codex.end'))  # a redirect is no answer, and is not followed
        time.sleep(.1)
        self.assertEqual(len(got), 1)
        self.assertEqual(followed, [])  # no redirect followed
        self.assertEqual(caught, [])  # no proxy
        head, body = got[0].split(b'\r\n\r\n', 1)
        self.assertEqual(body, b'{"moment": "codex.end"}')
        self.assertIn(f'Host: 127.0.0.1:{port}'.encode(), head)
        self.assertTrue(head.startswith(b'POST /moment HTTP/1.1'))

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX') and os.name != 'nt', 'a Unix socket')
    def test_the_sender_follows_no_redirect_from_the_socket_either(self):
        state = self.dir / 'state'
        state.mkdir()
        elsewhere, followed = self.receiver()  # where the redirect points, on this computer: a follow would land here
        listener = listen_as_tokentv(self, state)  # on TokenTV's socket, something that redirects

        def redirect():
            conn, _ = listener.accept()
            with conn:
                conn.recv(65536)
                conn.sendall(f'HTTP/1.0 307 Temporary Redirect\r\nLocation: http://127.0.0.1:{elsewhere}/stolen\r\n\r\n'
                             .encode())
        threading.Thread(target=redirect, daemon=True).start()
        (state / 'live.url').write_text('http://127.0.0.1:8787', encoding='utf-8')
        self.assertFalse(moments.post(state, 'codex.end'))  # a redirect is no answer
        time.sleep(.1)
        self.assertEqual(followed, [])

    @mock.patch.object(moments, 'WINDOWS', True)
    def test_the_sender_gives_up_quickly_on_a_tokentv_that_does_not_answer(self):
        state = self.dir / 'state'
        state.mkdir()
        port, got = self.receiver(hold=5)
        (state / 'live.url').write_text(f'http://127.0.0.1:{port}', encoding='utf-8')
        began = time.monotonic()
        self.assertFalse(moments.post(state, 'codex.end', timeout=.8))
        self.assertLess(time.monotonic() - began, 1.5)
        self.assertFalse(moments.post(self.dir / 'nowhere', 'codex.end'))  # no TokenTV at all

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX') and os.name != 'nt', 'a Unix socket')
    def test_the_sender_gives_up_quickly_on_a_socket_that_does_not_answer(self):
        state = self.dir / 'state'
        state.mkdir()
        hang = socket.socket(socket.AF_UNIX)
        hang.bind(str(state / 'live.sock'))
        hang.listen(1)  # takes the connection, never answers
        self.addCleanup(hang.close)
        (state / 'live.url').write_text('http://127.0.0.1:8787', encoding='utf-8')
        began = time.monotonic()
        self.assertFalse(moments.post(state, 'codex.end', timeout=.8))
        self.assertLess(time.monotonic() - began, 1.5)


def tokentv_at(test, state, agents):
    """The moment endpoint for the state folder `state`, as a running TokenTV has it: its port in live.url and, on
    Linux and macOS, its own socket (live.sock)."""
    server = live.QuietServer(('127.0.0.1', 0), live.handler(UsageStore([]), agents=agents))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    (state / 'live.url').write_text(f'http://127.0.0.1:{server.server_port}', encoding='utf-8')
    if not moments.WINDOWS:
        unix = live.MomentSocket(str(state / 'live.sock'), live.handler(UsageStore([]), agents=agents, moments_only=True))
        threading.Thread(target=unix.serve_forever, daemon=True).start()
        test.addCleanup(unix.server_close)
        test.addCleanup(unix.shutdown)
    return server.server_port


def listen_as_tokentv(test, state):
    """A bare listener where TokenTV would be for `state` (its socket, or on Windows its port), taking connections."""
    if moments.WINDOWS:
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        (state / 'live.url').write_text(f'http://127.0.0.1:{listener.getsockname()[1]}', encoding='utf-8')
    else:
        (state / 'live.sock').unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(state / 'live.sock'))
    listener.listen(4)
    test.addCleanup(listener.close)
    return listener


class NotifyTests(unittest.TestCase):
    """`token-tv notify` as Codex runs it: a process, one JSON argument."""
    def setUp(self):
        self.dir = temp_dir(self)
        self.home = self.dir / 'h'  # short: a socket's path has a length limit (about 104 bytes on macOS)
        self.state = self.home / '.config' / 'token-tv' / 'state'
        self.state.mkdir(parents=True)
        self.m = Moments({'codex'})
        tokentv_at(self, self.state, self.m)

    def notify(self, *args, env=None):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('TOKEN_TV')}
        environment.update({'HOME': str(self.home), 'USERPROFILE': str(self.home),  # Windows reads USERPROFILE
                            'XDG_CONFIG_HOME': '', 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}, **(env or {}))
        began = time.monotonic()
        done = subprocess.run([sys.executable, '-m', 'token_tv', 'notify', *args], capture_output=True, env=environment,
                              cwd=str(self.dir), timeout=10)
        return done, time.monotonic() - began

    def files(self):
        return sorted((str(p), p.stat().st_mtime_ns) for p in self.dir.rglob('*') if p.is_file())

    def test_a_finished_turn_bows_and_nothing_of_it_is_printed_or_kept(self):
        before = self.files()
        event = {'type': 'agent-turn-complete', 'thread-id': 'CANARY-THREAD 9f', 'turn-id': 'CANARY-TURN 1',
                 'cwd': '/home/u/CANARY-PATH', 'input-messages': ['CANARY-PROMPT "quoted"\nnew line $(touch pwned) `id`'],
                 'last-assistant-message': 'CANARY-OUTPUT 한국어 ✓'}
        done, took = self.notify(json.dumps(event, ensure_ascii=False))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b'', b''))
        self.assertLess(took, 2)
        self.assertEqual(self.m.wanted()[0], ('done', 'codex'))
        self.assertEqual(self.files(), before)  # nothing written, the shell-looking text ran nothing
        self.assertFalse((self.dir / 'pwned').exists())

    def test_only_the_name_goes_out(self):
        got = []
        listener = listen_as_tokentv(self, self.state)

        def accept():
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(3)
                data = b''
                while not data.endswith(b'}'):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                got.append(data)
                conn.sendall(b'HTTP/1.0 204 No Content\r\n\r\n')
        threading.Thread(target=accept, daemon=True).start()
        done, _ = self.notify(json.dumps({'type': 'agent-turn-complete', 'turn-id': 'CANARY-77', 'cwd': '/CANARY-PATH'}))
        self.assertEqual(done.returncode, 0)
        time.sleep(.1)
        self.assertEqual(len(got), 1)
        self.assertNotIn(b'CANARY', got[0])
        self.assertTrue(got[0].endswith(b'\r\n\r\n{"moment": "codex.end"}'))

    def test_other_events_and_broken_arguments_do_nothing_quickly(self):
        for args in ([json.dumps({'type': 'approval-requested'})], [json.dumps({'thread-id': 'x'})], ['"agent-turn-complete"'],
                     ['42'], ['-1'], ['{not json'], [], ['--weird'], ['[{"type": "agent-turn-complete"}]'],
                     [json.dumps({'type': 'Agent-Turn-Complete'})]):
            done, took = self.notify(*args)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b'', b''), args)
            self.assertLess(took, 2)
        self.assertIsNone(self.m.wanted()[0])
        done, _ = self.notify(json.dumps({'type': 'agent-turn-complete'}))  # the control
        self.assertEqual(self.m.wanted()[0], ('done', 'codex'))

    def test_no_tokentv_or_one_that_hangs_still_ends_within_two_seconds(self):
        url = (self.state / 'live.url').read_text(encoding='utf-8')
        (self.state / 'live.url').unlink()
        done, took = self.notify(json.dumps({'type': 'agent-turn-complete'}))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b'', b''))
        self.assertLess(took, 2)
        (self.state / 'live.url').write_text(url, encoding='utf-8')
        listen_as_tokentv(self, self.state)  # accepts, never answers
        done, took = self.notify(json.dumps({'type': 'agent-turn-complete'}))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b'', b''))
        self.assertLess(took, 2)

    def test_another_config_is_found_by_flag_or_by_environment(self):
        other = self.dir / 'o'
        (other / 'state').mkdir(parents=True)
        (self.state / 'live.url').unlink()
        tokentv_at(self, other / 'state', self.m)
        self.notify('--config', str(other / 'config.json'), json.dumps({'type': 'agent-turn-complete'}))
        self.assertEqual(self.m.wanted()[0], ('done', 'codex'))
        self.m.drop_bow()
        self.notify(json.dumps({'type': 'agent-turn-complete'}), env={'TOKEN_TV_CONFIG': str(other / 'config.json')})
        self.assertEqual(self.m.wanted()[0], ('done', 'codex'))


class StopTests(unittest.TestCase):
    """TokenTV stopping: its address (live.url) and its socket (live.sock) go with it, so no agent goes on telling a
    port another program may hold next."""
    def test_a_tokentv_that_stops_takes_its_address_and_socket_away(self):
        rig = Rig(self)
        self.assertTrue((rig.state / 'live.url').exists())
        self.assertEqual((rig.state / 'live.sock').exists(), not moments.WINDOWS)
        rig.stop()
        self.assertFalse((rig.state / 'live.url').exists())
        self.assertFalse((rig.state / 'live.sock').exists())

    @unittest.skipIf(os.name == 'nt', 'Windows ends a process outright: no program cleans up after that')
    def test_asked_to_stop_as_systemd_and_launchd_ask_it_cleans_up_the_same(self):
        folder = temp_dir(self)
        home, state = folder / 'h', folder / 's'
        home.mkdir()
        readings = {'claude_a': {'alias': 'CLAUDE', 'provider': 'claude', 'status': 'ok', 'fetched_at': time.time(),
                                 'windows': [{'label': 'WEEK', 'used_percent': 30, 'resets_at': time.time() + 86400}]}}
        (folder / 'readings.json').write_text(json.dumps({'accounts': readings}), encoding='utf-8')
        config = {'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE', 'provider': 'claude', 'email': 'c@example.com',
                                'snapshot_file': str(folder / 'readings.json')}], 'update_check': False}
        (folder / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        environment = {key: value for key, value in os.environ.items() if not key.startswith('TOKEN_TV')}
        # another HOME hides a per-user site-packages (Pillow): the child gets this process's import path
        environment.update({'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
                            'PYTHONPATH': os.pathsep.join([str(ROOT), *(p for p in sys.path if p)]),
                            'PYTHONDONTWRITEBYTECODE': '1'})
        out_path, err_path = folder / 'out.txt', folder / 'err.txt'
        # Started for sure once it says it listens (its stop handler is in place by then), however loaded the
        # machine; a free port another test took meanwhile is tried again with a new one.
        for attempt in range(3):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            with open(out_path, 'wb') as out, open(err_path, 'wb') as err:
                tokentv = subprocess.Popen([sys.executable, '-m', 'token_tv.live', '--config', str(folder / 'config.json'),
                                            '--state-dir', str(state), '--port', str(port)], env=environment,
                                           cwd=str(folder), stdout=out, stderr=err)
            self.addCleanup(lambda child=tokentv: child.poll() is None and (child.kill(), child.wait()))
            began = time.monotonic()
            while b'TokenTV live listening' not in out_path.read_bytes() and tokentv.poll() is None:
                self.assertLess(time.monotonic() - began, 60, err_path.read_bytes())
                time.sleep(.05)
            if tokentv.poll() is None:
                break
            self.assertIn(b'is in use', err_path.read_bytes())  # anything else is a real failure
        self.assertIsNone(tokentv.poll(), err_path.read_bytes())
        self.assertTrue((state / 'live.url').exists())
        self.assertTrue((state / 'live.sock').exists())
        status, answer, _ = raw(port, b'GET /moment HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n', timeout=15)
        self.assertEqual(status, 405)  # TokenTV, listening
        self.assertIn(b'allow: post', answer.lower())
        tokentv.send_signal(signal.SIGTERM)
        tokentv.wait(timeout=60)
        err = err_path.read_bytes()
        self.assertEqual(tokentv.returncode, 0, err)
        self.assertNotIn(b'Traceback', err)
        self.assertFalse((state / 'live.url').exists())
        self.assertFalse((state / 'live.sock').exists())


class FrozenTime:
    """The time module as the drawings see it: one fixed instant, so the same picture is the same bytes."""
    def __init__(self, at):
        self.at = at

    def time(self):
        return self.at

    def __getattr__(self, name):
        return getattr(time, name)


class SyntheticTime:
    """The time module with its wall clock (and, for the store, its monotonic one) moving with a FakeClock, from
    `wall` when the clock read `start`: readings, the store's pace of fetching and the break's hour on the test's
    clock."""
    def __init__(self, clock, wall, monotonic=False):
        self.clock, self.wall, self.start, self.fake_monotonic = clock, wall, clock.now(), monotonic

    def time(self):
        return self.wall + (self.clock.now() - self.start)

    def monotonic(self):
        return self.clock.now() if self.fake_monotonic else time.monotonic()

    def __getattr__(self, name):
        return getattr(time, name)


class Rig:
    """TokenTV itself (live.main) on a fake clock (moments.CLOCK) driving a fake SD_PRO, with fixed readings and
    pictures drawn at one fixed instant. Uploads and toggles are logged at the fake time they reach the clock.

    With `wall`, the wall clock moves with the fake one (TokenTV's, the store's and the readings' alike; the drawings
    keep their fixed instant) and the readings are the test's to change: `windows` {provider: [(label, used %,
    seconds to its reset)]}, then set() and write(). The first reading is taken as TokenTV starts (`t0`), the next
    every `poll` seconds. `delay`: every send takes that long on the clock; `late`: the first one only (its picture,
    and so its loop, goes on that much later); `switch_off`: turning a slot off takes that long (the animation holds
    meanwhile, as for every request)."""
    def __init__(self, test, providers=('claude',), state_dir=None, poll_seconds=None, frame_ms=None, wall=False,
                 windows=None, model='sdpro', delay=0, at=None, late=0, switch_off=0):
        self.test = test
        self.dir = temp_dir(test)
        own_tmp(test)  # the clock locks
        self.clock = FakeClock()
        self.model = model  # the fake clock: an SD_PRO (its album's toggles), or an Ultra (one file, uploaded over)
        self.frozen = FrozenTime(float(int(time.time() if at is None else at)))  # (whole seconds, as the readings)
        self.wall = SyntheticTime(self.clock, self.frozen.at) if wall else None
        timed = ((mock.patch.object(module, 'time', self.wall) for module in (live, moments, sources))
                 if wall else (mock.patch.object(live, 'time', self.frozen),))
        for patcher in (mock.patch.object(moments, 'CLOCK', self.clock),
                        *(mock.patch.object(module, 'time', self.frozen) for module in (arcade, readout, display)),
                        *timed,
                        *((mock.patch.object(state, 'time', SyntheticTime(self.clock, self.frozen.at, True)),) if wall else ()),
                        mock.patch.object(live.Lockbox, 'pick', return_value=None),  # no hidden one-offs meanwhile
                        mock.patch.object(arcade, 'BOW_STYLE', 'low')):  # one bow, so picture() draws the one sent
            patcher.start()
            test.addCleanup(patcher.stop)
        self.calls, self.log = [], []
        if model == 'ultra':
            self.album = {'theme': 3, 'autoplay': 0, 'i_i': 0, 'parts': [], 'files': {}}
            fake = ultra_clock(self.album, self.calls)
        else:
            self.album = {'files': {}, 'enabled': set(), 'total': 3_000_000, 'base': 0}
            fake = sd_pro_clock(self.album, self.calls)
        clock, log, state_of = self.clock, self.log, self.album

        played = self.played = []  # (when, the bytes) of each picture as it was turned on
        first = [late] if late else []

        class Timed(fake):
            def do_GET(self):
                log.append((clock.now(), 'GET', self.path))
                if switch_off and self.path.startswith('/photo/toggle') and self.path.endswith('state=0'):
                    clock.bump(switch_off)  # (taken before the answer goes back)
                super().do_GET()
                if self.path.startswith('/photo/toggle') and self.path.endswith('state=1'):
                    name = parse_qs(urlparse(self.path).query)['name'][0]
                    if name.startswith('tokentv'):
                        played.append((clock.now(), state_of['files'].get(name)))

            def do_POST(self):
                log.append((clock.now(), 'POST', self.path))
                took = delay + (first.pop() if first else 0)
                if took:  # a send that takes this long on the clock (the animation holds meanwhile)
                    clock.bump(took)
                super().do_POST()
        self.delay = delay
        self.device = serve(Timed)
        self.url = self.device.__enter__()
        test.addCleanup(self.device.__exit__, None, None, None)
        self.readings, accounts = {}, []
        now = self.wall.time() if wall else time.time()
        for k, provider in enumerate(providers):
            key, alias = f'{provider}_a', provider.upper()
            shown = (windows or {}).get(provider) or [('WEEK', 30 + 10 * k, 3 * 86400)]
            self.readings[key] = {'alias': alias, 'provider': provider, 'status': 'ok', 'fetched_at': now,
                                  'windows': [{'label': label, 'used_percent': used, 'resets_at': now + left}
                                              for label, used, left in shown]}
            accounts.append({'key': key, 'alias': alias, 'provider': provider, 'email': f'{provider}@example.com',
                             'snapshot_file': str(self.dir / 'readings.json')})
        self.write(now)
        self.config = {'accounts': accounts, 'device_url': self.url, 'display_style': 'arcade', 'update_check': False}
        self.poll = poll_seconds or 60
        if poll_seconds:
            self.config['poll_seconds'] = poll_seconds
        self.frame = FRAME_SD if frame_ms is None else frame_ms / 1000  # the fake SD_PRO's pace, set in the config too
        if frame_ms is not None:
            self.config['device_frame_ms'] = frame_ms
        (self.dir / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        self.state = state_dir or self.dir / 'state'
        self.start()

    def start(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        ready = threading.Event()
        box = {}
        argv = ['--config', str(self.dir / 'config.json'), '--state-dir', str(self.state), '--port', str(self.port)]
        self.thread = threading.Thread(target=live.main, args=(argv, lambda server: (box.update(server=server), ready.set())),
                                       daemon=True)
        self.t0 = self.clock.now()  # TokenTV's first reading is taken as it starts
        self.thread.start()
        self.test.assertTrue(ready.wait(10))
        self.server = box['server']
        self.test.addCleanup(self.stop)
        self.clock.settle()

    def stop(self):
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(5)

    def now(self):
        """The wall clock as TokenTV, the store and the readings see it."""
        return self.wall.time() if self.wall else time.time()

    def set(self, key, label, used):
        """Change one window's used % in the readings (write() puts them where TokenTV reads them)."""
        for window in self.readings[key]['windows']:
            if window['label'] == label:
                window['used_percent'] = used

    def write(self, at=None):
        """The readings as measured at `at` (default: now), where TokenTV reads them at its next poll."""
        for row in self.readings.values():
            row['fetched_at'] = self.now() if at is None else at
        (self.dir / 'readings.json').write_text(json.dumps({'accounts': self.readings}), encoding='utf-8')

    def poll_at(self, n):
        """When TokenTV takes its `n`-th reading after the first (taken as it started, at t0)."""
        return self.t0 + n * self.poll

    def say(self, name):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('POST', '/moment', json.dumps({'moment': name}), {'Content-Type': 'application/json'})
        status = conn.getresponse().status
        self.test.assertEqual(status, 204)
        self.clock.settle()

    def uploads(self, since=None):
        sent = '/doUpload?dir=/image/' if self.model == 'ultra' else '/photo/upload'
        return [t for t, method, path in self.log if method == 'POST' and path == sent and (since is None or t >= since)]

    def switches(self, since=None):
        """When a picture was turned on (an activation), each of them since `since`."""
        return [t for t, method, path in self.log if path.startswith('/photo/toggle') and path.endswith('state=1')
                and (since is None or t >= since)]

    def requests(self, since):
        return [(t, method, path) for t, method, path in self.log if t >= since]

    def showing(self):
        """(the bytes the clock shows, when that picture went on: the time of the toggle that turned it on; on an
        Ultra, its one file as last sent, and when that send ended)."""
        if self.model == 'ultra':
            return self.album['files']['tokentv.gif'], self.uploads()[-1] + self.delay
        on = [name for name in self.album['enabled'] if name.startswith('tokentv')]
        self.test.assertEqual(len(on), 1)
        started = max(t for t, method, path in self.log if path.startswith('/photo/toggle') and f'name={on[0]}' in path
                      and path.endswith('state=1'))
        return self.album['files'][on[0]], started

    def loop(self, image):
        """How long this fake clock plays one loop of `image`: an SD_PRO each picture for its delay but at least
        `frame`; an Ultra as long as the delays say."""
        return gif_seconds(image) if self.model == 'ultra' else physical(image, self.frame)

    def end_of_loop(self, at=None):
        """When the loop the clock plays at `at` (default: now) ends, from its picture's own start and frames."""
        image, started = self.showing()
        return loop_end({'at': started, 'loop': self.loop(image)}, self.clock.now() if at is None else at)

    def picture(self, what=None, level=None, egg=None, reading=True, snapshot=None):
        """The picture TokenTV should send for `what` (or the one-off `egg`), drawn here independently from the same
        readings (or, with `reading` False, from none yet: every account still loading), or from `snapshot` (the
        readings as TokenTV holds them, held(): who is at work comes from their history)."""
        if snapshot is None:
            store = UsageStore(self.config['accounts'], min_fetch_seconds=MIN_FETCH_SECONDS)
            if reading:
                store.refresh()
            snapshot = store.snapshot()
        mark = None if what is None else ({'kind': 'needs', 'since': 0, 'level': what[1]} if what[0] == 'needs'
                                          else {'kind': 'done', 'at': 0} if what[0] == 'done' else {'kind': what[1]})
        return render_page(overlay(snapshot, what, mark), 0, 'arcade', egg=egg)

    def held(self):
        """The readings as TokenTV holds them now: its dashboard's /snapshot."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', '/snapshot')
        return json.loads(conn.getresponse().read())


class ClockTimingTests(unittest.TestCase):
    """When each moment reaches the clock: at the end of the loop it is playing, one upload per change, none for
    the same again; a wait grows more insistent and is let go on time with nothing else happening."""
    def assertAt(self, rig, when, what, since):
        """One more upload at the loop's end `when` (within 250 ms), and the clock shows `what` since then."""
        image, started = rig.showing()
        self.assertEqual(image, rig.picture(what))
        self.assertGreaterEqual(started, when - 1e-6)  # (TokenTV sums the loop its own way, to the last bit)
        self.assertLess(started, when + .25)
        self.assertLessEqual(len(rig.uploads(since)), 1)  # a picture the clock still holds needs only switching on
        return started, physical(image)

    def test_a_wait_comes_at_the_loops_end_then_hops_holds_a_sign_and_is_let_go(self):
        rig = Rig(self)
        normal, start = rig.showing()
        self.assertEqual(normal, rig.picture())
        loop = physical(normal)
        rig.clock.advance(loop / 4)
        asked = rig.clock.now()
        rig.say('claude.ask')
        rig.clock.to(start + loop - .001)
        self.assertEqual(rig.requests(asked), [])  # nothing interrupts the loop that is playing
        rig.clock.to(start + loop + .3)
        start, loop = self.assertAt(rig, start + loop, ('needs', 1), asked)
        mark = rig.clock.now()
        rig.say('claude.ask')  # another session waits too: the same picture, nothing sent
        rig.clock.to(asked + 299.999)  # through the minute's reading of the usage: still nothing sent
        self.assertEqual(rig.requests(mark), [])
        for threshold, level in ((300, 2), (900, 3)):
            due = loop_end({'at': start, 'loop': loop}, asked + threshold)
            rig.clock.to(due + .3)
            start, loop = self.assertAt(rig, due, ('needs', level), asked + threshold - 1)
            rig.clock.advance(3 * loop)
            self.assertEqual(rig.uploads(start + .01), [])  # the same state loops on with no request
        rig.say('claude.answered')  # one of the two answered: still waiting
        rig.clock.to(asked + 1799.999)
        self.assertEqual(rig.showing()[0], rig.picture(('needs', 3)))
        due = loop_end({'at': start, 'loop': loop}, asked + 1800)
        rig.clock.to(due + .3)
        self.assertAt(rig, due, None, asked + 1799)  # thirty minutes after the wait began, the other's with it, no bow
        self.assertLessEqual(len(rig.uploads(asked)), 4)  # hand, hops, sign, the usual face: no more
        rig.clock.advance(120)
        image, _ = rig.showing()
        self.assertEqual(image, rig.picture())

    def test_an_answer_clears_the_wait_and_its_old_deadlines_do_nothing_later(self):
        rig = Rig(self)
        _, start = rig.showing()
        rig.clock.advance(1)
        asked = rig.clock.now()
        rig.say('claude.ask')
        rig.clock.advance(320)  # through the hop
        _, start = rig.showing()
        rig.say('claude.answered')
        answered = rig.clock.now()
        loop = physical(rig.showing()[0])
        due = loop_end({'at': start, 'loop': loop}, answered)
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, None, answered)
        rig.clock.to(asked + 1900)  # past the old sign and let-go times
        self.assertEqual(rig.uploads(start + .01), [])

    def test_a_turns_end_bows_for_one_loop_and_bows_at_most_once_a_minute(self):
        rig = Rig(self)
        _, start = rig.showing()
        loop = physical(rig.showing()[0])
        rig.clock.advance(loop / 2)
        ended = rig.clock.now()
        rig.say('claude.end')
        rig.clock.to(start + loop + .3)
        bowed, bow_loop = self.assertAt(rig, start + loop, ('done', 'claude'), ended)
        rig.clock.advance(1)
        rig.say('claude.end')  # inside the minute: dropped
        rig.clock.to(bowed + bow_loop + .3)
        image, back = rig.showing()
        self.assertEqual(image, rig.picture())  # one loop of the bow, then the usual face, no second bow
        self.assertGreaterEqual(back, bowed + bow_loop)
        self.assertLess(back, bowed + bow_loop + .25)
        self.assertLessEqual(len(rig.uploads(ended)), 2)
        rig.say('codex.end')  # no Codex here: nothing, and no minute used up
        rig.clock.to(bowed + 59.9)
        rig.say('claude.end')
        rig.clock.advance(10)
        self.assertEqual(rig.showing()[0], rig.picture())
        rig.clock.to(bowed + 60.5)
        rig.say('claude.end')  # a fresh one after the minute bows again, at the next loop's end
        rig.clock.to(rig.end_of_loop() + .1)
        self.assertEqual(rig.showing()[0], rig.picture(('done', 'claude')))

    def test_codex_bows_as_itself(self):
        rig = Rig(self, providers=('claude', 'codex'))
        _, start = rig.showing()
        loop = physical(rig.showing()[0])
        rig.clock.advance(1)
        ended = rig.clock.now()
        rig.say('codex.end')
        rig.clock.to(start + loop + .3)
        bowed, bow_loop = self.assertAt(rig, start + loop, ('done', 'codex'), ended)
        self.assertNotEqual(rig.picture(('done', 'codex')), rig.picture(('done', 'claude')))
        rig.clock.to(bowed + bow_loop + .3)
        self.assertEqual(rig.showing()[0], rig.picture())

    def test_a_wait_that_comes_during_a_bow_follows_it_and_a_waits_bow_is_dropped(self):
        rig = Rig(self, providers=('claude', 'codex'))
        _, start = rig.showing()
        loop = physical(rig.showing()[0])
        rig.say('codex.end')
        rig.clock.to(start + loop + .3)
        bowed, bow_loop = rig.showing()[1], physical(rig.showing()[0])
        rig.clock.advance(bow_loop / 2)
        asked = rig.clock.now()
        rig.say('claude.ask')
        rig.clock.to(bowed + bow_loop + .3)
        self.assertAt(rig, bowed + bow_loop, ('needs', 1), asked)  # at the bow's end, not before
        rig.clock.advance(70)
        rig.say('claude.end')  # another session's turn ends while this one waits
        rig.say('codex.end')
        rig.clock.advance(20)
        self.assertEqual(rig.showing()[0], rig.picture(('needs', 1)))
        mark = rig.clock.now()
        rig.say('claude.answered')
        rig.clock.advance(20)
        self.assertEqual(rig.showing()[0], rig.picture())  # no stale bow afterwards
        self.assertLessEqual(len(rig.uploads(mark)), 1)

    def test_states_superseded_before_the_loop_ends_never_show(self):
        rig = Rig(self)
        rig.clock.advance(.5)
        mark = rig.clock.now()
        rig.say('claude.ask')
        rig.say('claude.answered')
        rig.clock.to(rig.end_of_loop() + rig.end_of_loop() - mark)  # two loop ends later
        self.assertEqual(rig.requests(mark), [])  # asked and answered within one loop: nothing at all
        rig.clock.advance(.5)
        mark = rig.clock.now()
        due = rig.end_of_loop()
        for _ in range(3):
            rig.say('claude.ask')
            rig.say('claude.answered')
        rig.say('claude.ask')
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('needs', 1), mark)  # only the last state, once, at that loop's end
        rig.clock.advance(.5)
        mark = rig.clock.now()
        due = rig.end_of_loop()
        rig.say('claude.answered')
        rig.say('claude.end')  # the turn's end right after its answer: the bow, with no flash of the hand
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('done', 'claude'), mark)

    def test_a_change_due_while_a_new_reading_waits_for_the_loops_end_is_drawn_in(self):
        rig = Rig(self, providers=('claude', 'codex'))
        rig.clock.advance(1)
        asked = rig.clock.now()
        rig.say('claude.ask')
        rig.clock.to(asked + 290)
        readings = json.loads((rig.dir / 'readings.json').read_text(encoding='utf-8'))
        readings['accounts']['codex_a']['windows'][0]['used_percent'] = 35  # Codex's reading changes (down: no work)
        readings['accounts']['codex_a']['fetched_at'] = time.time()
        (rig.dir / 'readings.json').write_text(json.dumps(readings), encoding='utf-8')
        rig.clock.to(asked + 300)  # the minute's poll took the new reading and waits for the loop's end: hop now due
        due = rig.end_of_loop(asked + 300)
        rig.clock.to(due + .3)
        image, started = rig.showing()
        self.assertEqual(image, rig.picture(('needs', 2)))  # the hop, with the new reading, at that loop's end
        self.assertLess(started, due + .25)
        # one upload for the hop with the new reading; one more only if a loop ended between the poll and the hop
        self.assertLessEqual(len(rig.uploads(asked + 290)), 2)

    def test_a_slow_reading_holds_no_moment_back_and_is_drawn_once_it_is_in(self):
        gate, slow, began, tokentvs = threading.Event(), threading.Event(), [], []
        self.addCleanup(gate.set)
        read = live.UsageStore.refresh

        def refresh(store):  # TokenTV's providers answer only when the test says so (the test's own at once)
            tokentvs[:] = tokentvs or [store]  # the first store to read is TokenTV's, as it starts
            if slow.is_set() and store is tokentvs[0]:
                began.append(moments.CLOCK.now())
                moments.CLOCK.held.add(threading.current_thread())
                gate.wait(30)
            return read(store)
        patcher = mock.patch.object(live.UsageStore, 'refresh', refresh)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('claude', 'codex'))
        slow.set()
        rig.clock.advance(61)  # the minute's reading has begun, and does not come
        self.assertEqual(len(began), 1)
        rig.clock.advance(1)
        asked = rig.clock.now()
        rig.say('claude.ask')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('needs', 1), asked)  # on time, with the last reading
        due = loop_end({'at': start, 'loop': loop}, asked + 300)
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('needs', 2), asked + 299)  # the hop on time too
        answered = rig.clock.now()
        rig.say('claude.answered')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        self.assertAt(rig, due, None, answered)
        self.assertEqual(len(began), 1)  # no second reading piled up behind the first
        readings = json.loads((rig.dir / 'readings.json').read_text(encoding='utf-8'))
        readings['accounts']['codex_a']['windows'][0]['used_percent'] = 25  # a flower less (down: no work)
        readings['accounts']['codex_a']['fetched_at'] = time.time()
        (rig.dir / 'readings.json').write_text(json.dumps(readings), encoding='utf-8')
        before = rig.showing()[0]
        gate.set()  # the reading comes in at last
        for thread in threading.enumerate():
            if thread.name == 'TokenTV reading':
                thread.join(5)
        rig.clock.settle()
        rig.clock.to(rig.end_of_loop() + .3)
        image, _ = rig.showing()
        self.assertNotEqual(image, before)
        self.assertEqual(image, rig.picture())  # drawn once it is in, at the loop's end

    def test_a_reading_that_never_comes_from_the_start_holds_back_no_moment_nor_its_escalation(self):
        gate, began, tokentvs = threading.Event(), [], []
        self.addCleanup(gate.set)
        read = live.UsageStore.refresh

        def refresh(store):  # TokenTV's providers do not answer, from its very first reading (the test's own do)
            tokentvs[:] = tokentvs or [store]
            if store is tokentvs[0]:
                began.append(moments.CLOCK.now())
                moments.CLOCK.held.add(threading.current_thread())
                gate.wait(60)
            return read(store)
        patcher = mock.patch.object(live.UsageStore, 'refresh', refresh)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self)
        rig.clock.advance(10)
        self.assertEqual(rig.uploads(), [])  # no reading yet, nothing to show yet: the clock keeps what it had
        asked = rig.clock.now()
        rig.say('claude.ask')
        image, start = rig.showing()  # no loop of TokenTV's playing to wait for: at once, drawn from what it has
        self.assertEqual(image, rig.picture(('needs', 1), reading=False))
        self.assertLess(start - asked, .25)
        loop = physical(image)
        for threshold, level in ((300, 2), (900, 3)):
            due = loop_end({'at': start, 'loop': loop}, asked + threshold)
            rig.clock.to(due + .3)
            image, start = rig.showing()
            self.assertEqual(image, rig.picture(('needs', level), reading=False))
            self.assertGreaterEqual(start, due)  # at its loop's end, as ever
            self.assertLess(start, due + .25)
            loop = physical(image)
        answered = rig.clock.now()
        rig.say('claude.answered')
        due = loop_end({'at': start, 'loop': loop}, answered)
        rig.clock.to(due + .3)
        image, start = rig.showing()
        self.assertEqual(image, rig.picture(reading=False))
        self.assertLess(start, due + .25)
        self.assertEqual(len(began), 1)  # one reading out, however many minutes passed: none piled up behind it
        gate.set()  # the reading comes in at last: drawn at the next loop's end
        for thread in threading.enumerate():
            if thread.name == 'TokenTV reading':
                thread.join(5)
        rig.clock.settle()
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.showing()[0], rig.picture())

    def test_a_slow_reading_that_starts_as_a_hop_is_due_does_not_put_the_hop_off_a_loop(self):
        # The re-grade's m-slip: readings every 63 s and an ask at 15 s put the hop's time (315 s) on a reading's
        # tick and on a loop's end. The reading then takes long. Real time spent on the clock's path there (a wait
        # for the reading, the 40 ms a hop takes to draw) is put on the fake clock, as it passes for the real one.
        # (Clawd keeping still: its usual loop is 8 pictures held 420 and 630 ms, 4.2 s, so the raised hand goes on at
        # 16.8 s; its 50 pictures take a 142 ms tick each, 7.1 s, and 42 of those loops end at 315 s.)
        patcher = mock.patch.object(arcade, 'rest_step', lambda provider, now: (None, None))
        patcher.start()
        self.addCleanup(patcher.stop)
        gate, tokentvs = threading.Event(), []
        self.addCleanup(gate.set)
        read = live.UsageStore.refresh
        window = {}

        def refresh(store):
            tokentvs[:] = tokentvs or [store]
            if store is tokentvs[0] and window.get('from', float('inf')) <= moments.CLOCK.now():
                moments.CLOCK.held.add(threading.current_thread())
                gate.wait(30)
            return read(store)

        def scheduling():
            name = threading.current_thread().name
            return '(poll)' in name and window.get('from', float('inf')) <= moments.CLOCK.now() <= window['to']
        wait, draw = live.Wake.wait, live.render_page

        def timed_wait(self, timeout=None):
            began = time.monotonic()
            got = wait(self, timeout)
            if timeout is not None and scheduling():
                moments.CLOCK.bump(min(time.monotonic() - began, timeout))
            return got

        def timed_draw(*args, **kwargs):
            image = draw(*args, **kwargs)
            if scheduling():
                moments.CLOCK.bump(.04)
            return image
        for patcher in (mock.patch.object(live.UsageStore, 'refresh', refresh), mock.patch.object(live.Wake, 'wait', timed_wait),
                        mock.patch.object(live, 'render_page', timed_draw)):
            patcher.start()
            self.addCleanup(patcher.stop)
        rig = Rig(self, poll_seconds=63)
        _, first = rig.showing()
        rig.clock.to(first + 15)
        asked = rig.clock.now()
        rig.say('claude.ask')
        due = loop_end({'at': first, 'loop': physical(rig.showing()[0], rig.frame)}, asked)
        rig.clock.to(due + .3)
        _, start = rig.showing()
        hop = loop_end({'at': start, 'loop': physical(rig.showing()[0], rig.frame)}, asked + 300)
        self.assertAlmostEqual(hop - first, 5 * 63, places=6)  # the hop's loop end is a reading's tick
        window.update({'from': hop - 1, 'to': hop + 1})
        rig.clock.to(hop + 10)
        image, started = rig.showing()
        self.assertEqual(image, rig.picture(('needs', 2)))
        self.assertGreaterEqual(started, hop - 1e-6)  # (16.8 and 7.1 s are no exact binary numbers)
        self.assertLess(started, hop + .25)  # on time, not a loop later

    def test_a_moment_that_comes_during_a_one_off_goes_as_it_ends_in_its_quiet_loops_place(self):
        from PIL import Image
        from token_tv.lockbox import Box
        stage = lambda colour: Image.new('RGB', (120, 71), colour)  # noqa: E731
        boxes = [Box('Test', 'unique', 'claude_a', tuple(stage((200, 40, 40)) for _ in range(4)), 40,
                     after=(stage((40, 40, 200)),))]
        patcher = mock.patch.object(live.Lockbox, 'pick', side_effect=lambda snap: boxes.pop() if boxes else None)
        rig = Rig(self)
        patcher.start()
        self.addCleanup(patcher.stop)
        box = boxes[0]
        rig.clock.advance(60)  # the minute's reading opens the box: its event goes as the loop playing then ends
        self.assertEqual(boxes, [])
        rig.clock.to(rig.end_of_loop() + .001)
        event, opened = rig.showing()
        self.assertEqual(event, rig.picture(egg=box))  # and plays its loop, its quiet loop waiting for the end
        rig.clock.advance(physical(event) / 2)  # (a loop of a few pictures: as long as they take on the clock)
        asked = rig.clock.now()
        rig.say('claude.ask')  # while the one-off plays
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        self.assertAlmostEqual(due, opened + physical(event))
        self.assertAt(rig, due, ('needs', 1), asked)  # as the one-off ends, in its quiet loop's place
        rig.clock.advance(60)
        self.assertEqual(rig.showing()[0], rig.picture(('needs', 1)))
        self.assertEqual(len(rig.uploads(opened + .001)), 1)  # nothing else went to the clock after the event

    def test_a_moment_that_comes_and_goes_during_a_one_off_leaves_its_quiet_loop_in_place(self):
        import dataclasses
        from PIL import Image
        from token_tv.lockbox import Box
        stage = lambda colour: Image.new('RGB', (120, 71), colour)  # noqa: E731
        box = Box('Test', 'unique', 'claude_a', tuple(stage((200, 40, 40)) for _ in range(4)), 40,
                  after=(stage((40, 40, 200)),))
        boxes = [box]
        patcher = mock.patch.object(live.Lockbox, 'pick', side_effect=lambda snap: boxes.pop() if boxes else None)
        rig = Rig(self)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig.clock.advance(60)
        rig.clock.to(rig.end_of_loop() + .001)
        event, opened = rig.showing()
        rig.clock.advance(physical(event) / 4)
        rig.say('claude.ask')
        rig.clock.advance(physical(event) / 4)
        rig.say('claude.answered')  # answered (the row drawn running) well before the event's end
        rig.clock.to(opened + physical(event) + .3)
        quiet, started = rig.showing()
        self.assertEqual(quiet, rig.picture(egg=dataclasses.replace(box, frames=box.after, after=(), intro=False)))
        self.assertAlmostEqual(started, opened + physical(event))  # its quiet loop, as if nothing had come

    def test_a_one_off_plays_its_event_loop_whole_however_fast_its_quiet_loop_is_drawn(self):
        import dataclasses
        from PIL import Image
        from token_tv.lockbox import Box
        stage = lambda colour: Image.new('RGB', (120, 71), colour)  # noqa: E731
        box = Box('Test', 'unique', 'claude_a', tuple(stage((200, 40, 40)) for _ in range(4)), 40,
                  after=(stage((40, 40, 200)),))
        boxes = [box]
        patcher = mock.patch.object(live.Lockbox, 'pick', side_effect=lambda snap: boxes.pop() if boxes else None)
        rig = Rig(self)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig.clock.advance(60)  # (drawing takes no time on the fake clock: the quiet loop is ready at once)
        rig.clock.to(rig.end_of_loop() + .001)
        event, opened = rig.showing()
        self.assertEqual(event, rig.picture(egg=box))
        rig.clock.to(opened + physical(event) + .3)
        quiet, started = rig.showing()
        self.assertEqual(quiet, rig.picture(egg=dataclasses.replace(box, frames=box.after, after=(), intro=False)))
        self.assertAlmostEqual(started, opened + physical(event))  # as the event's loop ended, not before

    def one_off(self, seconds=40):
        """A rig whose minute's reading, half a loop into the usual face's loop, opens a box (the event, then its
        quiet loop for the rest of `seconds`)."""
        from PIL import Image
        from token_tv.lockbox import Box
        at = float(int(time.time()))
        learn = Rig(self, at=at)
        loop = physical(learn.showing()[0])
        learn.stop()
        stage = lambda colour: Image.new('RGB', (120, 71), colour)  # noqa: E731
        box = Box('Test', 'unique', 'claude_a', tuple(stage((200, 40, 40)) for _ in range(4)), seconds,
                  after=(stage((40, 40, 200)),))
        boxes = [box]
        patcher = mock.patch.object(live.Lockbox, 'pick', side_effect=lambda snap: boxes.pop() if boxes else None)
        rig = Rig(self, at=at, late=(60 - loop / 2) % loop)
        patcher.start()
        self.addCleanup(patcher.stop)
        return rig, box, boxes

    def test_a_one_offs_event_waits_for_the_end_of_the_loop_playing_as_it_came(self):
        rig, box, boxes = self.one_off()
        normal, start = rig.showing()
        loop = physical(normal)
        read = rig.poll_at(1)
        due = loop_end({'at': start, 'loop': loop}, read)
        self.assertGreater(due - read, .2)  # (it comes well inside a loop)
        rig.clock.to(due - .001)
        self.assertEqual(boxes, [])  # opened by the reading,
        self.assertEqual(rig.switches(read), [])  # and the loop that was playing not cut
        rig.clock.to(due + .3)
        event, opened = rig.showing()
        self.assertEqual(event, rig.picture(egg=box))
        self.assertGreaterEqual(opened, due - 1e-6)
        self.assertLess(opened, due + .25)
        self.assertEqual(len(rig.uploads(read)), 1)

    def full_reading(self):
        """A rig of one Codex account at 90 %, whose minute's reading, half a loop into the usual face's loop, says
        100 % (a 'full' one-off); and what each picture TokenTV draws from then on was drawn with ({bytes: egg})."""
        at, window = float(int(time.time())), {'codex': [('5H', 90, 4 * 3600)]}
        learn = Rig(self, providers=('codex',), wall=True, windows=window, at=at)
        loop = physical(learn.showing()[0])
        learn.stop()
        rig = Rig(self, providers=('codex',), wall=True, windows=window, at=at, late=(60 - loop / 2) % loop)
        drawn, draw = {}, live.render_page

        def spy(snapshot, page=0, style='pixel', egg=None):
            image = draw(snapshot, page, style, egg=egg)
            drawn[image] = egg
            return image
        patcher = mock.patch.object(live, 'render_page', spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        rig.clock.to(rig.poll_at(1) - 1)
        rig.set('codex_a', '5H', 100)
        rig.write()
        return rig, drawn

    def test_a_reading_that_brings_a_one_off_sends_the_one_off_alone(self):
        rig, drawn = self.full_reading()
        normal, start = rig.showing()
        read = rig.poll_at(1)
        due = loop_end({'at': start, 'loop': physical(normal)}, read)
        rig.clock.to(due - .001)
        self.assertEqual(rig.requests(read), [])  # nothing cuts the loop that was playing
        rig.clock.to(due + .001)
        event, opened = rig.showing()
        self.assertEqual(drawn.get(event), 'full@codex_a')  # the one-off, with no picture of the reading before it
        self.assertEqual(len(rig.uploads(read)), 1)
        self.assertGreaterEqual(opened, due - 1e-6)
        rig.clock.to(opened + physical(event) + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture(snapshot=rig.held()))  # then the usual face, at 100 %, as its loop ends
        self.assertAlmostEqual(returned, opened + physical(event))
        self.assertEqual(len(rig.uploads(read)), 2)

    def test_a_moment_that_comes_while_an_event_waits_to_go_on_goes_first_and_the_event_after_it(self):
        rig, drawn = self.full_reading()
        normal, start = rig.showing()
        read = rig.poll_at(1)
        due = loop_end({'at': start, 'loop': physical(normal)}, read)
        rig.clock.to(read + .01)
        rig.say('codex.end')  # Codex's turn ends while the event waits for the loop's end: its bow first
        rig.clock.to(due + .3)
        bow, began = rig.showing()
        self.assertEqual(bow, rig.picture(('done', 'codex'), snapshot=rig.held()))
        self.assertGreaterEqual(began, due - 1e-6)
        self.assertLess(began, due + .25)
        rig.clock.to(began + physical(bow) + .3)
        self.assertEqual(rig.showing()[0], rig.picture(snapshot=rig.held()))  # one loop of it, the usual face
        self.assertNotIn('full@codex_a', [drawn.get(image) for _, image in rig.played])
        nxt = rig.poll_at(2)  # the next reading: no moment now, so the event's turn
        rig.clock.to(rig.end_of_loop(nxt) + .3)
        event, opened = rig.showing()
        self.assertEqual(drawn.get(event), 'full@codex_a')
        self.assertGreaterEqual(opened, nxt - 1e-6)
        self.assertEqual([drawn.get(image) for _, image in rig.played].count('full@codex_a'), 1)

    def test_a_moment_that_comes_while_a_one_off_waits_to_go_on_goes_instead(self):
        rig, box, boxes = self.one_off()
        normal, start = rig.showing()
        read = rig.poll_at(1)
        due = loop_end({'at': start, 'loop': physical(normal)}, read)
        rig.clock.to(read + .01)
        self.assertEqual((boxes, rig.switches(read)), ([], []))  # the box is waiting for the loop's end
        rig.say('claude.end')  # a turn's end, before it went on: the bow goes, the one-off does not start
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('done', 'claude'), read)
        rig.clock.advance(120)  # its loop, the usual face, two more readings: the one-off is not seen
        self.assertEqual(rig.showing()[0], rig.picture())
        self.assertNotIn(rig.picture(egg=box), [image for _, image in rig.played])

    @unittest.skipIf(os.name == 'nt', 'no socket on Windows')
    def test_tokentv_says_so_when_it_cannot_open_its_socket(self):
        said = io.StringIO()
        with mock.patch('sys.stdout', said):
            rig = Rig(self, state_dir=Path(temp_dir(self)) / ('x' * 120) / 'state')
            rig.say('claude.ask')  # over the port still, for this test
        self.assertIn("could not open its socket for Claude Code's and Codex's moments", said.getvalue())
        self.assertFalse((rig.state / 'live.sock').exists())

    def test_a_restart_forgets_the_moments(self):
        rig = Rig(self)
        rig.say('claude.ask')
        rig.clock.advance(10)
        self.assertEqual(rig.showing()[0], rig.picture(('needs', 1)))
        rig.stop()
        self.assertFalse((rig.state / 'live.url').exists())
        self.assertFalse((rig.state / 'live.sock').exists())
        rig.start()
        rig.clock.advance(30)
        self.assertEqual(rig.showing()[0], rig.picture())
        rig.say('claude.end')
        rig.clock.to(rig.end_of_loop() + .1)
        self.assertEqual(rig.showing()[0], rig.picture(('done', 'claude')))

    def test_moments_write_nothing_to_disk(self):
        rig = Rig(self)
        def files():
            # the running TokenTV's live.lock is unreadable on Windows while held: its time is enough
            return {p.name: (p.stat().st_mtime_ns, b'' if p.name == 'live.lock' else p.read_bytes())
                    for p in rig.state.iterdir() if p.is_file()}
        before = files()
        rig.say('claude.ask')
        rig.clock.advance(20)
        rig.say('claude.answered')
        rig.say('claude.end')
        rig.clock.advance(20)  # all inside the minute: no reading of the usage meanwhile
        self.assertGreaterEqual(len(rig.uploads()), 3)
        self.assertEqual(files(), before)
        rig.say('claude.ask')
        rig.clock.advance(60)  # now with the minute's reading, as without any moment
        for name, (_, data) in files().items():
            for word in (b'claude.ask', b'claude.end', b'NEEDS', b'"moment"', b'"needs"'):
                self.assertNotIn(word, data, name)
        self.assertEqual(files()['tokentv.gif'][1], rig.picture())  # the picture with the wait in it was not kept

    def test_preview_shows_the_moment_due(self):
        rig = Rig(self)
        rig.say('claude.ask')
        conn = http.client.HTTPConnection('127.0.0.1', rig.port, timeout=5)
        conn.request('GET', '/frame/0.jpg')
        self.assertEqual(conn.getresponse().read(), rig.picture(('needs', 1)))


if __name__ == '__main__':
    unittest.main()
