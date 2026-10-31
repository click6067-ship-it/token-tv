"""The battery readout (the owner's pick, 2026-10-31): the pet and what it is doing, a battery of what is left, and
the reset as a clock time; and the pace the clock plays Arcade at."""
import datetime
import sys
import time
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_tv import arcade, lockbox, readout  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402

from helpers import stepped_over  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def lit_cells(image, y, x0, x1, colour):
    """How many cells of a battery row hold `colour`, counted along the row's middle line."""
    runs, inside = 0, False
    for x in range(x0, x1):
        hit = image.getpixel((x, y)) == colour
        runs += hit and not inside
        inside = hit
    return runs


class ResetClockTests(unittest.TestCase):
    def test_a_reset_is_a_clock_time_never_a_countdown(self):
        now = time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1))
        self.assertEqual(readout.reset_clock(now + 2 * H + 30 * 60, now), '14:30')
        later = now + 3 * D
        self.assertEqual(readout.reset_clock(later, now), datetime.datetime.fromtimestamp(later).strftime('%a %H:%M').upper())
        self.assertEqual(readout.reset_clock(None, now), '--')


class BatteryDrawingTests(unittest.TestCase):
    def frame(self, rows, action='RUNNING', provider='claude'):
        image = Image.new('RGB', (240, 240), readout.PANEL)
        readout.draw_battery(image, ImageDraw.Draw(image), provider, action, rows, time.time())
        return image

    def test_one_window_fills_cells_for_what_is_left(self):
        image = self.frame([('WK', 63, time.time() + 3 * D, False)])  # 37 % left: three full cells and a part of one
        self.assertEqual(lit_cells(image, 205, 14, 164, readout.band(63)), 4)
        empty = self.frame([('WK', None, None, False)])
        self.assertEqual(lit_cells(empty, 205, 14, 164, readout.band(0)), 0)  # no reading: an empty battery, not 0 %

    def test_two_windows_give_two_slim_batteries(self):
        image = self.frame([('5H', 41, time.time() + 2 * H, False), ('WK', 63, time.time() + 3 * D, False)])
        self.assertGreater(lit_cells(image, 204, 28, 64, readout.band(41)), 0)
        self.assertGreater(lit_cells(image, 225, 28, 64, readout.band(63)), 0)

    def test_two_windows_keep_room_between_what_is_left_and_the_reset(self):
        far = time.time() + 3 * D  # a reset days off: the weekday makes it the widest
        for old in (False, True):
            image = self.frame([('5H', 0, far, old), ('WK', 0, far, old)])  # 100% left: the widest number
            for y in (196, 217):
                gap = [x for x in range(124, 128) for yy in range(y, y + 16) if image.getpixel((x, yy)) != readout.PANEL]
                self.assertEqual(gap, [], (old, y))  # nothing between '100%' (ends at x 123) and the reset

    def test_an_old_reading_is_muted_not_coloured(self):
        image = self.frame([('WK', 30, time.time() + D, True)])
        self.assertEqual(lit_cells(image, 205, 14, 164, readout.band(30)), 0)
        self.assertGreater(lit_cells(image, 205, 14, 164, readout.MUTED), 0)

    def test_a_long_action_beside_a_long_name_stays_on_its_line(self):
        image = self.frame([('MO', 20, None, False)], action='LONG ACTION', provider='copilot')
        right = image.crop((231, 171, 240, 194))  # nothing spills past the right margin
        self.assertEqual(right.getcolors(), [(right.width * right.height, readout.PANEL)])


