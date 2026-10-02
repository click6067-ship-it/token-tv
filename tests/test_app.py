import json
import threading
import unittest
from urllib.request import urlopen

from http.server import ThreadingHTTPServer

from token_tv.app import MOCK_ACCOUNTS, make_handler
from token_tv.providers.mock import MockProvider


class SnapshotTests(unittest.TestCase):
    def test_snapshot_exposes_distinct_aliases_as_theme_paths(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(MOCK_ACCOUNTS, {
            "claude": MockProvider(),
            "codex": MockProvider(),
        }))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/snapshot") as response:
                payload = response.read()
                self.assertLessEqual(len(payload), 2048)
                self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
            data = json.loads(payload)
            self.assertEqual(data["schema"], 1)
            self.assertEqual(set(data["accounts"]), {"claude_personal", "claude_work", "codex_personal"})
            self.assertEqual(data["accounts"]["claude_work"]["alias"], "Claude work")
            self.assertEqual(data["accounts"]["claude_work"]["status"], "mock")
            with urlopen(f"http://127.0.0.1:{server.server_port}/snapshot/claude_work") as response:
                account = json.load(response)
            self.assertEqual(account["session_percent"], 61)
            self.assertEqual(account["alias"], "Claude work")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
