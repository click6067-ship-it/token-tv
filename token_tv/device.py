"""Confirmed SD_PRO photo API, plus the SmallTV-Ultra image API. Never flash or delete existing photographs."""
import json
import time
import uuid
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


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
LIST_SECONDS = 600  # how long the clock's file list is trusted without reading it again
MODEL_NAMES = {"sdpro": "an SD_PRO", "ultra": "a SmallTV-Ultra"}


class BackupMismatch(ValueError):
    """The saved original state belongs to a different kind of clock."""


class PhotoDisplay:
    MODEL = "sdpro"
    SLOTS = SLOTS

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
        self.last_used = {}  # slot -> when it was last shown, so the one longest unused is written next

    def request(self, path, data=None, headers=None):
        with urlopen(Request(self.base_url + path, data=data, headers=headers or {}), timeout=20) as response:
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
        status, _ = self.request("/photo/upload", body,
                                 {"Content-Type": "multipart/form-data; boundary=" + boundary})
        return {"file": name, "status": status, "bytes": len(image)}

    def listed(self):
        """The album as the clock lists it now: its sizes, free space and enabled files."""
        _, raw = self.request("/photo/list")
        listing = json.loads(raw)
        self.enabled = {f["name"] for f in listing["files"] if f.get("enabled")}
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

        The clock plays and answers on one core, so every request holds the animation. Its list is therefore kept
        and read again only every LIST_SECONDS, after anything failed, and after a send to a clock low on space,
        where a send could be kept short of whole; between, the sizes and free space follow our own sends."""
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
        # A clock too full for a second slot: write over the one shown, as before slots.
        slot = (min(fits, key=lambda s: self.last_used.get(s, 0)) if fits
                else next((s for s in self.SLOTS if s in self.enabled), None)
                or (self.active if self.active in self.SLOTS else self.SLOTS[0]))
        self.held.pop(slot, None)
        try:
            receipts = [dict(self.upload(slot, image), sha256=digest)]
        except Exception:
            self.sizes = None  # what the slot has now is unknown: list it again before the next send
            raise
        if self.free - len(image) < ROOM:
            if self.listed().get(slot) != len(image):
                raise ValueError("The clock did not keep the whole picture")
        else:
            self.free -= len(image) - (self.sizes.get(slot) or 0)
            self.sizes[slot] = len(image)
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
        self.last_used[name] = time.monotonic()

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
        return display  # model checked once at start; an Ultra offline at launch falls back to SD_PRO until restart
    return UltraDisplay(base_url) if isinstance(model, str) and model.startswith("SmallTV-Ultra") else display
