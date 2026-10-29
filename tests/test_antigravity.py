import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from token_tv import arcade, gif
from token_tv.display import STYLES, overview_rows, render_page
from token_tv.sample import D, H, snapshot
from token_tv.sources import codexbar_entry, load_config
from token_tv.usage import normalize_codexbar
from token_tv.web_assets import ASSETS


def pixels(image):
    """Every pixel, on old and new Pillow alike."""
    return getattr(image, 'get_flattened_data', image.getdata)()


DAY, NIGHT = time.mktime((2026, 10, 28, 14, 0, 0, 0, 0, -1)), time.mktime((2026, 10, 29, 2, 0, 0, 0, 0, -1))
STAGE = (0, 28, 240, 170)  # the stage on the clock, its pixels doubled


def anti_data(now, used=42, **fields):
    data = snapshot(now, [('anti_a', 'ANTI A', 'antigravity', [('5H', used, 2 * H)])])
    data['accounts']['anti_a'].update(fields)
    return data


def changed(a, b):
    """How many pixels differ between two frames."""
    return ImageChops.difference(a.convert('RGB'), b.convert('RGB')).convert('L').point(lambda v: 255 if v else 0).histogram()[255]

# Shapes of `codexbar usage --provider antigravity|gemini --format json` (sample values, no real account).
APP = {'provider': 'gemini', 'usage': {'primary': {'usedPercent': 42.0, 'windowMinutes': 300, 'resetsAt': 1900000000},
                                       'secondary': {'usedPercent': 18.0, 'windowMinutes': 10080},
                                       'accountEmail': 'owner@example.com'}}
CLI = {'provider': 'gemini', 'usage': {'primary': {'usedPercent': 7.0, 'windowMinutes': 1440}}}
AGY = {'provider': 'antigravity', 'usage': {'primary': {'usedPercent': 55.0, 'windowMinutes': 300}}}


