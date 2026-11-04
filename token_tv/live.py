"""Live account dashboard and stock-firmware image publisher."""
import argparse
import atexit
import dataclasses
import hashlib
import io
import ipaddress
import json
import os
import re
import signal
import socket
import socketserver
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
from token_tv.arcade import LOOP_SECONDS, gif_pictures, gif_seconds
from token_tv.events import EGG_SECONDS
from token_tv.lockbox import Lockbox
from token_tv import moments

# After a unique one has played its prop stays in the scene for an hour; a legend's, till midnight.
TRACE = {'unique': lambda now: now + 3600,
         'legend': lambda now: time.mktime(time.localtime(now)[:3] + (23, 59, 59, 0, 0, -1))}
from token_tv.private_files import open_private, private_dir, write_private
from token_tv.update import UpdateNotice
from token_tv.web_assets import HTML, ASSETS, asset
from token_tv.sources import load_config
from token_tv.state import ACTIVE_SECONDS, MIN_FETCH_SECONDS, UsageStore

# An SD_PRO shows one picture about every 142 ms whatever the GIF's delays ask (two 120 fps films): a loop of N
# pictures lasts N times that there, so every loop's end on it is timed so (m1). `device_frame_ms` in the config
# sets it; other clocks play as long as the GIF says until one is measured. The GIF itself is never changed for it.
DEVICE_FRAME_MS = 142


def loop_seconds(image, device, frame_ms=DEVICE_FRAME_MS):
    """How long one loop of the GIF `image` lasts on the clock `device`."""
    if getattr(device, 'MODEL', None) == 'sdpro':
        return gif_pictures(image) * frame_ms / 1000
    return gif_seconds(image)


def until_loop_end(shown, now):
    """Seconds until the loop the clock's GIF plays at `now` ends (it started at 'at' and loops every 'loop' seconds,
    moments.loop_end): 0 right at a loop's end or when nothing loops yet. A picture that has only just gone on plays
    its first loop whole (a one-off's event, before what follows it)."""
    end = moments.loop_end(shown, now)
    return 0 if end is None else max(0.0, end - now)


LATE = .2  # seconds past a loop's end that a change due at it still goes (it was drawn as the loop ended)


def switch_at(shown, came, now):
    """When a picture of a change that came in at `came` goes on the clock (moments.CLOCK): as the loop the clock was
    playing then ends, or, once that end is more than LATE gone by `now` (the clock was being sent to, or the drawing
    took that long), as the next one ends; None when nothing loops yet (at once). Every switch is timed so: the
    agents' moments, usage redraws, a one-off, what follows it and the return."""
    due = moments.loop_end(shown, came)
    if due is not None and due + LATE < now:
        due = moments.loop_end(shown, now)
    return due


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


def health(snapshot):
    """Whether TokenTV runs and, account by account, whether its reading is fresh ('fresh', 'stale', 'unknown' or
    'none'): 'ok' only when every account's is; 'degraded' otherwise. States only, never readings or emails."""
    accounts = {}
    for key, row in snapshot['accounts'].items():
        status = row.get('status')
        accounts[key] = {name: row[name] for name in ('provider', 'status', 'error_code', 'last_success_at', 'retry_at')
                         if row.get(name) is not None}
        accounts[key]['freshness'] = (
            'fresh' if status in ('ok', 'quota_unavailable') else
            'unknown' if status == 'loading' or row.get('error_code') == 'freshness_unknown' else
            'stale' if status == 'stale' else 'none')
    every = all(a['freshness'] == 'fresh' for a in accounts.values())
    from token_tv import __version__
    return {'status': 'ok' if every else 'degraded', 'version': __version__, 'updated_at': snapshot['updated_at'],
            'accounts': accounts}


AUTH_CODES = ('auth_required', 'http_401', 'http_403')


def reason_of(row):
    """Why an account has no fresh reading, in a few words for its dashboard card, and what to do about it:
    {'text', 'at'} where the page writes '{at}' as the time `at` on the reader's clock (HH:MM). None when fresh."""
    from token_tv.cli import cmd
    status, code = row.get('status'), row.get('error_code') or row.get('status')
    if status in ('ok', 'quota_unavailable', 'loading', None):
        return None
    codexbar = row.get('source') == 'codexbar'
    retry, seen = row.get('retry_at'), row.get('last_success_at')
    if status == 'auth_required' or code in AUTH_CODES:
        text = ('CodexBar is signed out of this account: sign it in again in CodexBar' if codexbar else
                f'Login expired: run {cmd("connect")} --account {row["key"]}')
        return {'text': text, 'at': None}
    if status == 'identity_mismatch':
        return {'text': 'Signed in as another account than the config names', 'at': None}
    if code in ('http_429', 'rate_limited') or (code == 'http_503' and retry):
        return {'text': 'Rate limited until {at}', 'at': retry} if retry else {'text': 'Rate limited; trying again soon', 'at': None}
    if code == 'format_changed':
        return {'text': f'The service changed its reply: update TokenTV ({cmd("update")})', 'at': None}
    if code and code.startswith('unexpected:'):
        return {'text': f'Unexpected error ({code[11:]}); if it lasts, update TokenTV ({cmd("update")})', 'at': None}
    if code == 'codexbar_old':
        return {'text': 'CodexBar has not measured it since {at}', 'at': seen}
    if code == 'freshness_unknown':
        return {'text': 'CodexBar did not say when it measured this', 'at': None}
    if code == 'laptop_offline':
        return {'text': 'The linked computer last sent a reading at {at}', 'at': seen}
    if code == 'snapshot_old':
        return {'text': 'No new reading since {at}', 'at': seen} if seen else {'text': 'No new reading', 'at': None}
    if retry:
        return {'text': f'Could not read it ({code}); next try {{at}}', 'at': retry}
    return {'text': f'Could not read it ({code})', 'at': None}


