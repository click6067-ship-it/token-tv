"""The contract every accepted service keeps, so a contributor who adds one hears what is missing from a test, not
from a user whose clock went dark; and a service no face knows yet still gets a plain pet on Arcade."""
import io
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from token_tv import arcade, cli, display, events, sources, themes
from token_tv.display import STYLES, render_page
from token_tv.sample import D, H, snapshot
from token_tv.web_assets import ASSETS

ROOT = Path(display.__file__).resolve().parent
DOCS = ROOT.parent / 'docs' / 'adding-a-provider.md'


def accepted():
    """The services load_config takes, read from load_config itself (an unknown one is refused)."""
    names = []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'config.json'
        for provider in display.PROVIDERS + ('newprovider',):
            account = {'key': 'a', 'alias': 'A', 'provider': provider, 'email': 'a@example.com'}
            if provider in sources.CODEXBAR_ONLY:
                account['codexbar_command'] = 'codexbar'
            path.write_text(json.dumps({'accounts': [account]}), encoding='utf-8')
            try:
                sources.load_config(path)
                names.append(provider)
            except ValueError:
                pass
    return names


def decodes(image):
    picture = Image.open(io.BytesIO(image))
    picture.load()
    return picture.size


class ContractTests(unittest.TestCase):
    def test_every_accepted_service_is_drawn_everywhere(self):
        services = accepted()
        self.assertEqual(sorted(services), sorted(display.PROVIDERS))  # load_config takes what the faces draw
        self.assertTrue(set(cli.PROVIDERS) <= set(services))
        script = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        for provider in services:
            with self.subTest(provider=provider):
                self.assertIn(provider, arcade.SCENES)
                self.assertIn(provider, display.PROVIDER_INK)
                for theme, colours in themes.ACCENT.items():
                    self.assertIn(provider, colours, theme)
                self.assertTrue((ROOT / 'assets' / f'{provider}-pixel.png').is_file())
                self.assertIn(f'/assets/{provider}-pixel.png', ASSETS)
                self.assertIn(f"'{provider}'", re.search(r'const PROVIDERS = \[(.*?)\]', script).group(1))
                self.assertIn(f'{provider}:', re.search(r'const COMPANIES = \{(.*?)\}', script).group(1))
                now = time.time()
                data = snapshot(now, [(f'{provider}_a', provider.upper() + ' A', provider, [('5H', 41, 2 * H), ('WEEK', 86, 3 * D)])])
                for style in STYLES:
                    self.assertEqual(decodes(render_page(data, 0, style)), (240, 240), style)
                for kind in ('reset', 'full'):
                    egg = f'{kind}@{provider}_a'
                    self.assertEqual(decodes(arcade.render_arcade(data, now, egg=egg)), (240, 240), kind)

    def test_the_guide_lists_the_arcade_scene_and_its_events(self):
        guide = DOCS.read_text(encoding='utf-8')
        for step in ('token_tv/arcade.py', 'SCENES', 'token_tv/events.py', 'event_scene', 'tests/test_providers.py'):
            self.assertIn(step, guide)

    def test_the_old_inline_dashboard_is_gone(self):
        self.assertFalse(hasattr(display, 'HTML'))  # the dashboard is token_tv/web/index.html, served by web_assets


class UnknownServiceTests(unittest.TestCase):
    """A service no face knows yet (a contributor's first try, say) gets a plain pet on Arcade, never a KeyError."""
    def frames(self, active=False, egg=None):
        now = time.time()
        data = snapshot(now, [('new_a', 'NEW A', 'newprovider', [('5H', 12, H)])])
        data['accounts']['new_a']['active'] = active
        return arcade.arcade_frames(data, now, egg=egg)

    def test_a_plain_pet_stands_in(self):
        idle, working = self.frames(), self.frames(active=True)
        self.assertEqual(len(idle), arcade.FRAMES // arcade.PLAYBACK)
        stage = lambda frame: frame.crop((0, 28, 240, 170))
        empty = Image.new('RGB', (240, 142), arcade.PANEL)
        self.assertTrue(any(stage(f).tobytes() != empty.tobytes() for f in idle))  # something is drawn
        inks = {c for _, c in stage(idle[0]).getcolors(1 << 16)}
        self.assertIn(arcade.PLAIN_INK['body'], inks)
        self.assertGreater(len({stage(f).tobytes() for f in working}), len({stage(f).tobytes() for f in idle}))  # it moves while working
        for kind in ('reset', 'full'):
            frames = self.frames(egg=f'{kind}@new_a')
            self.assertIn(arcade.PLAIN_INK['body'], {c for _, c in stage(frames[30]).getcolors(1 << 16)}, kind)

    def test_a_known_services_event_is_its_own_not_the_plain_pet(self):
        scene = events.event_scene('reset', 'copilot')
        frame = Image.new('RGB', (120, 71), arcade.PANEL)
        from PIL import ImageDraw
        scene(frame, ImageDraw.Draw(frame), (0, 0, 120, 71), 10, 1)
        self.assertNotIn(arcade.PLAIN_INK['body'], {c for _, c in frame.getcolors(1 << 16)})


if __name__ == '__main__':
    unittest.main()
