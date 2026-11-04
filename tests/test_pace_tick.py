"""v2 phase 2, x4: on every weekly window's battery a small tick where even use over the week would have left the
charge now; the battery shows what is left, so the tick stands at the share of the week still to come, and charge
that falls short of it is overspend, the gap to it red (the owner's style A). 5-hour windows get none. Time passing
alone sends no picture: the tick moves with the next picture sent for anything else."""
import io
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import Rig  # noqa: E402

from token_tv import arcade, readout  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402

WEEK = 7 * D
TICK_TOLERANCE = 1  # native pixels
NOW = 1793509260
ONE = (10, 195, 158, 20)  # the one-window battery: x, y, w, h
TWO = (24, 196 + 21, 44, 16)  # the weekly one of two (under the 5-hour one)


def track(box):
    """The battery's usable fill track: its first column and its width."""
    x, y, w, h = box
    return x + 4, w - 8


def tick_columns(image, box):
    """The columns the tick takes, read where only it reaches: the rows above the battery's case."""
    x, y, w, h = box
    return [c for c in range(x - 2, x + w + 4) if image.getpixel((c, y - 1)) == readout.TICK]


def ticked(image, box, share):
    """Whether the tick stands for `share` of the week gone, measured along the usable track (its middle)."""
    columns = tick_columns(image, box)
    if not columns:
        return False
    ix, iw = track(box)
    middle = (min(columns) + max(columns) + 1) / 2  # a tick two pixels wide: between them
    return abs(middle - (ix + iw * (1 - share))) <= TICK_TOLERANCE


def readout_image(rows, paces):
    image = Image.new('RGB', (240, 240), readout.PANEL)
    readout.draw_battery(image, ImageDraw.Draw(image), 'claude', 'RUNNING', rows, NOW, paces)
    return image