LOCKS = {}  # open lock files by path, held for the life of the process (a clock's until another replaces it)


def hold_lock(state_dir, name="live.lock"):
    """One TokenTV per config: two would both drive the clock and the same state files. False if one runs; OSError
    if the lock file cannot be made at all."""
    path = state_dir / name
    if path in LOCKS:  # this process holds it already
        return True
    private_dir(state_dir, close=False)  # a new one is this user's alone; main() closes the state folder itself
    handle = open_private(path)
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
    private_dir(path.parent, close=False)  # made here, the folder is this user's alone; an existing one is left as is
    write_private(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


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


class Wake:
    """A threading.Event (set, clear, is_set, wait) that also keeps why it was set: 'moment' when an agent's
    moment set it, 'other' for anything else (a new face, a replay, a clock found again)."""
    def __init__(self):
        self.cond = threading.Condition()
        self.why = set()

    def set(self, why='other'):
        with self.cond:
            self.why.add(why)
            self.cond.notify_all()

    def clear(self):
        with self.cond:
            self.why.clear()

    def is_set(self):
        with self.cond:
            return bool(self.why)

    def wait(self, timeout=None):
        with self.cond:
            if not self.why:
                self.cond.wait(timeout)
            return bool(self.why)

    def take(self):
        """Why it was set since the last take, and clear it."""
        with self.cond:
            why, self.why = self.why, set()
            return why


class DisplayPreferences:
    def __init__(self, config_path, config):
        self.path = Path(config_path)
        self.config = dict(config)
        self.style = config.get('display_style', 'pixel')
        self.applied_style = None
        self.status = 'queued' if config.get('device_url') else 'preview_only'
        self.lock = threading.Lock()
        self.changed = Wake()
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


MARK_STRIP = 14  # px under a saved scene for TokenTV's mark, so it covers nothing of the scene or its gauges
STAGE = (0, 28, 240, 170)  # where a scene plays on the clock face, between the header and the readout


def slug(name):
    return '-'.join(''.join(c if c.isalnum() else ' ' for c in str(name).lower()).split()) or 'scene'


def keepsake(image):
    """A found scene's GIF to keep: the scene itself, every frame and its timing, with a strip below holding a small
    TokenTV mark in its right-hand corner. Only the scene: the header and readout show the reading of the moment it
    is saved, which a gauge drawn into the scene when it was found (Codex's garden at 80%) would contradict."""
    from PIL import Image, ImageDraw
    from token_tv import gif
    from token_tv.arcade import MUTED, PANEL
    from token_tv.display import pixel_text
    source = Image.open(io.BytesIO(image))
    frames, durations = [], []
    for n in range(getattr(source, 'n_frames', 1)):
        source.seek(n)
        scene = source.convert('RGB').crop(STAGE)
        frame = Image.new('RGB', (scene.width, scene.height + MARK_STRIP), PANEL)
        frame.paste(scene, (0, 0))
        pixel_text(ImageDraw.Draw(frame), (scene.width - 6, scene.height + 4), 'TokenTV', color=MUTED, align='right')
        frames.append(frame)
        durations.append(source.info.get('duration', 70))
    return gif.encode(gif.indexed(frames, 'Arcade'), durations)


LOCAL_NAMES = ('127.0.0.1', 'localhost', '::1')
HOST_FORM = re.compile(r'(\[::1\]|[A-Za-z0-9._-]+)(:[0-9]{1,5})?')  # a Host header: a name or address, a port
READ_SECONDS = 2  # the most a moment's request may take to arrive, line, headers and body: a slow sender is let go
PAGE_SECONDS = 10  # the same for the dashboard's other requests: a phone on poor Wi-Fi is still answered


def host_name(header):
    """The name a Host header asks by, in lower case without its port or a final dot; None when it is not one
    plain name or address. In brackets only IPv6's loopback, [::1]: anything else bracketed is no address of ours."""
    found = HOST_FORM.fullmatch((header or '').strip())
    return found.group(1).strip('[]').lower().rstrip('.') if found else None


def same_origin(origin, host):
    """Whether a browser's Origin is the page this server gave it: http(s), the very Host it asks by, no path. One
    that does not even parse (a bracket left open) is not."""
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and parsed.netloc == host and parsed.path in ('', '/')


class Late(Exception):
    """A request that did not arrive in its time (Deadline): its handler answers 408. Not an OSError, so nothing on
    its way takes it for a failure of TokenTV's own (a display choice that could not be saved)."""


class Deadline(io.RawIOBase):
    """A request's socket as its handler reads it: one deadline for the whole request (the handler's `deadline`),
    not a timeout per read, so a sender that drips a byte now and then is let go as surely as one that stops. It
    counts what arrived (`received`): a request cut off part-way is answered, a connection that sent nothing not."""
    def __init__(self, sock, handler):
        self.sock, self.handler = sock, handler

    def readable(self):
        return True

    def readinto(self, buffer):
        left = self.handler.deadline - time.monotonic()
        if left <= 0:
            raise Late('The request took too long to arrive')
        before = self.sock.gettimeout()
        self.sock.settimeout(left if before is None else min(before, left))
        try:
            got = self.sock.recv_into(buffer)
        except TimeoutError:
            raise Late('The request took too long to arrive') from None
        finally:
            self.sock.settimeout(before)  # what it writes back keeps its own time
        self.handler.received += got
        return got


def unique_keys(pairs):
    """json.loads' object_pairs_hook: a key given twice is no request of ours."""
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('A key given twice')
    return dict(pairs)


def moment_of(body):
    """The moment a request body names: exactly {"moment": <one of moments.MOMENTS>}, as strict UTF-8 JSON; else
    ValueError (UnicodeError is one)."""
    data = json.loads(body.decode('utf-8'), object_pairs_hook=unique_keys)
    if not isinstance(data, dict) or set(data) != {'moment'} or data['moment'] not in moments.MOMENTS:
        raise ValueError('Not a moment')
    return data['moment']


class MomentSocket(socketserver.ThreadingUnixStreamServer if hasattr(socketserver, 'ThreadingUnixStreamServer')
                   else object):
    """The moment endpoint again on a socket in TokenTV's own state folder (live.sock), for the Claude Code mod: a
    request over it meets no proxy and cannot be redirected anywhere else. Linux and macOS."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        return


def lan_names(bound=None):
    """The names and addresses this computer answers by on its networks, for a dashboard bound beyond it: its host
    names (and name.local), its addresses, and the address it was bound to. A web page that renamed itself to this
    computer's address (DNS rebinding) comes under its own name, which is none of these."""
    from token_tv.device import local_addresses
    names = {socket.gethostname(), socket.getfqdn()}
    names |= {name + '.local' for name in list(names) if name and '.' not in name}
    try:
        names |= {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)}
    except OSError:
        pass
    names |= set(local_addresses())
    if bound and bound not in ('0.0.0.0', '::'):
        names.add(bound)
    return {name.lower().rstrip('.') for name in names if name} | set(LOCAL_NAMES)


