import email
import email.policy
import json
import socket
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from token_tv import live
from token_tv.device import BackupMismatch, PhotoDisplay, UltraDisplay, open_display


class DisplayTests(unittest.TestCase):
    def test_upload_contract_preserves_existing_files_and_restores_theme(self):
        calls = []
        themes = {"interval": 10, "themes": [{"id": 0, "enabled": True}, {"id": 2, "enabled": False}]}
        photos = {"interval": 10, "files": [{"name": "original.jpg", "size": 10, "enabled": True}, {"name": "space man.gif", "size": 20, "enabled": True}], "total": 3000000, "used": 1000000}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return
            def do_GET(self):
                calls.append(("GET", self.path, b""))
                url = urlparse(self.path)
                if url.path == "/photo/toggle":
                    query = parse_qs(url.query)
                    for photo in photos["files"]:
                        if photo["name"] == query["name"][0]:
                            photo["enabled"] = query["state"][0] == "1"
                if url.path == "/theme/toggle":
                    query = parse_qs(url.query)
                    identifier, enabled = int(query["id"][0]), query["state"][0] == "1"
                    proposed = [dict(t, enabled=enabled) if t["id"] == identifier else t for t in themes["themes"]]
                    if not any(t["enabled"] for t in proposed):
                        self.send_response(403)
                        self.end_headers()
                        return
                    themes["themes"] = proposed
                data = themes if self.path == "/theme/list" else photos if self.path == "/photo/list" else {"ok": True}
                body = json.dumps(data).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                calls.append(("POST", self.path, body))
                self.send_response(200)
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            display = PhotoDisplay(f"http://127.0.0.1:{server.server_port}")
            original = display.capture()
            photos["files"].extend([{"name": name, "enabled": True} for name in ("tokentv-c.jpg", "tokentv-m.jpg", "tokentv.jpg")])
            display.upload("tokentv.jpg", b"EXACT-JPEG")
            display.activate(original)
            self.assertEqual([p["name"] for p in photos["files"] if p["enabled"]], ["tokentv.jpg"])
            # Switching to the animated face shows only the GIF; switching back restores the JPEG.
            photos["files"].append({"name": "tokentv.gif", "enabled": False})
            display.upload("tokentv.gif", b"GIF89a-EXACT")
            display.activate(original, "tokentv.gif")
            self.assertEqual([p["name"] for p in photos["files"] if p["enabled"]], ["tokentv.gif"])
            display.activate(original, "tokentv.jpg")
            self.assertEqual([p["name"] for p in photos["files"] if p["enabled"]], ["tokentv.jpg"])
            with self.assertRaises(ValueError):
                display.upload("other.gif", b"GIF89a")
            display.restore(original)
            self.assertEqual([p["name"] for p in photos["files"] if p["enabled"]], ["original.jpg", "space man.gif"])
            uploads = [c for c in calls if c[0] == "POST"]
            self.assertEqual(len(uploads), 2)
            self.assertEqual(uploads[0][1], "/photo/upload")
            self.assertIn(b'name="file"; filename="tokentv.jpg"', uploads[0][2])
            self.assertIn(b"\r\n\r\nEXACT-JPEG\r\n", uploads[0][2])
            self.assertIn(b'filename="tokentv.gif"\r\nContent-Type: image/gif', uploads[1][2])
            paths = [c[1] for c in calls]
            self.assertIn("/theme/toggle?id=2&state=1", paths)
            self.assertIn("/theme/toggle?id=0&state=0", paths)
            self.assertIn("/theme/toggle?id=0&state=1", paths)
            self.assertIn("/photo/toggle?name=original.jpg&state=1", paths)
            self.assertIn("/photo/toggle?name=space%20man.gif&state=0", paths)
            self.assertIn("/photo/toggle?name=space%20man.gif&state=1", paths)
            self.assertFalse(any("delete" in p or "restart" in p or "update" in p for p in paths))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


@contextmanager
def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def answering(status, body):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)
    return Handler


