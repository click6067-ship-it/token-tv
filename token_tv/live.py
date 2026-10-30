"""Live account dashboard and stock-firmware image publisher."""
import argparse
import atexit
import dataclasses
import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from token_tv.device import FILES, BackupMismatch, open_display
from token_tv.catalog import payload as theme_payload
from token_tv.display import STYLES, overview_rows, render_page, watch_payload
from token_tv.arcade import LOOP_SECONDS, gif_seconds
from token_tv.events import EGG_SECONDS
from token_tv.lockbox import Lockbox

# After a unique one has played its prop stays in the scene for an hour; a legend's, till midnight.
TRACE = {'unique': lambda now: now + 3600,
         'legend': lambda now: time.mktime(time.localtime(now)[:3] + (23, 59, 59, 0, 0, -1))}
from token_tv.web_assets import HTML, ASSETS, asset
from token_tv.sources import load_config
from token_tv.state import MIN_FETCH_SECONDS, UsageStore


def until_loop_end(shown, now):
    """Seconds until the clock's GIF finishes a loop (it started at 'at' and loops every 'loop' seconds); 0 when
    nothing loops yet."""
    if shown.get('at') is None or not shown.get('loop'):
        return 0
    wait = shown['loop'] - (now - shown['at']) % shown['loop']
    return 0 if wait > shown['loop'] - .1 else wait  # right on time is no reason to wait a whole loop


LOST_POLLS = 3  # polls in a row the clock does not answer before TokenTV looks for it on the network again
RESCAN_SECONDS = 1800  # and then at most this often while it stays lost (a clock that is simply off)


def relocate(current, find=None):
    """The clock's new address when exactly one clock answers on this network and not at `current` (however that
    is spelt), else None. Each address gets 8 s: a clock busy playing can take that long to answer."""
    if find is None:
        from token_tv.device import find_clocks
        find = lambda: find_clocks(timeout=8)  # noqa: E731
    found = find()
    return found[0] if len(found) == 1 and not same_place(found[0], current) else None


def same_place(a, b):
    """Whether two clock addresses name the same host and port (localhost and 127.0.0.1, :80 or none)."""
    if not a or not b:
        return a == b
    places = []
    for url in (a, b):
        parsed = urlparse(url)
        try:
            host = socket.gethostbyname(parsed.hostname or '')
        except OSError:
            host = parsed.hostname
        places.append((host, parsed.port or 80))
    return places[0] == places[1]


def lost_search_due(polls, scanned, now):
    """Look for a clock that stopped answering after 3, 6, 12 and 24 polls, then every RESCAN_SECONDS."""
    return polls in (3, 6, 12, 24) or (polls > 24 and (scanned is None or now - scanned > RESCAN_SECONDS))


PROBLEMS = {  # what the dashboard says when the clock is not taking pictures
    'no_answer': 'The clock at {address} does not answer: is it on, and on this Wi-Fi?',
    'not_a_clock': 'Something else answers at {address} now; TokenTV is looking for the clock.',
    'clock_full': '{detail}. Delete a photo on its album page.',
    'short_copy': 'The clock kept only part of the last picture; TokenTV sends it again.',
    'other_clock': 'This clock is not the one TokenTV saved its settings from.',
    'error': 'The clock answered with an error ({detail}).',
    'other_tokentv': 'Another TokenTV on this computer drives the clock at {address}; this one leaves it alone.',
}


def problem_of(error):
    """The reason a picture did not reach the clock, for the dashboard: one of PROBLEMS."""
    from token_tv.device import ClockFull, NotAClock
    if isinstance(error, ClockFull):
        return 'clock_full'
    if isinstance(error, NotAClock):
        return 'not_a_clock'
    if isinstance(error, BackupMismatch):
        return 'other_clock'
    if isinstance(error, ValueError) and 'whole picture' in str(error):
        return 'short_copy'
    if isinstance(error, (json.JSONDecodeError, KeyError)):  # it answered, but not with a clock's lists
        return 'not_a_clock'
    if isinstance(error, HTTPError):
        return 'not_a_clock' if error.code == 404 else 'error'
    if isinstance(error, (OSError, HTTPException)):
        return 'no_answer'
    return 'error'


