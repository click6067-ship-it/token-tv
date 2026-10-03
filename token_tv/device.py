"""Confirmed SD_PRO photo API. Never flash or delete existing photographs."""
import json
import uuid
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


FILES = ("tokentv.jpg", "tokentv.gif")
# The album page accepts GIFs up to 240×240; keep both well under the free space.
LIMITS = {"tokentv.jpg": (60000, "image/jpeg"), "tokentv.gif": (400000, "image/gif")}
LEGACY_FILES = ("tokentv-c.jpg", "tokentv-m.jpg")


class PhotoDisplay:
    def __init__(self, base_url):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.path not in ("", "/"):
            raise ValueError("A plain local display URL is required")
        self.base_url = base_url.rstrip("/")

    def request(self, path, data=None, headers=None):
        with urlopen(Request(self.base_url + path, data=data, headers=headers or {}), timeout=20) as response:
            body = response.read()
            return response.status, body

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
