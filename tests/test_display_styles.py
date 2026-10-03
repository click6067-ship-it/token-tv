import copy
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from PIL import Image

from token_tv.display import STYLES, gauge_color, render_page
from token_tv.live import DisplayPreferences, handler
from token_tv.sources import load_config
from token_tv.state import UsageStore


class DisplayStyleTests(unittest.TestCase):
    def test_style_picker_persists_without_querying_accounts(self):
        account = {'key': 'a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'owner@example.com'}
        row = dict(account, status='ok', windows=[{'label': 'WEEK', 'used_percent': 94, 'resets_at': None}], fetched_at=100)
        fetch = Mock(return_value=row)
        store = UsageStore([account], fetch=fetch)
        store.refresh()
        baseline = copy.deepcopy(store.snapshot())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            config = {'accounts': [account], 'display_style': 'pixel'}
            path.write_text(json.dumps(config))
            prefs = DisplayPreferences(path, config)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(store, prefs))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            root = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(root + '/frame/0.jpg?style=digital') as response:
                    preview = response.read()
                self.assertEqual(Image.open(io.BytesIO(preview)).size, (240, 240))
                self.assertEqual(prefs.snapshot()['style'], 'pixel')
                request = Request(root + '/display/style', data=b'{"style":"digital"}', headers={'Content-Type': 'application/json'})
                with urlopen(request) as response:
                    self.assertEqual(json.load(response)['style'], 'digital')
                self.assertTrue(prefs.changed.is_set())
                self.assertEqual(load_config(path)['display_style'], 'digital')
                self.assertEqual(DisplayPreferences(path, load_config(path)).snapshot()['style'], 'digital')
                for style in STYLES:
                    with urlopen(root + '/frame/0.jpg?style=' + style) as response:
                        self.assertEqual(Image.open(io.BytesIO(response.read())).size, (240, 240))
                    request = Request(root + '/display/style', data=json.dumps({'style': style}).encode(), headers={'Content-Type': 'application/json'})
                    with urlopen(request) as response:
                        self.assertEqual(json.load(response)['style'], style)
                    self.assertEqual(DisplayPreferences(path, load_config(path)).snapshot()['style'], style)
                for payload, origin in ((b'{"style":"unknown"}', None), (b'{"style":"pixel"}', 'https://unrelated.example')):
                    headers = {'Content-Type': 'application/json'}
                    if origin:
                        headers['Origin'] = origin
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(Request(root + '/display/style', data=payload, headers=headers))
                    self.assertIn(raised.exception.code, (400, 403))
                self.assertEqual(load_config(path)['display_style'], STYLES[-1])
                self.assertEqual(store.snapshot(), baseline)
                self.assertEqual(fetch.call_count, 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_all_styles_keep_same_payload_contract_and_unknown_states(self):
        sample = {'accounts': {'a': {'alias': 'CLAUDE A', 'provider': 'claude', 'status': 'auth_required', 'windows': []}}}
        frames = [render_page(sample, style=style) for style in STYLES]
        self.assertEqual(len(set(frames)), len(STYLES))
        for status in ('ok', 'stale'):
            sample['accounts']['a'].update(status=status, windows=[{'label': 'WEEK', 'used_percent': 100, 'resets_at': None}])
            frames.extend(render_page(sample, style=style) for style in STYLES)
        for frame in frames:
            image = Image.open(io.BytesIO(frame))
            self.assertEqual(image.size, (240, 240))
            if frame[:4] == b'GIF8':  # the animated Space face
                self.assertEqual(image.format, 'GIF')
                self.assertGreater(image.n_frames, 1)
                self.assertLess(len(frame), 400000)
            else:
                self.assertEqual(image.format, 'JPEG')
                self.assertLess(len(frame), 60000)
        self.assertEqual(sum(f[:4] == b'GIF8' for f in frames[:len(STYLES)]), 1)
        with self.assertRaises(ValueError):
            render_page(sample, style='unknown')

    def test_gauge_enters_high_at_80_and_critical_at_90(self):
        self.assertEqual(gauge_color(49), (118, 169, 154))
        self.assertEqual(gauge_color(50), (147, 201, 185))
        self.assertEqual(gauge_color(79), (147, 201, 185))
        self.assertEqual(gauge_color(80), (209, 178, 117))
        self.assertEqual(gauge_color(89), (209, 178, 117))
        self.assertEqual(gauge_color(90), (216, 135, 126))
        self.assertEqual(gauge_color(100), (216, 135, 126))

    def test_config_rejects_unknown_display_style(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            config = {'accounts': [{'key': 'a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'owner@example.com'}], 'display_style': 'unknown'}
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == '__main__':
    unittest.main()


class ConfiguredServicesOnlyTest(unittest.TestCase):
    def test_only_services_with_accounts_get_a_row(self):
        import time
        from token_tv.display import STYLES, overview_rows, render_page
        from token_tv.sample import H, snapshot
        data = snapshot(time.time(), [('claude_a', 'CLAUDE A', 'claude', [('5H', 72, 2 * H)])])
        self.assertEqual([r['provider'] for r in overview_rows(data)], ['claude'])  # no LOGIN rows for unused services
        for style in STYLES:
            self.assertTrue(render_page(data, style=style))  # every face copes with one row
        self.assertEqual(len(overview_rows({'accounts': {}})), 3)  # empty config keeps the placeholders
