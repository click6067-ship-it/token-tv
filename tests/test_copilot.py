import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from token_tv import arcade
from token_tv.display import STYLES, overview_rows, render_page
from token_tv.sample import D, snapshot
from token_tv.sources import load_config
from token_tv.usage import normalize_codexbar
from token_tv.web_assets import ASSETS

# Shape of `codexbar usage --provider copilot --format json` (sample values, no real account).
ENTRY = {'provider': 'copilot', 'usage': {'primary': {'usedPercent': 38.0}, 'secondary': {'usedPercent': 12.5},
                                          'accountEmail': 'owner@example.com'}}


class CopilotTests(unittest.TestCase):
    def test_codexbar_copilot_slots_become_the_month_and_chat(self):
        windows = normalize_codexbar(ENTRY)
        self.assertEqual([(w['label'], w['used_percent'], w['resets_at']) for w in windows],
                         [('MONTH', 38.0, None), ('CHAT', 12.5, None)])  # GitHub gives no reset time

    def test_copilot_accounts_are_read_through_codexbar_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            account = {'key': 'copilot_a', 'alias': 'COPILOT A', 'provider': 'copilot', 'email': 'owner@example.com'}
            path.write_text(json.dumps({'accounts': [account]}))
            with self.assertRaises(ValueError):
                load_config(path)
            path.write_text(json.dumps({'accounts': [dict(account, codexbar_command='codexbar')]}))
            self.assertEqual(load_config(path)['accounts'][0]['provider'], 'copilot')

    def test_every_face_draws_a_copilot_row_and_its_scene_moves(self):
        now = time.time()
        data = snapshot(now, [('copilot_a', 'COPILOT A', 'copilot', [('MONTH', 38, None)])])
        self.assertEqual([r['provider'] for r in overview_rows(data)], ['copilot'])
        for style in STYLES:
            image = Image.open(io.BytesIO(render_page(data, style=style)))
            self.assertEqual(image.size, (240, 240), style)
        data['accounts']['copilot_a']['active'] = True
        frames = arcade.arcade_frames(data, now)
        self.assertTrue(ImageChops.difference(frames[0], frames[6]).getbbox())
        self.assertIn('/assets/copilot-pixel.png', ASSETS)

    def test_four_services_take_turns_on_arcade(self):
        now = time.time()
        data = snapshot(now, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 86, 3 * D)]),
                              ('codex_a', 'CODEX A', 'codex', [('WEEK', 47, 4 * D)]),
                              ('grok_a', 'GROK A', 'grok', [('BUDGET', 61, 6 * D)]),
                              ('copilot_a', 'COPILOT A', 'copilot', [('MONTH', 38, None)])])
        self.assertEqual(len(overview_rows(data)), 4)
        self.assertLess(len(arcade.render_arcade(data, now)), 400000)


if __name__ == '__main__':
    unittest.main()
