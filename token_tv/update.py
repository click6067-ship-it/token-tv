"""Keeping TokenTV current. The dashboard's 'new version' note comes from one look at PyPI's JSON a day, kept in
the state folder (`"update_check": false` in the config turns it off): nothing is sent but that GET, no account,
usage or telemetry. `token-tv update` (cli.py) puts the newest release in the background copy's place."""
import json
import re
import threading
import time
from http.client import HTTPException
from pathlib import Path
from urllib.request import Request, urlopen

from token_tv import __version__
from token_tv.private_files import private_dir, write_private

PYPI = 'https://pypi.org/pypi/token-tv/json'
CHECK_SECONDS = 86400  # PyPI is asked at most this often
CACHE = 'update-check.json'


def parts(version):
    """(0, 4, 0) for '0.4.0'; None for anything else, a pre-release included."""
    return tuple(int(p) for p in version.split('.')) if isinstance(version, str) and re.fullmatch(r'\d+(\.\d+)*', version) else None


def newer(version, than):
    mine, theirs = parts(than), parts(version)
    return bool(mine and theirs and theirs > mine)


def newest(timeout=10):
    """The newest release on PyPI, or None when its answer says none."""
    with urlopen(Request(PYPI, headers={'Accept': 'application/json'}), timeout=timeout) as response:
        data = json.load(response)
    version = (data.get('info') or {}).get('version') if isinstance(data, dict) else None
    return version if parts(version) else None


def check(state_dir, current=__version__, now=None, fetch=newest):
    """The newest release when it is newer than `current`, else None. PyPI is asked once a day at most: its answer,
    or that it could not be read, is kept in the state folder until then."""
    path, now = Path(state_dir) / CACHE, time.time() if now is None else now
    try:
        kept = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        kept = None
    if not (isinstance(kept, dict) and isinstance(kept.get('checked_at'), (int, float))
            and 0 <= now - kept['checked_at'] < CHECK_SECONDS):
        try:
            latest = fetch()
        except (OSError, ValueError, HTTPException):
            latest = None  # offline, or PyPI answered oddly: no note, and no asking again before tomorrow
        kept = {'checked_at': int(now), 'latest': latest}
        try:
            private_dir(path.parent, close=False)  # a state folder made here is this user's alone, like the rest
            write_private(path, json.dumps(kept))
        except OSError:
            pass
    latest = kept.get('latest')
    return latest if newer(latest, current) else None


class UpdateNotice:
    """What the dashboard says about a newer release: nothing, or {'current', 'latest', 'command'}."""
    def __init__(self, state_dir, enabled=True, fetch=newest):
        self.state_dir, self.enabled, self.fetch = state_dir, enabled, fetch
        self.latest = None
        self.lock = threading.Lock()

    def refresh(self, now=None):
        if not self.enabled:
            return
        latest = check(self.state_dir, __version__, now, self.fetch)
        with self.lock:
            self.latest = latest

    def payload(self):
        with self.lock:
            latest = self.latest
        if not latest:
            return None
        from token_tv.cli import cmd
        return {'current': __version__, 'latest': latest, 'command': cmd('update')}

    def watch(self, stopping, every=3600):
        """Look again every hour (PyPI itself once a day), until `stopping` is set; for a background thread."""
        while not stopping.is_set():
            try:
                self.refresh()
            except Exception:  # a note is never worth a stopped TokenTV
                pass
            stopping.wait(every)
