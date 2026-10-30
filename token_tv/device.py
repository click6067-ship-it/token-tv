"""Confirmed SD_PRO photo API, plus the SmallTV-Ultra image API. Never flash or delete existing photographs."""
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen


FILES = ("tokentv.jpg", "tokentv.gif")
# An animated face goes to one of these in turn, never to the one playing: a GIF written over while the clock reads
# it can leave the clock stuck on a broken file. A third keeps a picture that comes back (a resting pet's look round
# and its still minutes) on the clock, so coming back is a switch, not a send.
SLOTS = ("tokentv.gif", "tokentv-b.gif", "tokentv-c.gif")
# The album page accepts GIFs up to 240×240; keep both well under the free space.
LIMITS = {"tokentv.jpg": (60000, "image/jpeg"), **{name: (400000, "image/gif") for name in SLOTS}}
LEGACY_FILES = ("tokentv-c.jpg", "tokentv-m.jpg")
ROOM = 300000  # bytes of the clock's space a third slot leaves free, for the owner's own photos
MARGIN = 30000  # and any slot, for the clock's own files
LIST_SECONDS = 300  # how long the clock's file list is trusted without reading it again
MODEL_NAMES = {"sdpro": "an SD_PRO", "ultra": "a SmallTV-Ultra"}


class BackupMismatch(ValueError):
    """The saved original state belongs to a different kind of clock."""


class NotAClock(ValueError):
    """Something answers at the clock's address, but not as a clock does (a printer or router took the address)."""


class ClockFull(ValueError):
    """No slot but the one playing has room for the picture: nothing was sent, the clock keeps what it shows."""
    def __init__(self, needed, free):
        super().__init__(f"The clock is full: {max(1, (needed - free) // 1000)} kB more needed")
        self.needed, self.free = needed, free