class TickPlacementTests(unittest.TestCase):
    def test_the_tick_stands_at_the_share_of_the_week_still_to_come(self):
        for share in (0, .25, .5, .75, .999):
            start = NOW - 777  # a week begun at no particular hour
            resets = start + WEEK
            at = start + share * WEEK
            self.assertAlmostEqual(arcade.pace_share({'resets_at': resets}, at), share)
            one = readout_image([('WK', 30, resets, False)], [arcade.pace_share({'resets_at': resets}, at)])
            self.assertTrue(ticked(one, ONE, share), share)
            two = readout_image([('5H', 30, NOW + H, False), ('WK', 30, resets, False)],
                                [None, arcade.pace_share({'resets_at': resets}, at)])
            self.assertTrue(ticked(two, TWO, share), share)
            self.assertEqual(tick_columns(two, (24, 196, 44, 16)), [])  # the 5-hour battery: none
            ix, iw = track(ONE)
            for c in tick_columns(one, ONE):
                self.assertTrue(ix - 1 <= c <= ix + iw, (share, c))  # within the track, at either end too

    def test_under_and_over_pace_show_at_a_glance(self):
        resets, at = NOW + WEEK / 2, NOW  # half the week gone
        share = arcade.pace_share({'resets_at': resets}, at)
        ix, iw = track(ONE)
        tick = ix + iw * (1 - share)
        for used, behind in ((25, True), (75, False)):
            image = readout_image([('WK', used, resets, False)], [share])
            self.assertTrue(ticked(image, ONE, share))
            row = [image.getpixel((c, 205)) for c in range(ix, ix + iw)]
            lit = [ix + k for k, c in enumerate(row) if c == readout.band(used)]
            red = [ix + k for k, c in enumerate(row) if c == readout.OVERSPEND]
            if behind:  # 75% left at half the week: charge past the tick, nothing red
                self.assertGreater(max(lit), tick)
                self.assertEqual(red, [])
            else:  # 25% left: the charge stops short, and the gap up to the tick is red
                self.assertLess(max(lit), tick)
                self.assertTrue(red and min(red) > max(lit) and max(red) < tick)
        for used in (0, 100):  # full and empty: the tick still there
            self.assertTrue(ticked(readout_image([('WK', used, resets, False)], [share]), ONE, share))

    def test_over_pace_the_red_meets_the_charge_with_no_dark_column_between(self):
        import re
        for x, y, w, h in (ONE, TWO):
            cells = 10 if w > 100 else 5
            ix, iw = track((x, y, w, h))
            cw = (iw - 2 * (cells - 1)) / cells  # (a cell's width: 2 px between cells)
            for share in (.3, .5, .7):
                for used in range(round(100 * share) + 1, 100):  # over pace: less left than the week still to come
                    image = Image.new('RGB', (240, 240), readout.PANEL)
                    readout.battery(ImageDraw.Draw(image), x, y, w, h, used, cells, pace=share)
                    for k in range(cells):  # each cell, along its middle: charge, then red, then the empty track
                        x0, x1 = round(ix + k * (cw + 2)), round(ix + k * (cw + 2) + cw) - 1
                        cell = ''.join('t' if colour == readout.TRACK else 'r' if colour == readout.OVERSPEND else 'o'
                                       for colour in (image.getpixel((c, y + h // 2)) for c in range(x0, x1 + 1)))
                        self.assertIsNone(re.search('t.*r', cell), (w, share, used, k, cell))  # no dark seam

    def test_every_weekly_battery_gets_one_by_its_length_and_short_ones_none(self):
        cases = [
            ({'label': 'WEEK', 'duration_minutes': 10080}, True),
            ({'label': 'WEEK'}, True),  # no length given: by its name
            ({'label': 'WEEK2', 'duration_minutes': 10080}, True),  # a second weekly window
            ({'label': 'WINDOW', 'duration_minutes': 10080}, True),  # a week under another name
            ({'label': '5H', 'duration_minutes': 300}, False),
            ({'label': '5H'}, False),
            ({'label': 'BUDGET'}, False),
            ({'label': 'MONTH'}, False),
            ({'label': 'WEEK', 'duration_minutes': 300}, False),  # its length says otherwise
        ]
        for window, weekly in cases:
            self.assertEqual(arcade.weekly(window), weekly, window)

    def test_arcade_puts_each_weekly_window_its_own_tick_from_its_own_reset(self):
        accounts = [('claude_a', 'CLAUDE A', 'claude', [('5H', 40, 2 * H), ('WEEK', 50, 2 * D)]),
                    ('codex_b', 'CODEX B', 'codex', [('WEEK', 50, 5 * D)]),
                    ('grok_a', 'GROK A', 'grok', [('BUDGET', 50, 5 * D)])]
        data = snapshot(NOW, accounts)
        for row in data['accounts'].values():
            for window in row['windows']:
                window['duration_minutes'] = {'5H': 300, 'WEEK': 10080}.get(window['label'])
        data['pace_at'] = NOW
        frames = arcade.arcade_frames(data, NOW)
        shown = arcade.shown_rows(data, NOW)
        turn = len(frames) // len(shown)
        for k, row in enumerate(shown):
            frame = frames[k * turn + 1]
            weekly = [w for w in row['windows'] if w['label'] == 'WEEK']
            box = TWO if len(row['windows']) == 2 else ONE
            if weekly:
                self.assertTrue(ticked(frame, box, arcade.pace_share(weekly[0], NOW)), row['key'])
            else:
                self.assertEqual(tick_columns(frame, ONE), [], row['key'])

    def test_a_picture_drawn_for_a_given_time_has_its_tick_there_whatever_the_time_now(self):
        data = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', [('WEEK', 50, 3 * D)])])
        resets = data['accounts']['codex_a']['windows'][0]['resets_at']
        for at in (NOW - 2 * D, NOW, NOW + D):
            data['pace_at'] = at
            frame = arcade.arcade_frames(data, NOW)[0]
            self.assertTrue(ticked(frame, ONE, arcade.pace_share({'resets_at': resets}, at)), at)


class TickTimingTests(unittest.TestCase):
    """Through live.main with the wall clock moving: hours pass and the tick's place moves on, but nothing is sent
    for it; the next picture sent for another reason has it where it is then."""
    def test_time_alone_sends_nothing_and_the_next_real_change_brings_the_tick_along(self):
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('WEEK', 40, 3 * D)]})
        first, began = rig.showing()
        resets = rig.readings['codex_a']['windows'][0]['resets_at']
        self.assertTrue(ticked(Image.open(io.BytesIO(first)).convert('RGB'), ONE,
                               arcade.pace_share({'resets_at': resets}, rig.now())))
        k = 0
        while rig.poll_at(k + 1) < rig.t0 + 3 * H:  # three hours of the same readings: the tick's place moves on
            k += 1
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        self.assertEqual(rig.switches(began + .001), [])  # nothing sent for it, nothing restarted
        self.assertEqual(rig.showing()[0], first)
        ix, iw = track(ONE)
        moved = iw * 3 * H / WEEK
        self.assertGreater(moved, 2)  # (more than a pixel's worth of the track)
        rig.set('codex_a', 'WEEK', 55)  # a real change
        changed = rig.poll_at(k + 1)
        rig.write(rig.now() + changed - rig.clock.now())
        rig.clock.to(changed + .5)
        rig.clock.to(rig.end_of_loop(changed) + .3)
        image, at = rig.showing()
        self.assertEqual(len(rig.switches(began + .001)), 1)  # one picture: the change and the tick together
        drawn = rig.now() - (rig.clock.now() - changed)  # it was drawn as that reading came in
        frame = Image.open(io.BytesIO(image)).convert('RGB')
        self.assertTrue(ticked(frame, ONE, arcade.pace_share({'resets_at': resets}, drawn)))
        self.assertFalse(ticked(frame, ONE, arcade.pace_share({'resets_at': resets}, rig.t0 - rig.clock.now() + rig.now())))

    def test_a_new_week_moves_the_tick_back_with_the_reset_picture(self):
        rig = Rig(self, providers=('codex',), wall=True, windows={'codex': [('WEEK', 80, 60)]})  # the week nearly over
        old, began = rig.showing()
        frame = Image.open(io.BytesIO(old)).convert('RGB')
        ix, iw = track(ONE)
        self.assertLessEqual(max(tick_columns(frame, ONE)), ix + 1)  # at the empty end: the week is gone
        window = rig.readings['codex_a']['windows'][0]
        window.update(used_percent=0, resets_at=rig.now() + 120 + WEEK)  # the new week, just begun
        rig.write(rig.now() + rig.poll_at(1) - rig.clock.now())
        rig.clock.to(rig.poll_at(1) + 30)
        rig.clock.advance(60)
        image, _ = rig.showing()
        frame = Image.open(io.BytesIO(image)).convert('RGB')
        self.assertGreaterEqual(min(tick_columns(frame, ONE)), ix + iw - 2)  # back at the full end


if __name__ == '__main__':
    unittest.main()
