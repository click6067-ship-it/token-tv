"""Which clocks are known to work: one card per checked unit, and `start` says which clock it found and its firmware,
asking for a report when that pair is not checked yet. Fake clocks on 127.0.0.1 only."""
import contextlib
import io
import json
import re
import sys
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py and the fake clocks, however the tests are run
from helpers import temp_dir
from test_device import answering, sd_pro_clock, serve, ultra_clock

from token_tv import cli, device

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'https://github.com/click6067-ship-it/token-tv/issues/new?template=hardware_compatibility.md'


def ultra(version):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):
            body = json.dumps({'m': 'SmallTV-Ultra', **({'v': version} if version else {})}).encode()
            self.send_response(200 if self.path == '/v.json' else 404)
            self.end_headers()
            self.wfile.write(body)
    return Handler


class ClockInfoTests(unittest.TestCase):
    def test_the_clock_says_its_model_and_firmware(self):
        calls = []
        with serve(ultra_clock({'theme': 1}, calls)) as url:
            info = device.clock_info(url)
        self.assertEqual(info, {'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.0.54'})
        self.assertEqual(calls, [('GET', '/v.json')])  # read-only, one question
        with serve(sd_pro_clock({'files': {}, 'enabled': set(), 'total': 3000000, 'base': 0}, [])) as url:
            self.assertEqual(device.clock_info(url), {'kind': 'sdpro', 'model': 'SD_PRO', 'firmware': None})
        with serve(ultra(None)) as url:
            self.assertEqual(device.clock_info(url)['firmware'], None)  # not said: not made up
        with serve(answering(500, b'oops')) as url:
            self.assertIsNone(device.clock_info(url))
        self.assertIsNone(device.clock_info('http://127.0.0.1:9', timeout=1))  # nothing there

    def test_only_checked_pairs_count_as_verified(self):
        for info, known in (({'kind': 'sdpro', 'model': 'SD_PRO', 'firmware': None}, True),
                            ({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.0.54'}, True),
                            ({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.1.54'}, True),
                            ({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.2.10'}, False),
                            ({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.0.540'}, False),
                            ({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': None}, False),
                            ({'kind': 'sdpro', 'model': 'SmallTV-PRO', 'firmware': 'V3.2'}, False)):
            with self.subTest(info=info):
                self.assertEqual(device.verified(info), known)


class StartSaysTheClockTests(unittest.TestCase):
    def start(self, info):
        from token_tv import live
        config = temp_dir(self) / 'config.json'
        config.write_text(json.dumps({'device_url': 'http://127.0.0.1:9', 'accounts': [
            {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'a@example.com'}]}), encoding='utf-8')
        out = io.StringIO()
        with mock.patch.object(device, 'clock_info', return_value=info) as asked, \
                mock.patch.object(cli, 'dashboard_port', return_value=(8787, False)), \
                mock.patch.object(live, 'main'), mock.patch('token_tv.autostart.how', return_value='token-tv'), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['start', '--config', str(config), '--yes', '--no-browser']), 0)
        asked.assert_called_once_with('http://127.0.0.1:9')
        return out.getvalue()

    def test_a_checked_clock_is_named_with_its_firmware(self):
        said = self.start({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.0.54'})
        self.assertIn('Clock: SmallTV-Ultra, firmware Ultra-V9.0.54', said)
        self.assertNotIn(REPORT, said)
        said = self.start({'kind': 'sdpro', 'model': 'SD_PRO', 'firmware': None})
        self.assertIn('Clock: SD_PRO, firmware not reported by the clock', said)
        self.assertNotIn(REPORT, said)

    def test_an_unchecked_one_is_asked_for_a_report(self):
        said = self.start({'kind': 'ultra', 'model': 'SmallTV-Ultra', 'firmware': 'Ultra-V9.2.10'})
        self.assertIn('Clock: SmallTV-Ultra, firmware Ultra-V9.2.10', said)
        self.assertIn('not checked', said)
        self.assertIn(REPORT, said)

    def test_a_clock_that_does_not_answer_gets_no_made_up_model(self):
        said = self.start(None)
        self.assertNotIn('firmware', said)
        self.assertNotIn(REPORT, said)


class PassportTests(unittest.TestCase):
    def test_one_card_per_checked_unit_with_every_field(self):
        doc = (ROOT / 'docs' / 'hardware-compatibility.md').read_text(encoding='utf-8')
        cards = re.split(r'\n### ', doc.split('\n## Verified units', 1)[1].split('\n## ', 1)[0])[1:]
        self.assertEqual(len(cards), 4)
        for card in cards:
            for field in ('Firmware', 'Still / GIF', 'Restore', 'Host', 'Date', 'Evidence'):
                self.assertRegex(card, rf'\| {re.escape(field)} \|', card.splitlines()[0])
        text = '\n'.join(cards)
        for needle in ('SD_PRO', 'Ultra-V9.0.54', '/app.json', 'Raspberry Pi 4', '9.1.54', 'pull/7', 'pull/10',
                       'https://github.com/click6067-ship-it/token-tv/pull/7#issuecomment-6433844118'):
            self.assertIn(needle, text)
        new_unit = next(card for card in cards if '/app.json' in card.splitlines()[0])
        self.assertRegex(new_unit, r'\| Restore \|[^\n]*(not checked|fake clock)')  # its restore ran only on a fake
        self.assertIn('## Not verified', doc)
        self.assertIn('hardware_compatibility.md', doc)


if __name__ == '__main__':
    unittest.main()