class PhotoDisplay:
    MODEL = "sdpro"
    SLOTS = SLOTS
    guessed = False  # True when nothing answered to say which model this is

    def __init__(self, base_url):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.path not in ("", "/"):
            raise ValueError("A plain local display URL is required")
        self.base_url = base_url.rstrip("/")
        self.active = None  # the file this clock was last set to show
        self.enabled = set()  # the album's enabled files, likewise
        self.sizes = None  # file -> bytes on the clock, as last listed and since sent
        self.free = 0  # bytes free on the clock, likewise
        self.listed_at = 0  # when the list was last read
        self.held = {}  # slot -> (sha256, bytes) of the GIF put there and seen to arrive whole
        self.last_used = {}  # slot -> the turn it was last shown in, so the one longest unused is written next
        self.turns = 0  # a count, not a clock: Windows' clock can give two quick switches the same time

    def request(self, path, data=None, headers=None):
        # Straight to the clock: it is on this network, so a proxy set for the internet must not stand between.
        with DIRECT.open(Request(self.base_url + path, data=data, headers=headers or {}), timeout=20) as response:
            body = response.read()
            return response.status, body

    def check_backup(self, original):
        # SD_PRO backups predate the model key, so a missing key means SD_PRO.
        saved = original.get("model", "sdpro") if isinstance(original, dict) else None
        if saved != self.MODEL:
            raise BackupMismatch(f"The saved display backup is for {MODEL_NAMES.get(saved, 'an unknown')} clock, "
                                 f"but this clock was detected as {MODEL_NAMES[self.MODEL]}.")

    def capture(self):
        _, raw = self.request("/theme/list")
        themes = json.loads(raw)
        _, raw = self.request("/photo/list")
        photos = json.loads(raw)
        if not any(t["id"] == 2 for t in themes["themes"]):
            raise ValueError("The confirmed photo theme is missing")
        return {"themes": themes["themes"], "theme_interval": themes["interval"],
                "files": [{"name": f["name"], "enabled": f["enabled"]} for f in photos["files"]],
                "photo_interval": photos["interval"]}

    def upload(self, name, image):
        limit, mime = LIMITS.get(name, (0, ""))
        if not image or len(image) > limit:
            raise ValueError("Unexpected display image")
        boundary = "TokenTV" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + image + f"\r\n--{boundary}--\r\n".encode()
        status, answer = self.request("/photo/upload", body,
                                      {"Content-Type": "multipart/form-data; boundary=" + boundary})
        if b"success" not in answer.lower():  # the SD_PRO says "Upload Success"; a router or printer says something else
            raise NotAClock("The address took the upload, but not as a clock")
        return {"file": name, "status": status, "bytes": len(image)}

    def listed(self):
        """The album as the clock lists it now: its sizes, free space and enabled files."""
        _, raw = self.request("/photo/list")
        try:
            listing = json.loads(raw)
            files = listing["files"]
            self.enabled = {f["name"] for f in files if f.get("enabled")}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise NotAClock("The address answers, but not as a clock") from None
        self.sizes = {f["name"]: f.get("size") for f in listing["files"]}
        self.free = listing.get("total", float("inf")) - listing.get("used", 0)
        self.listed_at = time.monotonic()
        if self.enabled != {self.active}:  # not what we left on (a lost answer, the owner's own pick): activate in full
            self.active = None
        for slot, (_, size) in list(self.held.items()):
            if self.sizes.get(slot) != size:  # gone or changed on the clock since
                del self.held[slot]
        return self.sizes

    def put(self, name, image, digest):
        """Get a picture onto the clock without changing what it shows; returns the file that has it and receipts
        for what was sent. An animated face never goes to an enabled GIF: it goes to another slot, so a send cut
        short is never what the clock is playing.

        The clock plays and answers on one core, so every request holds the animation. Its list is therefore read
        before a send only when older than LIST_SECONDS or after anything failed, and after every send to check it
        arrived whole; between, the sizes and free space follow our own sends. A slot the owner turns on by hand in
        between is not seen until then (docs/hardware-compatibility.md)."""
        if name not in self.SLOTS:
            return name, [dict(self.upload(name, image), sha256=digest)]
        if self.sizes is None or time.monotonic() - self.listed_at > LIST_SECONDS:
            self.listed()
        slot = next((s for s, held in self.held.items() if held[0] == digest), None)
        if slot is not None:
            return slot, []
        ours = [s for s in self.SLOTS if s in self.enabled]
        for extra in ours[1:]:  # more than one of ours on, after a lost answer: keep one, so another is free to write
            self.toggle("photo", "name", extra, False)
            self.enabled.discard(extra)
        playing = self.enabled | {self.active}
        # The clock may keep the old copy until the new one is whole, so a slot needs room for all of it; the
        # third slot is used only while the owner's photos keep plenty of room.
        fits = [s for s in self.SLOTS if s not in playing
                and self.free - len(image) >= (MARGIN if s in self.SLOTS[:2] else ROOM)]
        if not fits:  # never the one playing: that is what can leave a clock frozen on a broken file
            if time.monotonic() - self.listed_at > 1:
                self.listed()  # make sure it is really full, not an old count
                return self.put(name, image, digest)
            raise ClockFull(len(image) + MARGIN, self.free)
        slot = min(fits, key=lambda s: self.last_used.get(s, 0))
        self.held.pop(slot, None)
        try:
            receipts = [dict(self.upload(slot, image), sha256=digest)]
        except Exception:
            self.sizes = None  # what the slot has now is unknown: list it again before the next send
            raise
        # Read back every send before it is switched on: the owner may have filled the clock since the last list,
        # and a GIF cut short can leave the clock frozen. One request, about a second of hold, at the loop's end.
        if self.listed().get(slot) != len(image):
            raise ValueError("The clock did not keep the whole picture")
        self.held[slot] = (digest, len(image))
        return slot, receipts

    def select(self, original, name):
        """Make `name` the one picture the clock shows: between slots two toggles, else the full activation. If
        anything fails, what the clock has enabled is unknown: the next change lists it and activates in full."""
        try:
            if self.active in self.SLOTS and name in self.SLOTS and self.active != name:
                self.toggle("photo", "name", name, True)  # the new one on before the old one off: never empty
                self.enabled.add(name)
                self.toggle("photo", "name", self.active, False)
                self.enabled.discard(self.active)
            elif self.active != name:
                self.activate(original, name)
                self.enabled = {name}
        except Exception:  # an answer lost or cut short included
            self.active, self.sizes = None, None
            raise
        self.active = name
        self.turns += 1
        self.last_used[name] = self.turns

    def show(self, original, name, image, digest):
        """Put a picture on the clock and make it the one shown; returns receipts for what was sent."""
        name, receipts = self.put(name, image, digest)
        self.select(original, name)
        return receipts

    def toggle(self, category, key, value, enabled):
        self.request("/" + category + "/toggle?" + urlencode({key: value, "state": int(enabled)}, quote_via=quote))

    def activate(self, original, name=FILES[0]):
        # Show only our current file, then select the photo theme; retain old files.
        current = self.capture()
        enabled = {f['name']: f['enabled'] for f in current['files']}
        if not enabled.get(name):
            self.toggle("photo", "name", name, True)
        for f in current['files']:
            if f["name"] != name and f['enabled']:
                self.toggle("photo", "name", f["name"], False)
        if current['photo_interval'] != 10:
            self.request("/photo/interval?val=10")
        if not any(t['id'] == 2 and t['enabled'] for t in current['themes']):
            self.toggle("theme", "id", 2, True)
        for t in current["themes"]:
            if t["id"] != 2 and t['enabled']:
                self.toggle("theme", "id", t["id"], False)

    def restore(self, original):
        for f in original["files"]:
            self.toggle("photo", "name", f["name"], f["enabled"])
        _, raw = self.request("/photo/list")
        present = {f["name"] for f in json.loads(raw)["files"]}
        for name in FILES + SLOTS + LEGACY_FILES:
            if name in present and not any(f["name"] == name for f in original["files"]):
                self.toggle("photo", "name", name, False)
        self.request("/photo/interval?val=" + str(original["photo_interval"]))
        self.request("/theme/interval?val=" + str(original["theme_interval"]))
        for enabled in (True, False):
            for t in original["themes"]:
                if t["enabled"] == enabled:
                    self.toggle("theme", "id", t["id"], enabled)