class ActionTests(unittest.TestCase):
    def row(self, provider, **extra):
        data = snapshot(time.time(), [(f'{provider}_a', f'{provider.upper()} A', provider, [('WEEK', 50, 3 * D)])])
        row = dict(data['accounts'][f'{provider}_a'], key=f'{provider}_a')
        row.update(extra)
        return row

    def test_work_names_follow_the_pet_and_grok_its_job(self):
        self.assertEqual(arcade.action_label(self.row('claude', active=True), {'mood': 'calm'}, None, 0, 60), 'RUNNING')
        self.assertEqual(arcade.action_label(self.row('codex', active=True), {'mood': 'calm'}, None, 0, 60), 'CODE RAIN')
        self.assertEqual(arcade.action_label(self.row('grok', active=True), {'mood': 'calm', 'role': 'control'}, None, 0, 60),
                         'AT CONSOLE')
        self.assertEqual(arcade.action_label(self.row('grok', active=True), {'mood': 'calm', 'role': 'crew'}, None, 0, 60),
                         'REFUELING')

    def test_worry_rest_and_events_have_their_own_names(self):
        worried = {'mood': 'worried', 'idle': ('fret', 'fret')}
        self.assertEqual(arcade.action_label(self.row('claude', active=True), worried, None, 0, 60), 'RUSHING')
        self.assertEqual(arcade.action_label(self.row('claude'), worried, None, 0, 60), 'PACING')
        self.assertEqual(arcade.action_label(self.row('codex'), worried, None, 0, 60), 'FRETTING')
        rest = {'mood': 'calm', 'idle': ('nap', 'yawn')}
        self.assertEqual(arcade.action_label(self.row('codex'), rest, None, 0, 60), 'NAPPING')
        self.assertEqual(arcade.action_label(self.row('codex'), rest, None, 45, 60), 'YAWNING')
        self.assertEqual(arcade.action_label(self.row('claude'), {'mood': 'calm', 'moves': [(1, 2, 'Waving', 3, 16)]}, None,
                                             18, 120), 'WAVING')
        self.assertEqual(arcade.action_label(self.row('grok'), rest, 'full@grok_a', 0, 60), 'OUT OF FUEL')
        self.assertEqual(arcade.action_label(self.row('codex'), rest, 'reset@codex_a', 0, 60), 'CELEBRATING')
        self.assertEqual(arcade.action_label(self.row('codex'), rest, 'reset@claude_a', 0, 60), 'NAPPING')  # not its event

    def test_a_hidden_one_off_shows_the_name_sealed_with_it(self):
        stage = tuple(Image.new('RGB', (120, 71)) for _ in range(2))
        box = lockbox.Box('x', 'rare', 'codex_a', stage, 6, action='SEALED NAME')
        self.assertEqual(arcade.action_label(self.row('codex'), {'mood': 'calm'}, box, 0, 60), 'SEALED NAME')

    def test_the_line_names_what_happens_on_the_clock(self):
        now = time.time()
        data = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)])])
        line = (60, 172, 240, 192)
        stage = tuple(Image.new('RGB', (120, 71)) for _ in range(2))
        plain = arcade.arcade_frames(data, now)[0].crop(line)
        boxed = arcade.arcade_frames(data, now, lockbox.Box('x', 'rare', 'codex_a', stage, 6, action='SEALED'))[0].crop(line)
        self.assertNotEqual(plain.tobytes(), boxed.tobytes())


class PaceTests(unittest.TestCase):
    def test_the_clock_gets_every_other_drawn_frame_and_a_loop_of_four_point_two_seconds(self):
        now = time.time()
        data = snapshot(now, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 50, 3 * D)])])
        self.assertEqual(len(arcade.arcade_frames(data, now)), arcade.FRAMES // arcade.PLAYBACK)
        self.assertAlmostEqual(arcade.gif_seconds(arcade.render_arcade(data, now)), 4.2, places=2)
        self.assertAlmostEqual(arcade.LOOP_SECONDS, 4.2, places=2)

    def test_nothing_on_the_clock_waits_for_a_frame_it_skips(self):
        # Most scenes move SPEED * PLAYBACK scene frames a picture: a blink or a prop turn tied to one frame never shows.
        for name in ('arcade.py', 'events.py'):
            self.assertEqual(stepped_over(ROOT / 'token_tv' / name, arcade.SPEED * arcade.PLAYBACK), [], name)

    def test_the_propeller_turns_at_the_clocks_pace(self):
        now = time.time()
        data = snapshot(now, [('copilot_a', 'COPILOT A', 'copilot', [('MONTH', 46, 9 * D)])])
        data['accounts']['copilot_a']['active'] = True
        blades, plane = [], arcade.plane
        def spy(u, blade):
            blades.append(blade)
            return plane(u, blade)
        arcade.plane = spy
        try:
            arcade.arcade_frames(data, now)
        finally:
            arcade.plane = plane
        self.assertEqual(set(blades), {0, 1})

    def test_timelines_of_their_own_keep_their_moments(self):
        now = time.mktime((2026, 10, 28, 14, 0, 0, 0, 0, -1))
        data = snapshot(now, [('grok_a', 'GROK A', 'grok', [('BUDGET', 50, 3 * D)])])
        data['accounts']['grok_a'].update(active=True, role='control')
        shakes, stage = set(), arcade.draw_stage
        arcade.draw_stage = lambda *a, **k: shakes.add(a[13]) or stage(*a, **k)
        try:
            arcade.arcade_frames(data, now)
        finally:
            arcade.draw_stage = stage
        self.assertTrue({-1, 1} <= shakes)  # the console's test burn rumbles both ways
        rows = [('antigravity_a', 'ANTI A', 'antigravity', [('5H', 30, 2 * H)])] + [
            (f'codex_{i}', 'CODEX', 'codex', [('WEEK', 50, 3 * D)]) for i in range(2)]  # Anti gets a third of the loop
        data, looks = snapshot(now, rows), set()
        plan, art = arcade.scene_plan, arcade.anti_art
        def floating(row, at, seconds=arcade.FRAMES / arcade.FPS):
            chosen = plan(row, at, seconds)
            if row['provider'] == 'antigravity':
                chosen['idle'] = ('float', 'float')
            return chosen
        arcade.scene_plan = floating
        arcade.anti_art = lambda face='normal', **k: looks.add((face, k.get('pose', 'stand'))) or art(face, **k)
        try:
            arcade.arcade_frames(data, now)
        finally:
            arcade.scene_plan, arcade.anti_art = plan, art
        self.assertTrue({('blink', 'stand'), ('normal', 'squash')} <= looks)  # the blink, and the squash on landing


if __name__ == '__main__':
    unittest.main()