def handler(store, preferences=None, locks=None, replays=None, wake=None, local_only=True, names=None, notice=None,
            agents=None, moments_only=False, pace=None):
    # Answered by: this computer's own names; on the network (LAN mode) also its names and addresses there.
    hosts = set(LOCAL_NAMES) if local_only else {n.lower().rstrip('.') for n in (lan_names() if names is None else names)} | set(LOCAL_NAMES)

    class Handler(BaseHTTPRequestHandler):
        timeout = 2 if moments_only else None  # the moments' own socket: a sender that stalls anywhere is let go

        def setup(self):
            super().setup()
            self.rfile.close()  # read instead with one deadline per request, here and on the port
            self.rfile = io.BufferedReader(Deadline(self.connection, self))

        def handle_one_request(self):
            # One deadline for the whole request: a moment's READ_SECONDS (all the socket takes), the dashboard's
            # PAGE_SECONDS until its first line says it is a moment (parse_request). One that runs out is answered
            # 408, if anything of it came at all, and never as TokenTV's own failure.
            self.began, self.received = time.monotonic(), 0
            self.deadline = self.began + (READ_SECONDS if moments_only else PAGE_SECONDS)
            try:
                super().handle_one_request()
            except Late:
                self.close_connection = True
                if self.received:
                    self.late()

        def parse_request(self):
            words = self.raw_requestline.split()
            try:
                moment = len(words) > 1 and urlparse(words[1].decode('latin-1')).path == '/moment'
            except ValueError:
                moment = False
            if moment:  # its line, headers and body in READ_SECONDS from its start
                self.deadline = min(self.deadline, self.began + READ_SECONDS)
            return super().parse_request()

        def late(self):
            for name, value in (('requestline', ''), ('request_version', 'HTTP/1.0'), ('command', '')):
                if not hasattr(self, name):  # cut off in its very first line
                    setattr(self, name, value)
            try:
                self.send_error(408)
                self.wfile.flush()
            except OSError:
                pass

        def log_message(self, *args):
            return

        def send_error(self, code, message=None, explain=None):
            # The base class names what it could not take ("Unsupported method ('X')", a broken request line):
            # those get the bare reason, so nothing sent comes back. An unknown method is no 501 but a 405.
            if code == 501:
                code, message = 405, None
            super().send_error(code, message if getattr(self, 'answering', False) else None)

        def do_OPTIONS(self):  # a browser's preflight: no page elsewhere is let in
            self.answering = True
            if moments_only or not self.foreign_host():
                self.send_error(405)

        def foreign_host(self):
            """True, having answered 403, when the dashboard is asked by a name not this computer's: a web page
            that renamed its own address to this computer (DNS rebinding) must not read or change anything. The Host
            is read as the moments read it (host_name)."""
            if host_name(self.headers.get('Host')) in hosts:
                return False
            self.send_error(403, 'This dashboard answers only as 127.0.0.1 or localhost' if local_only else
                            "This dashboard answers only by this computer's names and addresses")
            return True

        def do_GET(self):
            self.answering = True
            if urlparse(self.path).path == '/moment':
                self.moment_check()
                return
            if moments_only or self.foreign_host():
                if moments_only:
                    self.send_error(404)
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
                for row in snapshot["accounts"].values():
                    row["reason"] = reason_of(row)
                snapshot["update"] = notice.payload() if notice else None  # a newer release, once a day from PyPI
                body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
            elif path.startswith("/snapshot/") and path[10:] in snapshot["accounts"]:
                body = json.dumps(snapshot["accounts"][path[10:]], ensure_ascii=False, separators=(",", ":")).encode()
            elif path in ("/frame/0.jpg", "/frame/1.jpg"):
                style = parse_qs(url.query).get('style', [display['style']])[0]
                if style not in STYLES:
                    self.send_error(400, 'Unknown display style')
                    return
                if agents is not None and style == 'arcade':  # the agents' moment, as the clock will show it
                    snapshot = moments.overlay(snapshot, *agents.wanted()[::2])
                if pace and pace.get('at') is not None:  # the pace ticks where the clock's picture has them
                    snapshot['pace_at'] = pace['at']
                body = render_page(snapshot, int(path[7]), style)
                content_type = "image/gif" if body[:4] == b"GIF8" else "image/jpeg"
            elif path == '/themes':
                body = json.dumps(theme_payload()).encode()
            elif path == '/display':
                body = json.dumps(display).encode()
            elif path == "/watch.json":
                body = json.dumps(watch_payload(snapshot), ensure_ascii=False, separators=(",", ":")).encode()
            elif path == "/health":
                body = json.dumps(health(snapshot)).encode()
            elif path == "/collection":
                body = json.dumps(locks.collection() if locks else {'found': [], 'total': 0, 'hidden': 0}).encode()
            elif path.startswith("/collection/") and path.endswith(".gif") and locks:
                box = locks.replay(path[len("/collection/"):-len(".gif")])  # only a scene already found
                if not box or box.key not in snapshot["accounts"]:
                    self.send_error(404)
                    return
                body, content_type = render_page(snapshot, 0, 'arcade', egg=box), "image/gif"
                if parse_qs(url.query).get('save') == ['1']:  # the collection book's Save: a keepsake to download
                    self.reply(200, keepsake(body), content_type,
                               {'Content-Disposition': f'attachment; filename="tokentv-{slug(box.name)}.gif"'})
                    return
            else:
                self.send_error(404)
                return
            self.reply(200, body, content_type)

        def reply(self, status, body, content_type='application/json; charset=utf-8', headers=None):
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.answering = True
            if self.path == '/moment' or urlparse(self.path).path == '/moment':
                self.moment_request()
                return
            if moments_only:
                self.send_error(404)
                return
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
            if origin and not same_origin(origin, self.headers.get('Host')):
                self.send_error(403, 'Origin mismatch')
                return
            try:  # (a body that comes too late is a 408: Late, in handle_one_request)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid JSON request')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {'style'} or data['style'] not in STYLES:
                    raise ValueError('Unknown display style')
            except (ValueError, UnicodeError):
                self.send_error(400, 'Choose a supported display style')
                return
            try:
                preferences.set_style(data['style'])
            except (OSError, ValueError):  # the config could not be written, or read back (edited by hand, say)
                self.send_error(500, 'Could not save display choice')
                return
            self.reply(200, json.dumps(preferences.snapshot()).encode())

        def moment_refusal(self, body=True):
            """Why a moment request is refused, as (status, words), or None. Only this computer may tell TokenTV a
            moment, by its own name, and never a web page; the body is read only once it can be small JSON. With
            `body` False, the same for GET /moment, which carries none."""
            if isinstance(self.client_address, tuple):  # over TCP (on the socket, the peer is this computer)
                try:
                    if not ipaddress.ip_address(self.client_address[0].split('%')[0]).is_loopback:
                        return 403, 'Moments come only from this computer'
                except ValueError:
                    return 403, 'Moments come only from this computer'
            given = self.headers.get_all('Host') or []
            host = host_name(given[0]) if len(given) == 1 else None
            if host is None:
                return 400, 'One plain Host header is needed'
            if host not in hosts:
                return 403, 'This dashboard answers only by this computer\'s names'
            if urlparse(self.path).query or self.path != '/moment':
                return 400, 'A moment carries nothing in its address'
            origins = self.headers.get_all('Origin') or []
            if len(origins) > 1 or (origins and not same_origin(origins[0], given[0].strip())):
                return 403, 'Origin mismatch'
            if not body:
                return (404, 'Not Found') if agents is None else None
            if self.headers.get_all('Transfer-Encoding'):
                return 400, 'A moment is sent with its length'
            types = self.headers.get_all('Content-Type') or []
            if len(types) != 1 or types[0].split(';')[0].strip().lower() != 'application/json':
                return 415, 'A moment is JSON'
            lengths = self.headers.get_all('Content-Length') or []
            if len(lengths) != 1 or not lengths[0].strip().isdigit() or not lengths[0].strip().isascii():
                return 400, 'A moment is sent with its length'
            if int(lengths[0]) > moments.BODY_LIMIT:
                return 413, 'A moment is a short name'
            if int(lengths[0]) == 0:
                return 400, 'A moment is a short name'
            if agents is None:
                return 404, 'Not Found'
            return None

        def moment_request(self):
            """POST /moment {"moment": "claude.ask"}: one of moments.MOMENTS, from the Claude Code mod or Codex's
            notify program. Answered 204 at once; nothing of it is logged or kept, a refusal echoes nothing. One that
            came whole but past its READ_SECONDS is a 408 and changes nothing: its sender has given up on it."""
            refusal = self.moment_refusal()
            if refusal:
                self.refuse(*refusal)
                return
            try:
                self.connection.settimeout(1)  # a sender that stops part-way is let go
                body = self.rfile.read(int(self.headers['Content-Length']))
                if len(body) != int(self.headers['Content-Length']):
                    raise ValueError('Cut short')
                name = moment_of(body)
            except (ValueError, OSError):  # UnicodeError and JSON errors are ValueErrors (one that stops: Late, 408)
                self.refuse(400, 'Choose a moment TokenTV knows')
                return
            # The deadline is looked at only when a read waits for more: a request whose rest came in one go while
            # its first line still had the dashboard's PAGE_SECONDS (its first byte at once, the rest 8 s later) is
            # read whole from the buffer. Past its READ_SECONDS, it counts for nothing all the same.
            if time.monotonic() >= self.deadline:
                raise Late('The request took too long to arrive')
            agents.note(name)
            waited = agents.waited() if name == 'claude.ask' else None
            self.send_response(204)
            self.send_header('Cache-Control', 'no-store')
            if waited is not None:  # how long the wait this ask joined has lasted: when TokenTV lets it go
                self.send_header('TokenTV-Wait-Age', f'{waited:.1f}')
            self.end_headers()

        def moment_check(self):
            """GET /moment is no moment: 405, POST only. Refused as a moment is; nothing changes."""
            refusal = self.moment_refusal(body=False)
            if refusal:
                self.refuse(*refusal)
                return
            self.send_response(405)
            self.send_header('Allow', 'POST')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def refuse(self, status, words):
            """Answer a refusal and close; a sender still sending (a body far too long, say) gets to finish into
            nothing, at most 1 MiB for half a second, so it reads the refusal and not a reset. Nothing it sent is
            kept or looked at."""
            self.close_connection = True
            try:
                self.send_error(status, words)
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                self.connection.settimeout(.25)
                left, end = 1 << 20, time.monotonic() + .5
                while left > 0 and time.monotonic() < end:  # half a second in all, however slowly it comes
                    chunk = self.connection.recv(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            except OSError:
                pass

        def replay_request(self):
            """POST {"check": ...}: play a found one-off on the clock again."""
            origin = self.headers.get('Origin')
            if origin and not same_origin(origin, self.headers.get('Host')):
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
                       'Switch the clock to Arcade first' if preferences is not None and shown.get('style') != 'arcade' else
                       'Claude Code is waiting for you' if agents is not None and agents.busy() and agents.waits else
                       'A bow is on its way' if agents is not None and agents.busy() and agents.bow else
                       'A moment is on its way' if agents is not None and agents.busy() else '')
            if refusal:  # short: the dashboard puts it on the button as it is
                self.reply(409, json.dumps({'error': refusal}).encode())
                return
            replays.append(check)
            if wake:
                wake.set()
            self.reply(200, json.dumps({'queued': check}).encode())
    return Handler