class AntigravityTests(unittest.TestCase):
    def test_windows_keep_their_lengths(self):
        self.assertEqual([(w['label'], w['used_percent']) for w in normalize_codexbar(APP)], [('5H', 42.0), ('WEEK', 18.0)])
        self.assertEqual([w['label'] for w in normalize_codexbar(CLI)], ['DAY'])  # the Gemini CLI's daily quota

    def test_two_windows_of_one_length_keep_apart(self):
        both = {'provider': 'antigravity', 'usage': {'primary': {'usedPercent': 30.0}, 'secondary': {'usedPercent': 7.0}}}
        self.assertEqual([w['label'] for w in normalize_codexbar(both)], ['WINDOW', 'WINDOW2'])
        both['usage']['primary'] = {'usedPercent': None}  # a reading without the first: the second keeps its name
        self.assertEqual([w['label'] for w in normalize_codexbar(both)], ['WINDOW2'])
        del both['usage']['primary']
        self.assertEqual([w['label'] for w in normalize_codexbar(both)], ['WINDOW2'])

    def test_one_google_pet_reads_antigravity_or_gemini_through_codexbar(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            account = {'key': 'anti_a', 'alias': 'ANTI A', 'provider': 'antigravity', 'email': 'owner@example.com'}
            path.write_text(json.dumps({'accounts': [account]}))
            with self.assertRaises(ValueError):  # CodexBar owns the login
                load_config(path)
            path.write_text(json.dumps({'accounts': [dict(account, codexbar_command='codexbar')]}))
            loaded = load_config(path)['accounts'][0]
            self.assertEqual(codexbar_entry([APP, AGY], loaded)[0], AGY)  # its own entry by default
            old = dict(account, provider='gemini', codexbar_command='codexbar', codexbar_provider='gemini')
            path.write_text(json.dumps({'accounts': [old]}))
            loaded = load_config(path)['accounts'][0]
            self.assertEqual(loaded['provider'], 'antigravity')  # an old Gemini account is Anti now
            self.assertEqual(codexbar_entry([APP, AGY], loaded)[0], APP)
            older = dict(account, provider='gemini', codexbar_url='http://127.0.0.1:8080/usage?provider=gemini')
            path.write_text(json.dumps({'accounts': [older]}))
            self.assertEqual(codexbar_entry([APP, AGY], load_config(path)['accounts'][0])[0], APP)  # still its Gemini
            path.write_text(json.dumps({'accounts': [dict(account, codexbar_command='codexbar', codexbar_provider='cursor')]}))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_every_face_draws_anti(self):
        now = time.time()
        data = snapshot(now, [('anti_a', 'ANTI A', 'antigravity', [('5H', 45, 2 * H)])])
        self.assertEqual([r['provider'] for r in overview_rows(data)], ['antigravity'])
        for style in STYLES:
            self.assertEqual(Image.open(io.BytesIO(render_page(data, style=style))).size, (240, 240), style)
        data['accounts']['anti_a']['active'] = True
        frames = arcade.arcade_frames(data, now)
        self.assertTrue(ImageChops.difference(frames[0], frames[6]).getbbox())
        self.assertIn('/assets/antigravity-pixel.png', ASSETS)
        for kind in ('reset', 'full'):
            self.assertLess(len(render_page(data, style='arcade', egg=f'{kind}@anti_a')), 400000)

    def test_a_daily_window_survives_a_snapshot_handed_over(self):
        from token_tv.sources import imported_row
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            row = {'provider': 'antigravity', 'alias': 'ANTI A', 'status': 'ok', 'fetched_at': time.time() - 30,
                   'windows': [w for w in normalize_codexbar(CLI)]}
            path.write_text(json.dumps({'accounts': {'anti_a': row}}))
            account = {'key': 'anti_a', 'alias': 'ANTI A', 'provider': 'antigravity', 'snapshot_file': str(path)}
            self.assertEqual([w['label'] for w in imported_row(account)['windows']], ['DAY'])
            row.update(provider='codex', reset_credits={'count': 2, 'expires_at': 2_000_000_000})
            path.write_text(json.dumps({'accounts': {'anti_a': row}}))
            self.assertEqual(imported_row(dict(account, provider='codex'))['reset_credits'], {'count': 2, 'expires_at': 2_000_000_000})

    def test_old_names_keep_their_letter_and_full_counts_its_streak(self):
        from token_tv.display import account_label
        row = lambda alias: {'provider': 'antigravity', 'alias': alias}
        self.assertEqual([account_label(row(a)) for a in ('GEMINI B', 'ANTIGRAVITY C', 'ANTI D', 'WORK')],
                         ['ANTI B', 'ANTI C', 'ANTI D', 'ANTI A'])
        from token_tv import events
        def full(streak):
            stage = Image.new('RGB', (120, 71))
            events.event_scene('full', 'antigravity', streak)(stage, arcade.ImageDraw.Draw(stage), (0, 0, 120, 71), 110, 1)
            return stage.tobytes()
        self.assertNotEqual(full(1), full(3))  # 200, then 800

    def test_a_reset_brings_back_only_the_pellets_really_left(self):
        now = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))
        def pellets(used):
            data = snapshot(now, [('anti_a', 'ANTI A', 'antigravity', [('5H', used, 2 * H)])])
            last = arcade.arcade_frames(data, now, egg='reset@anti_a')[-1].convert('RGB').crop((0, 28, 240, 170))
            return sum(1 for p in pixels(last) if p == arcade.MAZE_DOT)
        self.assertGreater(pellets(5), pellets(80))  # a weekly reset with the 5 hours nearly gone refills little

    def test_the_pellets_are_what_is_left_of_the_five_hours(self):
        def lit(used, label='5H'):
            stage = Image.new('RGB', (120, 71))
            left = None if used is None else 1 - used / 100
            arcade.anti_pellets(arcade.ImageDraw.Draw(stage), (0, 0, 120, 71), left, label)
            return sum(1 for p in pixels(stage) if p == arcade.MAZE_DOT)
        self.assertGreater(lit(10), lit(45))
        self.assertGreater(lit(45), lit(80))
        self.assertEqual(lit(100), 0)
        self.assertEqual(lit(None), 0)

    def test_anti_turns_blue_near_the_limit_and_patrols_at_work(self):
        now = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))
        def stage(used, active, worry=False):
            data = snapshot(now, [('anti_a', 'ANTI A', 'antigravity', [('5H', used, 2 * H)])])
            data['accounts']['anti_a'].update(active=active, worry=worry)
            return [f.convert('RGB').crop((0, 28, 240, 170)) for f in arcade.arcade_frames(data, now)]
        blue = lambda frames: sum(1 for p in pixels(frames[0]) if p == arcade.ANTI_SCARED)
        calm, scared = stage(50, True), stage(95, True, True)
        self.assertGreater(blue(scared), blue(calm) + 100)  # the body itself turns blue
        self.assertGreater(blue(stage(95, False, True)), blue(stage(50, False)) + 100)
        moved = [ImageChops.difference(calm[0], calm[k]).getbbox() for k in (10, 40, 80)]
        self.assertTrue(all(moved))  # round the maze

    def test_anti_wears_the_v2_face_and_no_feet(self):
        art, logo = arcade.anti_art(), arcade.anti_logo()
        self.assertEqual(art.size, (24, 19))  # the legs' last row half height: no feet
        for y in range(art.height):
            for x in range(art.width):
                block, here = logo.getpixel((x // 2, y // 2)), art.getpixel((x, y))
                self.assertEqual(bool(here[3]), bool(block[3]) or (y == 10 and 10 <= x <= 13), (x, y))  # the logo and its chin
                if block[3] and not (7 <= x <= 16 and 3 <= y <= 10):  # its colours, round the face
                    self.assertEqual(here[:3], block[:3], (x, y))
        self.assertEqual([art.getpixel(p)[:3] for p in ((9, 4), (13, 4))], [arcade.ANTI_GLINT] * 2)  # a glint on each bean
        self.assertEqual([art.getpixel(p)[:3] for p in ((10, 4), (9, 6), (14, 6), (10, 8))], [arcade.ANTI_NAVY] * 4)
        for face in ('normal', 'blink', 'sleep', 'curious', 'roll', 'happy'):
            self.assertEqual({arcade.anti_art(face).getpixel(p)[:3] for p in arcade.ANTI_CHEEKS}, {arcade.ANTI_CHEEK}, face)
        for face, body in (('scared', 'scared'), ('wide_scared', 'scared'), ('low_scared', 'scared'), ('wide_flash', 'flash')):
            inks = {p[:3] for p in pixels(arcade.anti_art(face, body)) if p[3]}  # frightened faces stay frightened
            self.assertFalse({arcade.ANTI_CHEEK, arcade.ANTI_GLINT} & inks, face)

    def test_the_dashboard_shows_the_clocks_anti(self):
        sprite = Image.open(arcade.ASSETS / 'antigravity-pixel.png').convert('RGBA')
        drawn = Image.new('RGBA', (32, 32))
        drawn.paste(arcade.anti_art(), (4, 6))
        self.assertEqual(sprite.tobytes(), drawn.tobytes())

    def test_anti_rests_a_minute_at_a_time_and_sleeps_the_night_through(self):
        row = dict(anti_data(DAY)['accounts']['anti_a'], key='anti_a')
        idles = {}
        for minute in range(6 * 60):  # six hours of afternoon: every step of the rest flow, the rare one too
            step, _ = arcade.rest_step('antigravity', DAY + 60 * minute)
            idles.setdefault(step, arcade.scene_plan(row, DAY + 60 * minute)['idle'])
        self.assertEqual(idles, {None: ('bounce', 'bounce'), 'look': ('arch', 'bounce'), 'stretch': ('float', 'bounce'),
                                 'rare': ('umbrella', 'bounce')})
        for minute in range(6):
            self.assertEqual(arcade.scene_plan(row, NIGHT + 60 * minute)['idle'], ('blanket', 'blanket'))
        worried = dict(anti_data(NIGHT, 95, worry=True)['accounts']['anti_a'], key='anti_a')
        self.assertEqual(arcade.scene_plan(worried, NIGHT)['idle'], ('fret', 'fret'))

    def test_each_rest_piece_keeps_the_gauge_on_the_open_floor_and_meets_its_start(self):
        gauge = Image.new('RGB', (120, 71), arcade.MAZE_BG)
        arcade.anti_pellets(arcade.ImageDraw.Draw(gauge), (0, 0, 120, 71), .58)
        lit = [(x, y) for y in range(71) for x in range(120) if gauge.getpixel((x, y)) == arcade.MAZE_DOT]
        for idle in ('bounce', 'bounce'), ('arch', 'bounce'), ('float', 'bounce'), ('umbrella', 'bounce'), \
                    ('blanket', 'blanket'), ('fret', 'fret'):
            frames = arcade.arcade_frames(anti_data(DAY, showcase=list(idle)), DAY)
            self.assertTrue(all(f.getpixel((2 * x, 28 + 2 * y)) == arcade.MAZE_DOT for f in frames for x, y in lit), idle)
            self.assertNotIn(arcade.MAZE_DOOR, {c for _, c in frames[0].getcolors(1 << 16)}, idle)  # no house at rest
            steps = [changed(a, b) for a, b in zip(frames, frames[1:])]
            self.assertTrue(max(steps), idle)
            self.assertLessEqual(changed(frames[-1], frames[0]), max(steps), idle)  # no jump where the loop meets its start

    def test_a_reset_pops_the_pellets_in_and_anti_hops_for_joy(self):
        frames = [f.crop(STAGE) for f in arcade.arcade_frames(anti_data(DAY, 2), DAY, egg='reset@anti_a')]
        dots = lambda image: sum(1 for p in pixels(image) if p == arcade.MAZE_DOT)
        everyday = arcade.arcade_frames(anti_data(DAY, 2, showcase=['bounce']), DAY)[0].crop(STAGE)
        self.assertLess(dots(frames[0]), dots(frames[-1]))  # left out at first, then in
        self.assertEqual(dots(frames[-1]), dots(everyday))  # as many as the gauge shows any other time
        def top(image):  # the highest row of Anti, between the top row of dots and the floor
            band = image.crop((96, 44, 144, 120))
            return 44 + next(y for y in range(band.height) if any(band.getpixel((x, y)) != arcade.MAZE_BG for x in range(band.width)))
        self.assertGreaterEqual(sum(1 for f in frames[12:30] if top(f) <= top(frames[0]) - 16), 6)  # 8 px up for half a second

    def test_every_anti_state_fits_the_upload_alone_and_among_four(self):
        others = [('claude_a', 'CLAUDE A', 'claude', [('5H', 41, 2 * H)]), ('codex_a', 'CODEX A', 'codex', [('WEEK', 47, 4 * D)]),
                  ('grok_a', 'GROK A', 'grok', [('BUDGET', 61, 6 * D)])]
        states = [(DAY, 42, {'active': True}), (DAY, 95, {'active': True, 'worry': True}), (NIGHT, 42, {}),
                  (DAY, 95, {'worry': True})] + [(DAY, 42, {'showcase': [idle, 'bounce']}) for idle in ('bounce', 'arch', 'float', 'umbrella')]
        for four in (False, True):
            for now, used, fields in states:
                data = snapshot(now, [('anti_a', 'ANTI A', 'antigravity', [('5H', used, 2 * H)])] + (others if four else []))
                for key, row in data['accounts'].items():
                    row.update(fields if key == 'anti_a' else {'active': fields.get('active', False)})
                frames = arcade.arcade_frames(data, now)
                whole = gif.encode(gif.indexed(frames, 'Arcade'), [arcade.FRAME_MS] * len(frames))
                self.assertLessEqual(len(whole), arcade.BUDGET, (four, now, used, fields))  # every frame kept
        for kind, used in (('reset', 2), ('full', 100)):
            frames = arcade.arcade_frames(anti_data(DAY, used), DAY, egg=f'{kind}@anti_a')
            self.assertLessEqual(len(gif.encode(gif.indexed(frames, 'Arcade'), [arcade.FRAME_MS] * 120)), arcade.BUDGET)


if __name__ == '__main__':
    unittest.main()
