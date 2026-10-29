import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from token_tv import arcade
from token_tv.display import STYLES, overview_rows, render_page
from token_tv.sample import H, snapshot
from token_tv.sources import codexbar_entry, load_config
from token_tv.usage import normalize_codexbar
from token_tv.web_assets import ASSETS


def pixels(image):
    """Every pixel, on old and new Pillow alike."""
    return getattr(image, 'get_flattened_data', image.getdata)()

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


if __name__ == '__main__':
    unittest.main()
