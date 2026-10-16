"""Confirmed SD_PRO photo API, plus the SmallTV-Ultra image API. Never flash or delete existing photographs."""
import json
import uuid
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


FILES = ("tokentv.jpg", "tokentv.gif")
# The album page accepts GIFs up to 240×240; keep both well under the free space.
LIMITS = {"tokentv.jpg": (60000, "image/jpeg"), "tokentv.gif": (400000, "image/gif")}
LEGACY_FILES = ("tokentv-c.jpg", "tokentv-m.jpg")
MODEL_NAMES = {"sdpro": "an SD_PRO", "ultra": "a SmallTV-Ultra"}


class BackupMismatch(ValueError):
    """The saved original state belongs to a different kind of clock."""


class PhotoDisplay:
    MODEL = "sdpro"

    def __init__(self, base_url):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.path not in ("", "/"):
            raise ValueError("A plain local display URL is required")
        self.base_url = base_url.rstrip("/")

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
        for name in FILES + LEGACY_FILES:
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
