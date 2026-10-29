import email
import email.policy
import hashlib
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


def sd_pro_clock(state, calls):
    """SD_PRO photo album that keeps what it is sent: names, bytes, the enabled flags and its free space."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return
        def reply(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            calls.append(("GET", self.path))
            url = urlparse(self.path)
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            if url.path == "/photo/list":
                files = [{"name": name, "size": len(data), "enabled": name in state["enabled"]} for name, data in state["files"].items()]
                return self.reply({"files": files, "interval": 10, "total": state["total"],
                                   "used": state["base"] + sum(len(data) for data in state["files"].values())})
            if url.path == "/theme/list":
                return self.reply({"interval": 10, "themes": [{"id": 0, "enabled": False}, {"id": 2, "enabled": True}]})
            if url.path == "/photo/toggle":
                (state["enabled"].add if query["state"] == "1" else state["enabled"].discard)(query["name"])
                if state.get("lose_answers"):  # done on the clock, but the answer never arrives
                    state["lose_answers"] -= 1
                    self.send_response(500)
                    self.end_headers()
                    return
                if state.get("cut_answers"):  # done, and the answer breaks off part-way
                    state["cut_answers"] -= 1
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b"{")
                    self.close_connection = True
                    return
            self.reply({"ok": True})
        def do_POST(self):
            calls.append(("POST", self.path))
            body = self.rfile.read(int(self.headers["Content-Length"]))
            form = email.message_from_bytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body,
                                            policy=email.policy.HTTP)
            for part in form.iter_parts():
                data = part.get_payload(decode=True)
                others = sum(len(d) for name, d in state["files"].items() if name != part.get_filename())
                room = state["total"] - state["base"] - others  # a full clock keeps what fits, and still says OK
                state["files"][part.get_filename()] = data[:len(data) // 2] if state.get("drop") else data[:room]
            self.reply({"ok": True})
    return Handler


class SlotTests(unittest.TestCase):
    """An animated face never writes over the GIF the clock is playing."""
    def setUp(self):
        self.state = {"files": {"cat.jpg": b"CAT", "tokentv.gif": b"GIF-OLD"}, "enabled": {"tokentv.gif"},
                      "total": 3000000, "base": 1500000}
        self.calls = []

    def show(self, display, image):
        return display.show(SD_PRO_BACKUP, "tokentv.gif", image, hashlib.sha256(image).hexdigest())

    def test_each_new_picture_goes_to_a_slot_not_playing_then_the_album_switches(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            playing = []
            for image in (b"GIF-A", b"GIF-B", b"GIF-C", b"GIF-D"):
                sent = self.show(display, image)
                self.assertEqual([r["bytes"] for r in sent], [len(image)])
                self.assertEqual(self.state["enabled"], {display.active})
                self.assertEqual(self.state["files"][display.active], image)
                playing.append(display.active)
            # The one shown at the start of a run is not written over either; the oldest unused slot is reused.
            self.assertEqual(playing, ["tokentv-b.gif", "tokentv.gif", "tokentv-c.gif", "tokentv-b.gif"])
            for before, after in zip(playing, playing[1:]):
                self.assertNotEqual(before, after)

    def test_a_picture_already_on_the_clock_is_a_switch_without_a_send(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            for image in (b"GIF-LOOK", b"GIF-STILL"):
                self.show(display, image)
            start = len(self.calls)
            self.assertEqual(self.show(display, b"GIF-LOOK"), [])
            self.assertEqual(self.state["files"]["tokentv-b.gif"], b"GIF-LOOK")
            self.assertEqual(self.state["enabled"], {"tokentv-b.gif"})
            self.assertEqual(self.calls[start:], [("GET", "/photo/toggle?name=tokentv-b.gif&state=1"),
                                                  ("GET", "/photo/toggle?name=tokentv.gif&state=0")])

    def test_a_picture_is_sent_ahead_and_the_clock_changes_only_at_the_switch(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-A")
            slot, sent = display.put("tokentv.gif", b"GIF-B", hashlib.sha256(b"GIF-B").hexdigest())
            self.assertEqual((slot, len(sent)), ("tokentv.gif", 1))
            self.assertEqual(self.state["enabled"], {"tokentv-b.gif"})  # still the last picture
            display.select(SD_PRO_BACKUP, slot)
            self.assertEqual(self.state["enabled"], {"tokentv.gif"})

    def test_a_clock_low_on_space_has_each_send_read_back_and_a_short_one_is_never_shown(self):
        self.state["total"] = self.state["base"] + 250000  # under the 300 kB kept free: sends are read back
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-GOOD")
            self.state["drop"] = True
            with self.assertRaises(ValueError):
                self.show(display, b"GIF-BROKEN")
            self.assertEqual(self.state["enabled"], {"tokentv-b.gif"})
            self.state["drop"] = False
            self.assertEqual(len(self.show(display, b"GIF-BROKEN")), 1)  # not taken as there: sent again
            self.assertEqual(self.state["files"][display.active], b"GIF-BROKEN")

    def test_with_room_to_spare_a_send_is_three_requests_and_the_list_is_read_once(self):
        # Every request holds the clock's animation: upload and two toggles, no read back.
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-A")
            for image in (b"GIF-B", b"GIF-C"):
                start = len(self.calls)
                self.show(display, image)
                self.assertEqual([c[0] for c in self.calls[start:]], ["POST", "GET", "GET"])
            self.assertEqual(sum(c[1] == "/photo/list" for c in self.calls), 2)  # the first send, and its activation

    def test_after_a_lost_answer_the_clock_is_listed_and_activated_again_never_written_while_enabled(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-A")
            self.state["lose_answers"] = 1
            with self.assertRaises(OSError):
                self.show(display, b"GIF-B")  # the new one is on, the old one still on: two enabled
            self.assertEqual(len(self.state["enabled"]), 1 + 1)
            enabled = set(self.state["enabled"])
            before = {name: self.state["files"][name] for name in enabled}
            self.show(display, b"GIF-C")
            self.assertEqual({name: self.state["files"][name] for name in enabled}, before)  # neither written
            self.assertEqual(self.state["enabled"], {display.active})
            self.assertEqual(self.state["files"][display.active], b"GIF-C")

    def test_an_answer_cut_short_is_a_failure_too(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-A")
            self.state["cut_answers"] = 1
            with self.assertRaises(Exception):
                self.show(display, b"GIF-B")
            enabled = set(self.state["enabled"])
            before = {name: self.state["files"][name] for name in enabled}
            self.show(display, b"GIF-C")
            self.assertEqual({name: self.state["files"][name] for name in enabled - {display.active}},
                             {name: before[name] for name in enabled - {display.active}})
            self.assertEqual(self.state["enabled"], {display.active})
            self.assertNotIn(display.active, enabled)  # written to a slot that was off

    def test_two_of_ours_on_and_little_room_one_is_turned_off_before_a_write(self):
        self.state["total"] = self.state["base"] + 250000  # no third slot
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-A")
            self.state["lose_answers"] = 1
            with self.assertRaises(OSError):
                self.show(display, b"GIF-B")
            self.assertEqual(self.state["enabled"], {"tokentv.gif", "tokentv-b.gif"})
            on = dict(self.state["files"])
            self.show(display, b"GIF-C")
            self.assertEqual(self.state["enabled"], {display.active})
            self.assertEqual(self.state["files"][display.active], b"GIF-C")
            kept = ({"tokentv.gif", "tokentv-b.gif"} - {display.active}).pop()
            self.assertEqual(self.state["files"][kept], on[kept])

    def test_a_photo_the_owner_turned_on_is_turned_off_at_the_next_change(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            for image in (b"GIF-A", b"GIF-B"):
                self.show(display, image)
            self.state["enabled"].add("cat.jpg")
            display.listed_at -= 601
            self.show(display, b"GIF-C")
            self.assertEqual(self.state["enabled"], {display.active})

    def test_the_list_is_read_again_after_ten_minutes(self):
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            for image in (b"GIF-A", b"GIF-B"):
                self.show(display, image)
            self.state["files"]["tokentv-b.gif"] = b""  # emptied on the clock's own page
            display.listed_at -= 601
            self.assertEqual(len(self.show(display, b"GIF-A")), 1)  # seen as gone: sent again, not switched to

    def test_a_restart_on_a_full_clock_writes_over_the_gif_that_is_on(self):
        self.state["files"].update({"tokentv.gif": b"G" * 10, "tokentv-b.gif": b"B" * 1000})
        self.state["enabled"] = {"tokentv-b.gif"}
        self.state["total"] = self.state["base"] + 3 + 10 + 1000 + 20000
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            self.show(display, b"GIF-NEW")
            self.assertEqual(self.state["files"]["tokentv-b.gif"], b"GIF-NEW")
            self.assertEqual(self.state["enabled"], {"tokentv-b.gif"})

    def test_the_third_slot_is_written_only_while_room_is_kept(self):
        self.state["files"].update({"tokentv-b.gif": b"B", "tokentv-c.gif": b"C"})
        self.state["total"] = self.state["base"] + 250000
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            for image in (b"GIF-1", b"GIF-2", b"GIF-3", b"GIF-4"):
                self.show(display, image)
            self.assertEqual(self.state["files"]["tokentv-c.gif"], b"C")

    def test_a_third_slot_only_while_the_owner_keeps_room_and_a_full_clock_still_updates(self):
        self.state["total"] = self.state["base"] + 200000
        with serve(sd_pro_clock(self.state, self.calls)) as url:
            display = PhotoDisplay(url)
            for image in (b"GIF-A", b"GIF-B", b"GIF-C"):
                self.show(display, image)
            self.assertNotIn("tokentv-c.gif", self.state["files"])  # two slots, taken in turn
            self.assertEqual((self.state["files"]["tokentv.gif"], self.state["files"]["tokentv-b.gif"]), (b"GIF-B", b"GIF-C"))
            # The owner's new photos fill the clock: the send that no longer fits is caught and not shown, and the
            # next one, seeing no room for a second copy, writes over the one shown, as before slots.
            self.state["files"]["owner.jpg"] = b"x" * (200000 - 10)
            with self.assertRaises(ValueError):
                self.show(display, b"GIF-D")
            self.assertEqual(self.state["enabled"], {"tokentv-b.gif"})
            self.show(display, b"GIF-D")
            self.assertEqual(self.state["files"]["tokentv-b.gif"], b"GIF-D")
            self.assertEqual(self.state["enabled"], {"tokentv-b.gif"})


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