class UltraDisplay(PhotoDisplay):
    """SmallTV-Ultra (Ultra-V9) image API, read from the clock's own image.html and settings.html."""
    MODEL = "ultra"
    PHOTO_THEME = 3
    SLOTS = ()  # untried on this clock: one file, as before

    def capture(self):
        # A new clock has no /app.json (404) until its theme is first changed: there is no saved theme to restore.
        try:
            _, raw = self.request("/app.json")
            theme = json.loads(raw)["theme"]
        except HTTPError as error:
            if error.code != 404:
                raise
            theme = None
        _, raw = self.request("/album.json")
        album = json.loads(raw)
        return {"model": self.MODEL, "theme": theme, "autoplay": album["autoplay"], "i_i": album["i_i"]}

    def upload(self, name, image):
        limit, mime = LIMITS.get(name, (0, ""))
        if not image or len(image) > limit:
            raise ValueError("Unexpected display image")
        boundary = "TokenTV" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + image + f"\r\n--{boundary}--\r\n".encode()
        status, _ = self.request("/doUpload?dir=/image/", body,
                                 {"Content-Type": "multipart/form-data; boundary=" + boundary})
        return {"file": name, "status": status, "bytes": len(image)}

    def activate(self, original, name=FILES[0]):
        # Stop the slideshow so the user's own photos never rotate in, select the album theme, show ours.
        # The image is chosen after the theme, as geekmagic-hacs does on the same firmware.
        current = self.capture()
        if current["autoplay"]:
            self.request(f"/set?i_i={int(current['i_i'])}&autoplay=0")
        if current["theme"] != self.PHOTO_THEME:
            self.request(f"/set?theme={self.PHOTO_THEME}")
        self.request("/set?img=" + quote("/image/" + name, safe=""))

    def restore(self, original):
        # There is no known way to read the previously shown image, so only the album settings and theme return.
        self.request(f"/set?i_i={int(original['i_i'])}&autoplay={int(original['autoplay'])}")
        if original["theme"] is not None:
            self.request(f"/set?theme={int(original['theme'])}")