def ultra_clock(state, calls):
    """SmallTV-Ultra stock web API as recorded by the contributor and adrienbrault/geekmagic-hacs."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return
        def reply(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            calls.append(("GET", self.path))
            url = urlparse(self.path)
            if url.path == "/v.json":
                return self.reply({"m": "SmallTV-Ultra", "v": "Ultra-V9.0.54"})
            if url.path == "/app.json":
                if state["theme"] is None:  # a new unit has no /app.json until its theme is first set
                    return self.reply({}, 404)
                return self.reply({"theme": state["theme"]})
            if url.path == "/album.json":
                return self.reply({"autoplay": state["autoplay"], "i_i": state["i_i"]})
            if url.path == "/set":
                for key, values in parse_qs(url.query).items():
                    state[key] = values[0] if key == "img" else int(values[0])
                return self.reply("OK")
            self.reply({}, 404)
        def do_POST(self):
            calls.append(("POST", self.path))
            body = self.rfile.read(int(self.headers["Content-Length"]))
            form = email.message_from_bytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body,
                                            policy=email.policy.HTTP)
            for part in form.iter_parts():
                state["parts"].append((part.get_param("name", header="content-disposition"), part.get_filename(),
                                       part.get_content_type(), part.get_payload(decode=True)))
                if self.path == "/doUpload?dir=/image/" and part.get_param("name", header="content-disposition") == "file":
                    state["files"][part.get_filename()] = part.get_payload(decode=True)
            self.reply("OK")
    return Handler


SD_PRO_BACKUP = {"themes": [{"id": 0, "enabled": True}, {"id": 2, "enabled": False}], "theme_interval": 10,
                 "files": [{"name": "original.jpg", "enabled": True}], "photo_interval": 10}
ULTRA_BACKUP = {"model": "ultra", "theme": 1, "autoplay": 1, "i_i": 5}


class UltraTests(unittest.TestCase):
    def setUp(self):
        self.state = {"theme": 1, "autoplay": 1, "i_i": 5, "img": "/image/cat.jpg", "files": {"cat.jpg": b"CAT"}, "parts": []}
        self.calls = []

    def test_only_a_smalltv_ultra_answer_selects_the_ultra_api(self):
        answers = [(200, b'{"m": "SmallTV-Ultra", "v": "Ultra-V9.0.54"}', UltraDisplay),
                   (404, b"", PhotoDisplay), (200, b'{"m": null}', PhotoDisplay), (200, b'{"m": 5}', PhotoDisplay),
                   (200, b'["SmallTV-Ultra"]', PhotoDisplay), (200, b"<html></html>", PhotoDisplay),
                   (200, b"\xff", PhotoDisplay), (200, b'{"m": "SmallTV-PRO"}', PhotoDisplay),
                   (200, b'{"m": "NotUltraAtAll"}', PhotoDisplay)]
        for status, body, expected in answers:
            with self.subTest(body=body), serve(answering(status, body)) as url:
                self.assertIs(type(open_display(url)), expected)

    def test_unreachable_or_broken_clock_keeps_the_sd_pro_path(self):
        class Garbled(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return
            def do_GET(self):
                self.wfile.write(b"not an http status line\r\n\r\n")
        with serve(Garbled) as url:
            self.assertIs(type(open_display(url)), PhotoDisplay)
        with socket.socket() as closed:
            closed.bind(("127.0.0.1", 0))
            port = closed.getsockname()[1]
        self.assertIs(type(open_display(f"http://127.0.0.1:{port}")), PhotoDisplay)

    def test_ultra_contract_backup_upload_show_and_restore(self):
        with serve(ultra_clock(self.state, self.calls)) as url:
            display = open_display(url)
            self.assertIsInstance(display, UltraDisplay)
            self.assertEqual(self.calls, [("GET", "/v.json")])
            original = display.capture()
            self.assertEqual(original, ULTRA_BACKUP)
            self.assertEqual(self.calls[1:], [("GET", "/app.json"), ("GET", "/album.json")])

            start = len(self.calls)
            display.upload("tokentv.jpg", b"EXACT-JPEG")
            display.upload("tokentv.gif", b"GIF89a-EXACT")
            for name, image in (("other.jpg", b"JPEG"), ("tokentv.jpg", b""), ("tokentv.jpg", b"x" * 60001)):
                with self.assertRaises(ValueError):
                    display.upload(name, image)
            self.assertEqual(self.calls[start:], [("POST", "/doUpload?dir=/image/")] * 2)
            self.assertEqual(self.state["parts"], [("file", "tokentv.jpg", "image/jpeg", b"EXACT-JPEG"),
                                                   ("file", "tokentv.gif", "image/gif", b"GIF89a-EXACT")])

            # Stop the slideshow, switch to the Photo Album theme, then point it at our image.
            start = len(self.calls)
            display.activate(original)
            self.assertEqual(self.calls[start:], [("GET", "/app.json"), ("GET", "/album.json"), ("GET", "/set?i_i=5&autoplay=0"),
                                                  ("GET", "/set?theme=3"), ("GET", "/set?img=%2Fimage%2Ftokentv.jpg")])
            self.assertEqual((self.state["theme"], self.state["autoplay"], self.state["img"]), (3, 0, "/image/tokentv.jpg"))
            # Already in the album with autoplay off: only the image changes.
            start = len(self.calls)
            display.activate(original, "tokentv.gif")
            self.assertEqual(self.calls[start:], [("GET", "/app.json"), ("GET", "/album.json"), ("GET", "/set?img=%2Fimage%2Ftokentv.gif")])

            start = len(self.calls)
            display.restore(original)
            self.assertEqual(self.calls[start:], [("GET", "/set?i_i=5&autoplay=1"), ("GET", "/set?theme=1")])
            self.assertEqual((self.state["theme"], self.state["autoplay"], self.state["i_i"]), (1, 1, 5))
            self.assertEqual(self.state["files"], {"cat.jpg": b"CAT", "tokentv.jpg": b"EXACT-JPEG", "tokentv.gif": b"GIF89a-EXACT"})
            paths = [c[1] for c in self.calls]
            self.assertFalse(any(word in p for p in paths for word in ("delete", "clear", "reset", "reboot", "update")))

    def test_new_ultra_without_app_json_is_backed_up_shown_and_left_on_the_album(self):
        # Seen on a new Ultra-V9.0.54 unit: /app.json is 404 until the theme is changed once.
        self.state["theme"] = None
        with serve(ultra_clock(self.state, self.calls)) as url:
            display = open_display(url)
            original = display.capture()
            self.assertEqual(original, {"model": "ultra", "theme": None, "autoplay": 1, "i_i": 5})
            self.assertEqual(json.loads(json.dumps(original)), original)  # survives display-original.json

            start = len(self.calls)
            display.activate(original)
            self.assertEqual(self.calls[start:], [("GET", "/app.json"), ("GET", "/album.json"), ("GET", "/set?i_i=5&autoplay=0"),
                                                  ("GET", "/set?theme=3"), ("GET", "/set?img=%2Fimage%2Ftokentv.jpg")])
            self.assertEqual((self.state["theme"], self.state["img"]), (3, "/image/tokentv.jpg"))

            # No theme was saved, so restoring puts autoplay back and does not invent a theme.
            start = len(self.calls)
            display.restore(original)
            self.assertEqual(self.calls[start:], [("GET", "/set?i_i=5&autoplay=1")])

    def test_ultra_app_json_errors_other_than_404_still_fail(self):
        with serve(answering(500, b"")) as url:
            with self.assertRaises(HTTPError) as raised:
                UltraDisplay(url).capture()
        self.assertEqual(raised.exception.code, 500)

    def test_ultra_activate_does_not_copy_clock_values_into_the_query(self):
        self.state["i_i"] = "5&theme=0"
        with serve(ultra_clock(self.state, self.calls)) as url:
            with self.assertRaises(ValueError):
                UltraDisplay(url).activate(ULTRA_BACKUP)
        self.assertFalse(any(path.startswith("/set") for _, path in self.calls))
        self.assertEqual(self.state["theme"], 1)

    def test_backup_from_another_kind_of_clock_is_refused(self):
        sd_pro, ultra = PhotoDisplay("http://127.0.0.1:9"), UltraDisplay("http://127.0.0.1:9")
        sd_pro.check_backup(SD_PRO_BACKUP)
        ultra.check_backup(ULTRA_BACKUP)
        for display, backup in ((ultra, SD_PRO_BACKUP), (sd_pro, ULTRA_BACKUP), (ultra, ["not", "a", "backup"])):
            with self.subTest(display=type(display).__name__, backup=backup), self.assertRaises(BackupMismatch):
                display.check_backup(backup)

    def test_mismatched_backup_is_kept_and_the_clock_is_not_touched(self):
        with tempfile.TemporaryDirectory() as folder, serve(ultra_clock(self.state, self.calls)) as url:
            backup = Path(folder) / "display-original.json"
            backup.write_text(json.dumps(SD_PRO_BACKUP))
            saved = backup.read_bytes()
            display = open_display(url)
            # Live cycle: refuse before any capture, upload or new backup.
            with self.assertRaises(BackupMismatch):
                live.load_original(display, backup)
            # --restore-display: a clear message instead of a KeyError traceback.
            config = Path(folder) / "config.json"
            config.write_text(json.dumps({"device_url": url, "accounts": [
                {"key": "claude", "alias": "Claude", "provider": "claude", "email": "owner@example.com"}]}))
            with patch("sys.argv", ["token-tv", "--config", str(config), "--state-dir", folder, "--restore-display"]):
                with self.assertRaises(SystemExit) as stop:
                    live.main()
            self.assertIn("SD_PRO", str(stop.exception.code))
            self.assertIn("Nothing was changed on the clock", str(stop.exception.code))
            self.assertEqual(backup.read_bytes(), saved)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["config.json", "display-original.json"])
            self.assertEqual(self.calls, [("GET", "/v.json")] * 2)
            self.assertEqual(self.state["theme"], 1)

    def test_backup_is_saved_once_and_reused_for_the_same_kind_of_clock(self):
        with tempfile.TemporaryDirectory() as folder, serve(ultra_clock(self.state, self.calls)) as url:
            backup = Path(folder) / "display-original.json"
            display = open_display(url)
            self.assertEqual(live.load_original(display, backup), ULTRA_BACKUP)
            self.assertEqual(json.loads(backup.read_text()), ULTRA_BACKUP)
            self.state["theme"] = 3
            start = len(self.calls)
            self.assertEqual(live.load_original(display, backup), ULTRA_BACKUP)
            self.assertEqual(self.calls[start:], [])
            # SD_PRO backups have no model key and keep working unchanged.
            backup.write_text(json.dumps(SD_PRO_BACKUP))
            self.assertEqual(live.load_original(PhotoDisplay(url), backup), SD_PRO_BACKUP)
            self.assertEqual(self.calls[start:], [])


if __name__ == "__main__":
    unittest.main()
