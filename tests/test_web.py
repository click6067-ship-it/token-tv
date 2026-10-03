import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
from token_tv.live import handler
from token_tv.state import UsageStore
from token_tv.web_assets import ASSETS


class WebAssetTests(unittest.TestCase):
    def test_assets_are_allowlisted_and_dashboard_is_live(self):
        store = UsageStore([])
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(store))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        root = f'http://127.0.0.1:{server.server_port}'
        try:
            html = urlopen(root).read().decode()
            self.assertIn('/assets/app.js', html)
            for name, mime in [('app.js', 'text/javascript'), ('style.css', 'text/css'), ('tokens.css', 'text/css')]:
                with urlopen(root + '/assets/' + name) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.headers['Content-Type'].startswith(mime))
                    self.assertGreater(len(response.read()), 100)
            for path, (_, mime) in ASSETS.items():
                with urlopen(root + path) as response:
                    self.assertEqual(response.headers['Content-Type'], mime, path)
                    self.assertGreater(len(response.read()), 100, path)
            for path in ['/assets/../.runtime/config.json', '/assets/%2e%2e/.runtime/config.json', '/assets/config.json']:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(root + path)
                self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class ThemesEndpointTests(unittest.TestCase):
    def test_themes_endpoint_lists_installed_styles(self):
        import json
        from token_tv.display import STYLES
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(UsageStore([])))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/themes') as response:
                data = json.load(response)
            self.assertEqual({t['id'] for t in data['themes'] if t['installed']}, set(STYLES))
            self.assertIn('last_attempt_at', data)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_demo_build_writes_themes_without_apply(self):
        import importlib.util
        import json
        import tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_demo', root / 'scripts' / 'build_demo.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out = Path(tempfile.mkdtemp()) / 'site'
        module.build(out, 'https://example.com')
        themes = json.loads((out / 'demo-themes.json').read_text())
        self.assertEqual(len(themes['themes']), 6)
        self.assertIn('data-demo', (out / 'index.html').read_text())