LOCKS = {}  # open lock files by path, held for the life of the process (a clock's until another replaces it)


def hold_lock(state_dir, name="live.lock"):
    """One TokenTV per config: two would both drive the clock and the same state files. False if one runs; OSError
    if the lock file cannot be made at all."""
    path = state_dir / name
    if path in LOCKS:  # this process holds it already
        return True
    state_dir.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    LOCKS[path] = handle
    return True


def clock_lock(url, strict=False):
    """Where the lock for the clock at `url` lives: the system's temporary folder (one per user, so another
    account's folder is never in the way), named after the address the name resolves to now. With `strict`, None
    when it does not resolve now: a passing name-lookup hiccup is no move."""
    parsed = urlparse(url)
    try:
        host = socket.gethostbyname(parsed.hostname or '')
    except OSError:
        if strict:
            return None
        host = parsed.hostname or ''
    key = hashlib.sha256(f"{host}:{parsed.port or 80}".encode()).hexdigest()[:16]
    user = f"-{os.getuid()}" if hasattr(os, "getuid") else ""  # Windows and macOS temp folders are per user already
    return Path(tempfile.gettempdir()) / f"token-tv{user}" / f"clock-{key}.lock"


def hold_clock(url):
    """One TokenTV per clock, whatever its config: two would write over each other's playing GIF. The lock's path
    (keep it: the name may point elsewhere later), or None if another TokenTV holds it. A lock that cannot be made
    at all (a full or read-only temporary folder) is no reason not to run."""
    path = clock_lock(url)
    try:
        return path if hold_lock(path.parent, path.name) else None
    except OSError as error:
        print(f"TokenTV could not lock the clock in {path.parent} ({error.strerror or error}); it runs without "
              f"that check.", flush=True)
        return path


def let_go(path):
    """Give up the clock lock at `path` (from hold_clock), for another TokenTV to drive that clock."""
    handle = LOCKS.pop(path, None)
    if handle:
        handle.close()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding='utf-8')
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def load_original(device, backup_path):
    """Return the clock's original state; save it first only if no backup exists yet."""
    if backup_path.is_file():
        original = json.loads(backup_path.read_text(encoding='utf-8'))
        device.check_backup(original)  # a backup from another kind of clock is kept and nothing is sent
        return original
    original = device.capture()
    write_json(backup_path, original)
    return original


def plain(url):
    """The clock's address as it speaks: plain http (0.3.1 saved an https:// one as it was typed)."""
    return 'http://' + url[8:] if isinstance(url, str) and url[:8].lower() == 'https://' else url


def start_command():
    from token_tv.cli import cmd
    return cmd("start")  # written the way this person runs TokenTV


def mismatch_message(error, backup_path):
    return (f"{error} Nothing was changed on the clock and {backup_path} was kept. If the clock was offline "
            "when TokenTV started, start TokenTV again. If you replaced the clock, put the old one back to "
            "restore it, or move that file away so TokenTV saves a new backup.")


class DisplayPreferences:
    def __init__(self, config_path, config):
        self.path = Path(config_path)
        self.config = dict(config)
        self.style = config.get('display_style', 'pixel')
        self.applied_style = None
        self.status = 'queued' if config.get('device_url') else 'preview_only'
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.trouble = None  # why pictures do not reach the clock now, for the dashboard

    def snapshot(self):
        with self.lock:
            return {'style': self.style, 'applied_style': self.applied_style,
                    'status': self.status, 'styles': list(STYLES), 'problem': self.trouble}

    def set_style(self, style):
        if style not in STYLES:
            raise ValueError('Unknown display style')
        with self.lock:
            updated = dict(load_config(self.path), display_style=style)
            write_json(self.path, updated)
            self.config = updated
            self.style = style
            self.status = 'queued' if self.config.get('device_url') else 'preview_only'
        self.changed.set()

    def set_device(self, url):
        """The clock moved to `url` (the router gave it a new address): kept in the config from now on."""
        with self.lock:
            updated = dict(load_config(self.path), device_url=url)
            write_json(self.path, updated)
            self.config = updated

    def problem(self, reason, address=None, detail=''):
        """What keeps pictures from the clock now (a PROBLEMS key), since when; None once one arrives again."""
        with self.lock:
            if reason is None:
                self.trouble = None
            elif not self.trouble or self.trouble['reason'] != reason:
                text = PROBLEMS[reason].format(address=urlparse(address or '').netloc or address, detail=detail)
                self.trouble = {'reason': reason, 'since': int(time.time()), 'text': text}

    def delivered(self, style, success):
        with self.lock:
            if success:
                self.applied_style = style
            self.status = ('queued' if style != self.style else 'ok' if success else 'error')