def main(argv=None, ready=None):
    """Run TokenTV: the dashboard, the clock and the agents' moments. `ready(server)` is told once it listens
    (tests and graders stop it with server.shutdown())."""
    parser = argparse.ArgumentParser(description="TokenTV live account display")
    parser.add_argument("--config", help="Credential-free account metadata (default: the one `token-tv start` uses)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output", help="Write a normalized snapshot rather than stdout")
    parser.add_argument("--state-dir", default=".runtime")
    parser.add_argument("--restore-display", action="store_true")
    args = parser.parse_args(argv)
    if args.config is None:
        from token_tv.cli import default_config
        args.config = default_config()
    config = load_config(args.config)
    config["device_url"] = plain(config.get("device_url"))
    if config.get("font"):
        os.environ["TOKEN_TV_FONT"] = config["font"]
    state_dir = Path(args.state_dir)
    try:
        private_dir(state_dir)  # history, snapshots and the clock's backup: this user's alone
    except OSError as error:
        raise SystemExit(f"TokenTV cannot write its state folder {state_dir} ({error.strerror or error}).")
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
        write_private(pid_file, str(os.getpid()))  # how `autostart off` ends it on Windows; gone again at exit
        write_private(url_file, f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}")
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

    shown = {'at': None, 'loop': None}  # when the clock's GIF started (moments.CLOCK), and its loop on that clock
    frame_ms = config.get('device_frame_ms') or DEVICE_FRAME_MS  # an SD_PRO's pace (m1)
    pace = {'at': None}  # when the pace ticks in the clock's picture stand (x4): time alone sends no new picture
    readings = {'count': 0}  # usage readings taken in: a picture waiting for its loop's end is drawn again with one
    lost = {'polls': 0, 'scanned': None}  # polls in a row the clock did not answer, and when it was last looked for
    refused = {'url': None}  # a clock another TokenTV drives, said once

    # The agents' moments (Claude Code waiting for you, a turn done, a pet or a snack, the pets' break): in memory
    # only, gone with a restart.
    unsure = ('unsure',)  # what the clock shows is not known (a send failed): never what is wanted
    displayed = {'what': None}  # the moment in the picture on the clock: None or one of Moments.due()'s
    # Sends in a row of a picture with the break that the clock did not take, and when the break goes once more after
    # the first of them: as the loop the clock plays then ends (moments.CLOCK), or None.
    failed = {'break': 0, 'again': None}
    kick = threading.Event()  # set when the moments change, and to stop: a wait for a loop's end looks again
    agents = moments.Moments({account.get('provider') for account in config['accounts']},
                             wake=lambda: (kick.set(), preferences.changed.set('moment')), active=ACTIVE_SECONDS)

    def version():
        """What a picture waiting for its loop's end was drawn from: the moments due and the readings in."""
        return agents.count, readings['count']

    def follow_clock():
        """The clock to drive: the address in the config, read again each minute (`start` finding the clock, or
        `start --device-url`, while this runs), and its pace (`device_frame_ms`). With no address there, no clock: one
        on this network may be someone else's."""
        nonlocal device, last_upload, frame_ms
        try:
            read = load_config(args.config)
        except (OSError, ValueError):
            return
        wanted = plain(read.get("device_url"))
        frame_ms = read.get('device_frame_ms') or DEVICE_FRAME_MS  # (the next picture's loop is timed by it)
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

    def base():
        """The reading to draw: the store's, with what the one-offs leave (a run of full periods, a prop)."""
        snapshot = store.snapshot()
        for key, count in streaks.items():
            if key in snapshot['accounts']:
                snapshot['accounts'][key]['full_streak'] = count
        for key, (tier, until, prop) in list(traces.items()):
            if time.time() < until and key in snapshot['accounts']:
                snapshot['accounts'][key].update(trace=tier, trace_prop=prop)
            else:
                traces.pop(key, None)
        return snapshot

    def hold(until, seen, what, follows=True):
        """Wait until `until` (moments.CLOCK) to send a picture drawn with the moment `what`; False as soon as the
        moments or the readings change from `seen` (version()) or, when the picture follows them, what is due
        changes with time (a hop, a sign, a wait let go, the hour of work done), or TokenTV stops. The kick is cleared
        before each look, so a change between the look and the wait still ends it."""
        while not stopping.is_set():
            kick.clear()
            if version() != seen or (follows and agents.wanted()[0] != what):
                return False
            now = moments.CLOCK.now()
            if until <= now:
                return True
            turn = agents.next_change(now)  # (a one-off's quiet loop, which follows no moment, looks again too)
            moments.CLOCK.wait(kick, min(until, until if turn is None else turn) - now)
        return False

    def show(image, name, digest, what, receipts, where, paced=None):
        """Send `image` and make it the one the clock shows, its loop starting as the switch is done; `what` is the
        agent's moment in it, `paced` when its pace ticks stand. A bow, a treat or the break is then over: it plays
        that one loop, and what follows is due as it ends."""
        nonlocal last_upload
        begun, on = moments.CLOCK.now(), {}
        try:
            slot, sent = device.put(name, image, digest)
            receipts.extend(sent)
            where['phase'] = "activate"
            device.select(original, slot, on=lambda: on.update(at=moments.CLOCK.now(), wall=time.time()))
        except Exception:
            if shown['at'] is not None:  # the old loop held while the clock tried: it ends that much later
                shown['at'] += moments.CLOCK.now() - begun
            last_upload = None  # what the clock shows is unknown: the next picture goes in full, even this one
            displayed['what'] = unsure
            if on:  # its slot went on before the old one failed to go off: its moment has been on the clock
                agents.shown(what, on['at'], on['wall'])
            elif what and what[0] == 'break':  # still due: once more as the next loop ends (sync_moments), not before
                failed['break'] += 1
                failed['again'] = moments.loop_end(shown, moments.CLOCK.now() + .001) if failed['break'] == 1 else None
            agents.shown(unsure, None)
            raise
        failed.update({'break': 0, 'again': None})
        # Its loop starts once the switch is done: every request holds the clock's animation, the one turning the
        # old slot off after the new one went on too (and every one of a full activation).
        shown['at'], wall = moments.CLOCK.now(), time.time()
        shown['loop'] = loop_seconds(image, device, frame_ms) if name == FILES[1] else None
        last_upload = (name, digest)
        pace['at'] = paced
        displayed['what'] = what
        agents.shown(what, shown['at'], wall)

    def picture(snapshot, style, egg=None):
        """(image, its file name, digest, when its pace ticks stand) for `snapshot` on `style`. Time passing alone
        moves no pace tick on the clock (x4): a picture that differs from the clock's in its ticks alone is the
        clock's own, its ticks where they stood; any other change draws them as they stand now."""
        if style == 'arcade' and pace['at'] is not None and last_upload:
            image = render_page(dict(snapshot, pace_at=pace['at']), 0, style, egg=egg)
            name, digest = FILES[1] if image[:4] == b"GIF8" else FILES[0], hashlib.sha256(image).hexdigest()
            if (name, digest) == last_upload:
                return image, name, digest, pace['at']
        at = time.time()
        image = render_page(dict(snapshot, pace_at=at), 0, style, egg=egg)
        return image, FILES[1] if image[:4] == b"GIF8" else FILES[0], hashlib.sha256(image).hexdigest(), at

    def cycle(refresh=True, egg=None, came=None):
        """Read (if `refresh`: `--once`; a running TokenTV reads in read_usage), draw and upload; True once the
        clock has the picture. A new picture for a looping face lands as the one on the clock finishes its loop, so
        the animation never jumps back mid-move; a one-off's first picture too. On Arcade the picture carries the
        agents' moment due now, and one that changes while the loop plays out is drawn in before it goes; one due as
        a one-off's quiet loop would follow it goes in that loop's place, and one due before a one-off's first
        picture went on goes instead of the one-off (None: nothing sent). `came`: when the change it draws came in
        (moments.CLOCK; now if not given), so the time a reading's one-offs take to pick puts it no later; a moment
        the clock does not show yet goes no later than as the loop playing when it became due ends."""
        nonlocal original, device
        delivered = False
        if refresh:
            store.refresh()
        snapshot = base()
        style = preferences.snapshot()['style']
        if not args.once and device:
            receipts = []
            where = {'phase': "backup"}
            what = None
            try:
                if original is None:
                    original = load_original(device, backup_path)
                where['phase'] = "upload"
                quiet_loop = egg if egg is not None and not getattr(egg, 'intro', True) else None
                entry = egg is not None and quiet_loop is None  # a one-off's own first picture: an event, a box's cut-in
                came = moments.CLOCK.now() if came is None else came
                for _ in range(25):  # a storm of moments still ends in a picture
                    seen = version()  # what it is drawn from (and `came`, when the first change of it came in)
                    snapshot = base()  # (a reading that came in while the last one waited for its loop's end)
                    if quiet_loop is not None:  # an agent's moment due as the one-off ends goes in its quiet loop's place
                        egg = None if style == 'arcade' and agents.wanted()[0] else quiet_loop
                    elif entry and style == 'arcade' and agents.wanted()[0]:  # one came while it waited: it goes first
                        return None
                    follows = style == 'arcade' and egg is None  # a one-off takes the whole loop: no moment in it
                    what, since, mark = agents.wanted() if follows else (None, None, None)
                    image, name, digest, paced = picture(moments.overlay(snapshot, what, mark), style, egg)
                    if (name, digest) == last_upload:  # identical frames are not rewritten to flash
                        displayed['what'] = what
                        agents.shown(what, shown['at'])
                        break
                    if what is None:  # a picture with an agent's moment in it is never kept
                        write_private(state_dir / name, image)
                    # The clock plays and answers on one core: while it takes a picture the animation holds. So
                    # the send and the switch go together as the loop ends: the loop plays out whole, holds a
                    # moment, and the new one starts. A one-off's event or a box's cut-in waits for it too.
                    due = switch_at(shown, came, moments.CLOCK.now())
                    if follows and due is not None and what != displayed['what']:  # as sync_moments would show it
                        due = min(due, switch_at(shown, since, moments.CLOCK.now()))
                    if due is not None and not hold(due, seen, what, follows):
                        if stopping.is_set():
                            return delivered
                        continue  # a moment or a reading changed while the loop played out: draw it in
                    show(image, name, digest, what, receipts, where, paced)
                    break
                if what is None:  # receipts say nothing of the agents' moments
                    write_json(state_dir / "display-receipt.json", {"at": int(time.time()), "style": style, "uploads": receipts})
                preferences.delivered(style, True)
                # Pictures arrive; a clock asked for that another TokenTV drives is still worth saying.
                preferences.problem('other_tokentv' if refused['url'] else None, refused['url'])
                delivered = True
                lost['polls'] = 0
            except (OSError, ValueError, KeyError, HTTPException) as error:
                phase = where['phase']
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
                if what is None:
                    write_json(state_dir / "display-receipt.json", {"at": int(time.time()), "style": style, "status": "error",
                               "phase": phase, "reason": reason, "uploads": receipts, "http_status": getattr(error, "code", None)})
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

    def sync_moments():
        """Bring the agents' moments to the clock (Claude Code waiting for you, a turn done) as the loop it is
        playing ends: one upload per change of what it shows, none for the same again, never mid-loop. A change
        asked for while the loop plays out is drawn in, not queued; a bow with no clock to bow on is dropped. The
        break stays due: one the clock fails to take goes once more as the loop it then plays ends, and after that
        with the clock's next picture. Nothing of it is written anywhere."""
        for _ in range(25):  # a storm of moments still ends in a picture
            if stopping.is_set():
                return
            seen = version()
            what, since, mark = agents.wanted()
            if what == displayed['what']:
                return
            state = preferences.snapshot()
            again = what is not None and what[0] == 'break' and failed['again'] is not None  # its send failed once
            if not device or state['style'] != 'arcade' or (state['status'] == 'error' and not again):
                agents.drop_bow()  # no picture of ours to follow: the next one carries the moment
                return
            if again:  # the break once more as the loop after the failed send ends: the clock gets that loop
                if moments.CLOCK.now() < failed['again']:
                    if not hold(failed['again'], seen, what) and stopping.is_set():
                        return
                    continue
                failed['again'] = None
            if last_upload is None:  # nothing of this run's on the clock yet (its first reading not in), or what it
                cycle(False)  # shows is not known (a send failed): one in full, drawn from what TokenTV has, with the
                continue  # moment, at once or as the loop it holds ends
            image, name, digest, paced = picture(moments.overlay(base(), what, mark), 'arcade')
            due = switch_at(shown, since, moments.CLOCK.now())  # the end of the loop that was playing when it became due
            if due is not None and not hold(due, seen, what):
                if stopping.is_set():
                    return
                continue  # changed again while the loop played out: draw the newest instead
            if (name, digest) == last_upload:
                displayed['what'] = what
                agents.shown(what, shown['at'])
                continue
            try:
                show(image, name, digest, what, [], {}, paced)
            except (OSError, ValueError, KeyError, HTTPException) as error:
                agents.drop_bow()  # (a break stays due)
                reason = problem_of(error)
                preferences.problem(reason, device.base_url, str(error) if reason in ('clock_full', 'error') else '')
                preferences.delivered('arcade', False)
                if failed['again'] is not None:  # the break, not on the clock: once more as the next loop ends
                    continue
                return
            preferences.delivered('arcade', True)

    def quiet_wait(seconds):
        """Wait out a one-off's quiet loop; True when TokenTV stops or an agent's moment wants the clock first, the
        break included, which comes due with time alone."""
        end = moments.CLOCK.now() + seconds
        while not stopping.is_set() and moments.CLOCK.now() < end:
            kick.clear()
            if agents.wanted()[0] != displayed['what']:
                return True
            turn = agents.next_change()
            moments.CLOCK.wait(kick, min(end, end if turn is None else turn) - moments.CLOCK.now())
        return stopping.is_set() or agents.wanted()[0] != displayed['what']

    def play(egg, mark=True, came=None):
        """One one-off on the clock: the event, then for a unique or legend its quiet aftermath, then the usual face.
        True once its event went on; None when an agent's moment came while it waited for the loop's end and went
        first (its turn comes again: put it back), False when it did not reach the clock. `came`: when the reading
        that brought it came in (cycle)."""
        went = False
        try:
            went = cycle(False, egg, came)
            if not went:
                if mark and not isinstance(egg, str):
                    locks.forget()  # never shown, so not seen: it may come again
                return went
            if mark and getattr(egg, 'tier', None) in TRACE and getattr(egg, 'prop', ''):  # in case it was missed
                traces[egg.key] = (egg.tier, TRACE[egg.tier](time.time()), egg.prop)
            # One loop of the event: the next picture is timed by cycle() to land as it ends, so its start never
            # plays again. A unique or legend then keeps its quiet loop for the rest of its time.
            seconds = getattr(egg, 'seconds', EGG_SECONDS)
            event = shown['loop'] or LOOP_SECONDS  # how long the event's one loop lasts on this clock
            if getattr(egg, 'after', ()):
                cycle(False, dataclasses.replace(egg, frames=egg.after, after=(), intro=False))
                if displayed['what'] not in (None, unsure):  # an agent's moment went in the quiet loop's place
                    return True
                if quiet_wait(max(0, seconds - event - (shown['loop'] or 0))):  # its last loop lands it
                    return True
            cycle(False)
        except Exception:
            print("TokenTV easter egg skipped.", flush=True)
        return bool(went)

    def read_usage():
        """Read every account (a provider may take its time) apart from the clock's work, so that no agent's moment
        waits for it: the moments keep their loop ends with the last reading. The clock is told once it is in."""
        try:
            store.refresh()
        except Exception:
            # Never serialize exception text, which may include auth material.
            print("TokenTV poll failed; retained previous snapshot.", flush=True)
        try:
            agents.observe(store.snapshot())  # who is at work, for the pets' break
        except Exception:
            print("TokenTV moment skipped.", flush=True)
        readings['count'] += 1
        kick.set()  # a picture waiting for its loop's end is drawn again with this reading
        preferences.changed.set('reading')

    def poll():
        nonlocal device
        try:
            device = open_display(config["device_url"]) if config.get("device_url") else None
        except ValueError:
            pass  # an address edited into the config by hand: follow_clock says what is wrong with it
        next_refresh, reading = 0, None
        while not stopping.is_set():
            if moments.CLOCK.now() >= next_refresh and not (reading and reading.is_alive()):
                next_refresh = moments.CLOCK.now() + interval
                # One reading at a time, never waited for: it wakes this loop once it is in, and is drawn then. Till
                # then everything goes on with what TokenTV has, the first picture of a run included if a moment
                # needs the clock before the first reading (sync_moments).
                reading = threading.Thread(target=read_usage, name='TokenTV reading', daemon=True)
                reading.start()
            why, came = preferences.changed.take(), moments.CLOCK.now()  # what changed, and when it came in
            new_reading = 'reading' in why
            if new_reading:
                try:
                    follow_clock()  # the clock's address in the config, looked at again with each reading
                except Exception:
                    # Never serialize exception text, which may include auth material.
                    print("TokenTV poll failed; retained previous snapshot.", flush=True)
            arcade_on = preferences.snapshot()['style'] == 'arcade'
            if not arcade_on:
                pending.clear()  # another face now (even for a moment): what was waiting is not played later
            egg = None
            if new_reading and device:
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
                # An agent's moment comes first: no one-off starts while one is due or on the clock.
                busy = agents.busy() or displayed['what'] not in (None, unsure)
                try:
                    egg = (pending.pop(0) if pending else locks.pick(snap)) if arcade_on and not busy else None
                except (OSError, ValueError):
                    egg = None
                    print("TokenTV hidden one-offs skipped.", flush=True)
            # A one-off the reading brings goes on in place of its picture: the one-off's own pictures and the usual
            # face after them show the reading, so the clock takes one picture for it, never two at once. Either goes
            # as the loop playing when the reading came in ends, however long the pick took.
            went = play(egg, came=came) if egg else False
            if went is None and isinstance(egg, str):
                pending.insert(0, egg)  # an agent's moment came first: the event waits its turn again
            if not went and (new_reading or why - {'moment'}):  # a moment alone is sync_moments' to show
                try:
                    cycle(False, came=came)
                except Exception:
                    # Never serialize exception text, which may include auth material.
                    print("TokenTV poll failed; retained previous snapshot.", flush=True)
            # Asked for from the collection book: played now, or once an agent's moment is off the clock.
            while device and replays and not (agents.busy() or displayed['what'] not in (None, unsure)):
                check = replays.pop(0)
                egg = locks.replay(check)
                if egg and play(egg, mark=False) is None:
                    replays.insert(0, check)  # (one came first: once it is over)
            try:
                sync_moments()
            except Exception:
                print("TokenTV moment skipped.", flush=True)
            if device and replays and not (agents.busy() or displayed['what'] not in (None, unsure)):
                continue  # a replay waited for a moment that is over now
            due = agents.next_change()  # a wait grows more insistent, or is let go, on time without a poll
            # and for the next reading, unless one is still under way (that one says when it is in)
            times = [t for t in (due, None if reading.is_alive() else next_refresh) if t is not None]
            until = min(times) if times else moments.CLOCK.now() + interval
            moments.CLOCK.wait(preferences.changed, until - moments.CLOCK.now())

    try:  # the dashboard's port first: if another program has it, stop before touching the clock
        local = args.host in LOCAL_NAMES  # bound to this computer only: answer only by its own names
        names = None if local else lan_names(args.host)  # on the network: by its names and addresses there
        notice = UpdateNotice(state_dir, enabled=config.get('update_check', True))
        server = QuietServer((args.host, args.port), handler(store, preferences, locks, replays, preferences.changed, local, names,
                                                             notice, agents, pace=pace))
    except OSError as error:
        raise SystemExit(f"Port {args.port} is in use on this computer ({error.strerror or error}). "
                         f"Pass another with --port, or use {start_command()}, which picks a free one.")
    # The moments again on a socket of its own in the state folder, for the Claude Code mod (Linux and macOS):
    # what goes over it meets no proxy and is never redirected to another program or computer.
    sock_path, sock_server = state_dir / "live.sock", None
    if hasattr(socketserver, 'ThreadingUnixStreamServer') and not moments.WINDOWS:
        try:
            sock_path.unlink(missing_ok=True)  # one left by a run that ended without its cleanup
            sock_server = MomentSocket(str(sock_path), handler(store, preferences, agents=agents, moments_only=True))
            os.chmod(sock_path, 0o600)
            atexit.register(sock_path.unlink, missing_ok=True)
        except OSError as error:  # a path too long for a socket, say
            if sock_server:
                sock_server.server_close()
            sock_server = None
            # The Claude Code mod and Codex's notify send here alone on Linux and macOS: say so, once.
            print(f"TokenTV could not open its socket for Claude Code's and Codex's moments in {state_dir} "
                  f"({error.strerror or error}); the clock will not show them.", flush=True)
    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    threading.Thread(target=notice.watch, args=(stopping,), daemon=True).start()
    if sock_server:
        threading.Thread(target=sock_server.serve_forever, daemon=True).start()
    # Asked to stop (as systemd and launchd stop it, or `kill`): it ends as Ctrl+C ends it, its address and socket
    # gone with it, so no agent goes on telling a port another program may hold next. (Windows ends it outright.)
    told = None
    if os.name != 'nt' and threading.current_thread() is threading.main_thread():
        def asked_to_stop(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)  # asked once: a second one does not cut the cleanup short
            raise KeyboardInterrupt
        told = signal.signal(signal.SIGTERM, asked_to_stop)
    try:
        with server:
            print(f"TokenTV live listening at http://{args.host}:{args.port}", flush=True)
            if ready:
                ready(server)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        kick.set()
        preferences.changed.set()
        thread.join(timeout=2)
        if sock_server:
            sock_server.shutdown()
            sock_server.server_close()
            sock_path.unlink(missing_ok=True)
        (state_dir / "live.url").unlink(missing_ok=True)  # stopped: the agents find no TokenTV to tell
        if told is not None:
            signal.signal(signal.SIGTERM, told)


if __name__ == "__main__":
    main()