def open_display(base_url):
    display = PhotoDisplay(base_url)
    try:
        _, raw = display.request("/v.json")
        model = json.loads(raw).get("m")
    except (OSError, ValueError, AttributeError, HTTPException):
        display.guessed = True  # an Ultra that is off reads as an SD_PRO until it answers
        return display
    return UltraDisplay(base_url) if isinstance(model, str) and model.startswith("SmallTV-Ultra") else display


DIRECT = build_opener(ProxyHandler({}))


def clock_model(base_url, timeout=3):
    """'ultra' or 'sdpro' when a clock answers at `base_url`, else None. Read-only; an address where nothing answers
    is asked once."""
    opener = DIRECT  # a clock is on this network, never behind a proxy

    def get(path):
        with opener.open(Request(base_url + path), timeout=timeout) as response:
            return json.loads(response.read(65536))
    try:
        model = get("/v.json").get("m")
        if isinstance(model, str) and model.startswith("SmallTV"):
            return "ultra" if model.startswith("SmallTV-Ultra") else "sdpro"
    except HTTPError:
        pass  # something answers there: an SD_PRO has no /v.json
    except (OSError, ValueError, AttributeError, HTTPException):
        return None
    try:
        listing = get("/photo/list")
        if isinstance(listing.get("files"), list) and "total" in listing:
            return "sdpro"
    except (OSError, ValueError, AttributeError, HTTPException):
        pass
    return None


def local_addresses():
    """This computer's IPv4 addresses on every network it is on, as its own tools list them (a VPN may hold the
    default route while the clock sits on the Wi-Fi). Under WSL, Windows' addresses too."""
    found = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # sends nothing: only picks the interface the default route is on
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    tools = [["ipconfig"]] if sys.platform == "win32" else [["ip", "-4", "-o", "addr", "show"], ["ifconfig"]]
    try:
        if "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower():
            tools.append(["ipconfig.exe"])
    except OSError:
        pass
    for tool in tools:
        try:
            shown = subprocess.run(tool, capture_output=True, timeout=10).stdout.decode(errors="replace")
        except (OSError, subprocess.SubprocessError):
            continue
        pattern = r"IPv4[^\n]*?(\d+\.\d+\.\d+\.\d+)" if tool[0].startswith("ipconfig") else r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)"
        found += re.findall(pattern, shown)
    return found


def local_prefixes():
    """The first three parts of this computer's private addresses: a clock on the same Wi-Fi is beside one.
    Home networks first; at most four, so the search stays a few seconds."""
    prefixes = []
    for address in local_addresses():
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private and not (ip.is_loopback or ip.is_link_local or address.startswith("0.")):
            prefix = address.rsplit(".", 1)[0]
            if prefix not in prefixes:
                prefixes.append(prefix)
    return sorted(prefixes, key=lambda p: (not p.startswith("192.168."), not p.startswith("10.")))[:4]


def find_clocks(candidates=None, timeout=3):
    """The addresses of the clocks that answer on this computer's networks, so nobody has to read one off the clock.
    Every address of each local /24 is asked at once, read-only: a few seconds."""
    if candidates is None:
        candidates = [f"http://{prefix}.{n}" for prefix in local_prefixes() for n in range(1, 255)]
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=min(256, len(candidates))) as pool:
        models = list(pool.map(lambda url: clock_model(url, timeout), candidates))
    return [url for url, model in zip(candidates, models) if model]