class QuietServer(ThreadingHTTPServer):
    """A browser that closes a page mid-answer is not an error worth a traceback in the terminal or the log."""
    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


LOCAL_NAMES = ('127.0.0.1', 'localhost', '::1')


def handler(store, preferences=None, locks=None, replays=None, wake=None, local_only=True):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def foreign_host(self):
            """True, having answered 403, when a dashboard on this computer only is asked by another name: a web
            page that renamed its own address to 127.0.0.1 (DNS rebinding) must not read or change anything."""
            if not local_only:
                return False
            host = urlparse('//' + (self.headers.get('Host') or '')).hostname or ''
            if host in LOCAL_NAMES:
                return False
            self.send_error(403, 'This dashboard answers only as 127.0.0.1 or localhost')
            return True

        def do_GET(self):
            if self.foreign_host():
                return
            url = urlparse(self.path)
            path = url.path
            snapshot = store.snapshot()
            display = preferences.snapshot() if preferences else {'style': 'pixel', 'status': 'preview_only', 'styles': list(STYLES)}
            snapshot['display'] = display
            content_type = "application/json; charset=utf-8"
            if path == "/":
                body = HTML.encode()
                content_type = "text/html; charset=utf-8"
            elif path in ASSETS:
                body, content_type = asset(path)
            elif path == "/snapshot":
                body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
            elif path.startswith("/snapshot/") and path[10:] in snapshot["accounts"]:
                body = json.dumps(snapshot["accounts"][path[10:]], ensure_ascii=False, separators=(",", ":")).encode()
            elif path in ("/frame/0.jpg", "/frame/1.jpg"):
                style = parse_qs(url.query).get('style', [display['style']])[0]
                if style not in STYLES:
                    self.send_error(400, 'Unknown display style')
                    return
                body = render_page(snapshot, int(path[7]), style)
                content_type = "image/gif" if body[:4] == b"GIF8" else "image/jpeg"
            elif path == '/themes':
                body = json.dumps(theme_payload()).encode()
            elif path == '/display':
                body = json.dumps(display).encode()
            elif path == "/watch.json":
                body = json.dumps(watch_payload(snapshot), ensure_ascii=False, separators=(",", ":")).encode()
            elif path == "/health":
                body = json.dumps({"status": "ok", "updated_at": snapshot["updated_at"]}).encode()
            elif path == "/collection":
                body = json.dumps(locks.collection() if locks else {'found': [], 'total': 0, 'hidden': 0}).encode()
            elif path.startswith("/collection/") and path.endswith(".gif") and locks:
                box = locks.replay(path[len("/collection/"):-len(".gif")])
                if not box or box.key not in snapshot["accounts"]:
                    self.send_error(404)
                    return
                body, content_type = render_page(snapshot, 0, 'arcade', egg=box), "image/gif"
            else:
                self.send_error(404)
                return
            self.reply(200, body, content_type)

        def reply(self, status, body, content_type='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.foreign_host():
                return
            if urlparse(self.path).path == '/collection/replay':
                self.replay_request()
                return
            if urlparse(self.path).path != '/display/style':
                self.send_error(404)
                return
            if preferences is None:
                self.send_error(409, 'Display settings unavailable')
                return
            origin = self.headers.get('Origin')
            if origin and (urlparse(origin).scheme not in ('http', 'https') or urlparse(origin).netloc != self.headers.get('Host')):
                self.send_error(403, 'Origin mismatch')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid JSON request')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {'style'} or data['style'] not in STYLES:
                    raise ValueError('Unknown display style')
                preferences.set_style(data['style'])
            except (ValueError, UnicodeError):
                self.send_error(400, 'Choose a supported display style')
                return
            except OSError:
                self.send_error(500, 'Could not save display choice')
                return
            self.reply(200, json.dumps(preferences.snapshot()).encode())

        def replay_request(self):
            """POST {"check": ...}: play a found one-off on the clock again."""
            origin = self.headers.get('Origin')
            if origin and (urlparse(origin).scheme not in ('http', 'https') or urlparse(origin).netloc != self.headers.get('Host')):
                self.send_error(403, 'Origin mismatch')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 256 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid JSON request')
                data = json.loads(self.rfile.read(length))
                check = data.get('check') if isinstance(data, dict) else None
                found = {item['check'] for item in locks.collection()['found']} if locks else set()
                if check not in found or replays is None:
                    raise ValueError('Not in the collection')
            except (ValueError, UnicodeError):
                self.send_error(400, 'Choose a scene you have found')
                return
            shown = preferences.snapshot() if preferences is not None else {}
            refusal = ('No clock connected' if shown.get('status') == 'preview_only' else
                       'The clock is not answering' if shown.get('status') == 'error' else
                       'Waiting for the clock' if preferences is not None and shown.get('applied_style') is None else
                       'Switch the clock to Arcade first' if preferences is not None and shown.get('style') != 'arcade' else '')
            if refusal:  # short: the dashboard puts it on the button as it is
                self.reply(409, json.dumps({'error': refusal}).encode())
                return
            replays.append(check)
            if wake:
                wake.set()
            self.reply(200, json.dumps({'queued': check}).encode())
    return Handler


def main():
    parser = argparse.ArgumentParser(description="TokenTV live account display")
    parser.add_argument("--config", help="Credential-free account metadata (default: the one `token-tv start` uses)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output", help="Write a normalized snapshot rather than stdout")
    parser.add_argument("--state-dir", default=".runtime")
    parser.add_argument("--restore-display", action="store_true")
    args = parser.parse_args()
    if args.config is None:
        from token_tv.cli import default_config
        args.config = default_config()
    config = load_config(args.config)
    config["device_url"] = plain(config.get("device_url"))
    if config.get("font"):
        os.environ["TOKEN_TV_FONT"] = config["font"]
    state_dir = Path(args.state_dir)
    held = {'path': None}  # the clock lock this run holds, as it was taken
    if not (args.once or args.restore_display):
        try:
            free = hold_lock(state_dir)
        except OSError as error:
            raise SystemExit(f"TokenTV cannot write its state folder {state_dir} ({error.strerror or error}).")
        if not free:
            try:
                where = (state_dir / "live.url").read_text(encoding='utf-8').strip()
            except OSError:
                where = ''
            raise SystemExit("TokenTV is already running with this config on this computer" +
                             (f": {where}" if where else "."))
        with socket.socket() as probe:  # the dashboard's port before anything touches the clock
            try:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((args.host, args.port))
            except OSError as error:
                raise SystemExit(f"Port {args.port} is in use on this computer ({error.strerror or error}). "
                                 f"Pass another with --port, or use {start_command()}, which picks a free one.")
        held['path'] = config.get("device_url") and hold_clock(config["device_url"])
        if config.get("device_url") and not held['path']:
            raise SystemExit(f"Another TokenTV already drives the clock at {config['device_url']} "
                             f"(with another config). One clock takes one TokenTV.")
        pid_file, url_file = state_dir / "live.pid", state_dir / "live.url"
        pid_file.write_text(str(os.getpid()), encoding='utf-8')  # how `autostart off` ends it on Windows; gone again at exit
        url_file.write_text(f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}", encoding='utf-8')
        atexit.register(lambda: (pid_file.unlink(missing_ok=True), url_file.unlink(missing_ok=True)))
    # The clock's model is asked in the background, so a clock that hangs never keeps the dashboard from opening.
    device = open_display(config["device_url"]) if config.get("device_url") and args.restore_display else None
    backup_path = state_dir / "display-original.json"
    if args.restore_display:
        if not device or not backup_path.is_file():
            parser.error("A display and its original state backup are required")
        original = json.loads(backup_path.read_text(encoding='utf-8'))
        try:
            device.check_backup(original)
        except BackupMismatch as error:
            raise SystemExit(mismatch_message(error, backup_path))
        device.restore(original)
        print("Original display selection restored.")
        return
    store = UsageStore(config["accounts"], min_fetch_seconds=MIN_FETCH_SECONDS)
    try:  # when each account last worked, from the last run
        store.restore(json.loads((state_dir / "snapshot.json").read_text(encoding='utf-8')))
    except (OSError, ValueError):
        pass
    preferences = DisplayPreferences(args.config, config)
    interval = max(60, int(config.get("poll_seconds", 60)))
    stopping = threading.Event()
    original = None
    last_upload = None

    locks = Lockbox(state_dir / "history.json")  # the hidden one-offs, and what they remember
    replays = []  # collection-book replays waiting for the clock
    seen_events, started = {}, time.time()  # events from before this start are not replayed
    pending = []  # events waiting their turn, one per poll, so two at once are both shown

    traces = {}  # account key -> (tier, until, prop): what a unique or legend leaves after it has played
    streaks = {}  # account key -> full periods in a row, at its last 'full'

    shown = {'at': None, 'loop': None}  # when the clock's GIF started, and its loop
    lost = {'polls': 0, 'scanned': None}  # polls in a row the clock did not answer, and when it was last looked for
    refused = {'url': None}  # a clock another TokenTV drives, said once

    def follow_clock():
        """The clock to drive: the address in the config, read again each minute (`start` finding the clock, or
        `start --device-url`, while this runs). With none there, no clock: one on this network may be someone else's."""
        nonlocal device, last_upload
        try:
            wanted = plain(load_config(args.config).get("device_url"))
        except (OSError, ValueError):
            return
        if refused['url'] and wanted != refused['url']:  # what was refused is no longer asked for
            refused['url'] = None
            preferences.problem(None)
        here = wanted and clock_lock(wanted, strict=True)
        elsewhere = bool(device and here and here != held['path'])  # the same name points at another address now
        if (device is None) != (not wanted) or (device and not same_place(wanted, device.base_url)) or elsewhere:
            path = wanted and hold_clock(wanted)
            if wanted and not path:
                if refused['url'] != wanted:
                    refused['url'] = wanted
                    print(f"Another TokenTV already drives the clock at {wanted}; this one leaves it alone.", flush=True)
                preferences.problem('other_tokentv', wanted)
                if device:  # the config names another clock now (or this name reaches the other's): let this one go
                    let_go(held['path'])
                    device, held['path'] = None, None
                    with preferences.lock:
                        preferences.status = "preview_only"
                return
            try:
                fresh = open_display(wanted) if wanted else None
            except ValueError as error:  # an address edited into the config by hand
                if path != held['path']:
                    let_go(path)
                if refused['url'] != wanted:
                    refused['url'] = wanted
                    print(f"TokenTV cannot use the clock address {wanted!r} in the config: {error}.", flush=True)
                return
            if held['path'] and held['path'] != path:
                let_go(held['path'])
            held['path'] = path or None
            device, last_upload, refused['url'] = fresh, None, None
            with preferences.lock:
                preferences.config["device_url"] = wanted
                preferences.status = "queued" if wanted else "preview_only"
                preferences.applied_style = None  # nothing on this clock from this run yet
                preferences.trouble = None
            print(f"TokenTV drives the clock at {wanted} now." if wanted else "TokenTV runs without a clock now.", flush=True)

    def cycle(refresh=True, egg=None):
        """Read (if `refresh`), draw and upload; True once the clock has the picture. A new picture for a looping
        face lands as the one on the clock finishes its loop, so the animation never jumps back mid-move; a
        one-off's first picture goes at once."""
        nonlocal original, last_upload, device
        delivered = False
        if refresh and not args.once:
            follow_clock()
        if refresh:
            store.refresh()
        snapshot = store.snapshot()
        for key, count in streaks.items():
            if key in snapshot['accounts']:
                snapshot['accounts'][key]['full_streak'] = count
        for key, (tier, until, prop) in list(traces.items()):
            if time.time() < until and key in snapshot['accounts']:
                snapshot['accounts'][key].update(trace=tier, trace_prop=prop)
            else:
                traces.pop(key, None)
        style = preferences.snapshot()['style']
        if not args.once and device:
            receipts = []
            phase = "backup"
            try:
                if original is None:
                    original = load_original(device, backup_path)
                phase = "upload"
                image = render_page(snapshot, 0, style, egg=egg)
                name = FILES[1] if image[:4] == b"GIF8" else FILES[0]
                digest = hashlib.sha256(image).hexdigest()
                if (name, digest) != last_upload:  # identical frames are not rewritten to flash
                    (state_dir / name).write_bytes(image)
                    # The clock plays and answers on one core: while it takes a picture the animation holds. So
                    # the send and the switch go together as the loop ends: the loop plays out whole, holds a
                    # moment, and the new one starts. An event or a box goes at once.
                    if not (egg is not None and getattr(egg, 'intro', True)):
                        stopping.wait(until_loop_end(shown, time.monotonic()))
                    started = time.monotonic()
                    try:
                        slot, sent = device.put(name, image, digest)
                        receipts.extend(sent)
                        phase = "activate"
                        device.select(original, slot)
                    except Exception:
                        if shown['at'] is not None:  # the old loop held while the clock tried: it ends that much later
                            shown['at'] += time.monotonic() - started
                        last_upload = None  # what the clock shows is unknown: the next picture goes in full, even this one
                        raise
                    shown['at'] = time.monotonic()
                    shown['loop'] = gif_seconds(image) if name == FILES[1] else None
                    last_upload = (name, digest)
                write_json(state_dir / "display-receipt.json", {"at": int(time.time()), "style": style, "uploads": receipts})
                preferences.delivered(style, True)
                # Pictures arrive; a clock asked for that another TokenTV drives is still worth saying.
                preferences.problem('other_tokentv' if refused['url'] else None, refused['url'])
                delivered = True
                lost['polls'] = 0
            except (OSError, ValueError, KeyError, HTTPException) as error:
                silent = swapped = False
                if isinstance(error, BackupMismatch):
                    again = open_display(device.base_url)  # guessed while the clock was off? ask it again
                    silent = again.guessed  # still off: nothing is known yet, so nothing to say about its backup
                    if type(again) is not type(device):
                        device, swapped = again, True
                        preferences.changed.set()  # the clock it really is: send to it now, not at the next poll
                    elif not silent:
                        print(mismatch_message(error, backup_path), flush=True)
                reason = 'no_answer' if silent else problem_of(error)
                if not swapped:
                    preferences.problem(reason, device.base_url, str(error) if reason in ('clock_full', 'error') else '')
                if reason in ('no_answer', 'not_a_clock'):  # no answer, or another device answers there now
                    lost['polls'] += 1
                    if lost_search_due(lost['polls'], lost['scanned'], time.monotonic()):
                        lost['scanned'] = time.monotonic()
                        again = open_display(device.base_url)  # the same address, maybe now an Ultra that was off
                        if type(again) is not type(device):
                            device = again
                        moved = relocate(device.base_url)
                        candidate = moved and open_display(moved)
                        try:
                            if candidate and original is not None:
                                candidate.check_backup(original)  # the same kind of clock, or it is not ours
                        except BackupMismatch:
                            candidate = None
                        path = candidate and hold_clock(moved)
                        if candidate and not path:  # another TokenTV drives the clock there
                            preferences.problem('other_tokentv', moved)
                            candidate = None
                        if candidate:
                            if held['path'] != path:
                                let_go(held['path'])
                            held['path'] = path
                            device = candidate
                            preferences.set_device(moved)
                            lost['polls'] = 0
                            preferences.changed.set()  # send to it now, not at the next poll
                            print(f"TokenTV found the clock at its new address {moved}.", flush=True)
                write_json(state_dir / "display-receipt.json", {"at": int(time.time()), "style": style, "status": "error", "phase": phase,
                           "reason": reason, "uploads": receipts, "http_status": getattr(error, "code", None)})
                preferences.delivered(style, False)
        snapshot['display'] = preferences.snapshot()
        write_json(state_dir / "snapshot.json", snapshot)
        if args.output:
            write_json(args.output, snapshot)
        return delivered

    if args.once:
        cycle()
        if not args.output:
            print(json.dumps(store.snapshot(), ensure_ascii=False, separators=(",", ":")))
        return

    def play(egg, mark=True):
        """One one-off on the clock: the event, then for a unique or legend its quiet aftermath, then the usual face."""
        try:
            if not cycle(False, egg):
                if mark and not isinstance(egg, str):
                    locks.forget()  # never shown, so not seen: it may come again
                return
            if mark and getattr(egg, 'tier', None) in TRACE and getattr(egg, 'prop', ''):  # in case it was missed
                traces[egg.key] = (egg.tier, TRACE[egg.tier](time.time()), egg.prop)
            # One loop of the event: the next picture is timed by cycle() to land as it ends, so its start never
            # plays again. A unique or legend then keeps its quiet loop for the rest of its time.
            seconds = getattr(egg, 'seconds', EGG_SECONDS)
            if getattr(egg, 'after', ()):
                cycle(False, dataclasses.replace(egg, frames=egg.after, after=(), intro=False))
                if stopping.wait(max(0, seconds - LOOP_SECONDS - (shown['loop'] or 0))):  # its last loop lands it
                    return
            cycle(False)
        except Exception:
            print("TokenTV easter egg skipped.", flush=True)

    def poll():
        nonlocal device
        try:
            device = open_display(config["device_url"]) if config.get("device_url") else None
        except ValueError:
            pass  # an address edited into the config by hand: follow_clock says what is wrong with it
        next_refresh = 0
        while not stopping.is_set():
            preferences.changed.clear()
            refresh = time.monotonic() >= next_refresh
            try:
                cycle(refresh)
            except Exception:
                # Never serialize exception text, which may include auth material.
                print("TokenTV poll failed; retained previous snapshot.", flush=True)
            arcade_on = preferences.snapshot()['style'] == 'arcade'
            if not arcade_on:
                pending.clear()  # another face now (even for a moment): what was waiting is not played later
            if refresh:
                next_refresh = time.monotonic() + interval
                if device:
                    # A one-off: a window that just reset or ran out, else a hidden box whose moment has
                    # come. It plays once on the clock, then the usual face comes back. Events are noted
                    # under any face, but played only on Arcade, never saved up for later.
                    snap = store.snapshot()
                    rows = [dict(row, key=key) for key, row in snap['accounts'].items()]
                    fresh = sorted((row['event_at'], row['key'], row['event']) for row in rows
                                   if row.get('event') and row.get('event_at', 0) > seen_events.get(row['key'], started))
                    for at, key, kind in fresh:
                        seen_events[key] = at
                        if not arcade_on:
                            continue
                        if kind == 'full':  # how many periods in a row now, for the scenes that count them
                            try:
                                locks.history.observe(snap, time.time())
                                streaks[key] = max(locks.history.full_streak(key, time.time()),
                                                   locks.history.five_hour_run(key))
                            except (OSError, ValueError):
                                streaks[key] = 1  # history out of reach: the event still plays
                        pending.append(f"{kind}@{key}")
                    try:
                        egg = (pending.pop(0) if pending else locks.pick(snap)) if arcade_on else None
                    except (OSError, ValueError):
                        egg = None
                        print("TokenTV hidden one-offs skipped.", flush=True)
                    if egg:
                        play(egg)
            while device and replays:  # asked for from the collection book: play it again now
                egg = locks.replay(replays.pop(0))
                if egg:
                    play(egg, mark=False)
            preferences.changed.wait(max(0, next_refresh - time.monotonic()))

    try:  # the dashboard's port first: if another program has it, stop before touching the clock
        local = args.host in LOCAL_NAMES  # bound to this computer only: answer only by its own names
        server = QuietServer((args.host, args.port), handler(store, preferences, locks, replays, preferences.changed, local))
    except OSError as error:
        raise SystemExit(f"Port {args.port} is in use on this computer ({error.strerror or error}). "
                         f"Pass another with --port, or use {start_command()}, which picks a free one.")
    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    try:
        with server:
            print(f"TokenTV live listening at http://{args.host}:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        preferences.changed.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
