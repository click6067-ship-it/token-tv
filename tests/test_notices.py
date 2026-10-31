"""What the public documents promise: whose Clawd's animations are, and which clocks are known to work."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RightsTests(unittest.TestCase):
    def test_clawds_animations_are_anthropics_outside_the_mit_grant(self):
        licence = (ROOT / 'LICENSE').read_text(encoding='utf-8')
        self.assertTrue(licence.startswith('MIT License'))
        self.assertIn('Permission is hereby granted, free of charge', licence)  # the grant itself unchanged
        self.assertTrue(licence.endswith('OTHER DEALINGS IN THE\nSOFTWARE.\n'))  # only MIT, so GitHub reads it as MIT
        notice = (ROOT / 'NOTICE').read_text(encoding='utf-8')
        assets = (ROOT / 'token_tv' / 'assets' / 'README.md').read_text(encoding='utf-8')
        self.assertIn('`NOTICE`', assets)
        for text in (notice, assets):
            flat = ' '.join(text.split())
            self.assertIn('clawd.json', flat)
            self.assertIn('Anthropic', flat)
            self.assertRegex(flat, r'outside (the|this) MIT')
            self.assertIn('fan work', flat)
            self.assertIn('removed on request', flat)
        self.assertIn('## Names and marks', assets)
        self.assertIn('not affiliated with or\nendorsed by', assets)


if __name__ == '__main__':
    unittest.main()
