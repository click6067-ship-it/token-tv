"""What the agents are doing right now (v2): Claude Code waiting for you, a turn done, Clawd petted or given a snack,
and the pets' break once an hour of work.

A moment arrives as its name and nothing else (MOMENTS): from the TokenTV mod in Claude Code (claude-plugin/) and
from Codex's notify program (`token-tv notify`). TokenTV keeps what they mean in memory only, never on disk and never
in a log, so a restart forgets them. The break comes from the usage readings alone (Work). Time here is CLOCK's,
which a test or a grader can replace to run a half-hour wait at once; the readings' times are the wall clock's
(`time.time()`), which moves with it.
"""
import bisect
import json
import math
import os
import random
import socket
import sys
import threading
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path

MOMENTS = ('claude.ask', 'claude.answered', 'claude.end', 'codex.end', 'claude.pet', 'claude.snack')
HOP, SIGN = 5 * 60, 15 * 60  # seconds waited before Clawd hops, and before it holds up a sign (arcade.NEEDS_LEVELS)
EXPIRE = 30 * 60  # the waits are let go this long after the continuous wait began, answered or not
COOLDOWN = 60  # at most one bow in any 60 s, Claude's and Codex's together; one asked for inside it is dropped
TREATS = {'claude.pet': 'pet', 'claude.snack': 'snack'}  # /tokentv pet and /tokentv snack: one loop of Clawd's
WORK = 60 * 60  # an hour of work, any account's, since the last break (or the last reminder) brings one...
BREAK = 10 * 60  # ...where a break is this long with no account at work (its own length, not state.ACTIVE_SECONDS)
BREAKS = ('drink', 'stretch')  # the reminder: a glass of water or a stretch for the pets on the clock
RANDOM = random.Random()  # picks each reminder's break, once (a test or a grader seeds it, or puts its own here)
BODY_LIMIT = 256  # bytes: the most a moment's request may carry
WINDOWS = os.name == 'nt'  # no TokenTV socket there: its port on this computer instead


# Elapsed time that keeps counting while the computer sleeps, as the clock on the desk and the mods' own clocks do:
# a wait that spans a laptop's sleep is as old as it looks. (time.monotonic() stops then on Linux and macOS.)
if sys.platform.startswith('linux') and hasattr(time, 'CLOCK_BOOTTIME'):
    def elapsed():
        return time.clock_gettime(time.CLOCK_BOOTTIME)
elif sys.platform == 'darwin' and hasattr(time, 'CLOCK_MONOTONIC'):
    def elapsed():
        return time.clock_gettime(time.CLOCK_MONOTONIC)  # macOS's counts sleep; time.monotonic()'s does not
else:
    elapsed = time.monotonic


class Clock:
    """Elapsed seconds and waits that end early when an event is set. The moments and the clock's loop run on it;
    a test or a grader puts a fake one in `CLOCK` to run thirty minutes in a moment."""
    def now(self):
        return elapsed()

    def wait(self, event, seconds):
        """Wait until `event` is set or `seconds` have passed; True when the event was set. Looked at again every
        few seconds: a wait's own timer stops while the computer sleeps, the time here does not."""
        end = elapsed() + max(0, seconds)
        while True:
            left = end - elapsed()
            if left <= 0:
                return event.is_set()
            if event.wait(min(left, 5)):
                return True


CLOCK = Clock()


def number(value):
    """A time or an amount as a reading gives one: a finite int or float (not a bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Work:
    """How long the accounts have worked toward the pets' next break (e6), on the wall clock, as the readings tell
    it: working is any account at work (its usage rose within `active` seconds, state.ACTIVE_SECONDS, as Arcade's
    `active`), their times together, never added up, whatever order the readings come in: a rise read late counts
    for when it was measured. An hour of it makes the reminder due, once; BREAK in a row with none at work starts the
    hour over (a reminder not yet shown goes with it), and so does a reminder going on the clock. None pile up.

    A break is settled by the rise that ends it, at the readings' own times: one at exactly BREAK after the last
    account stopped counting as at work starts the hour over; one a moment sooner does not, nor one that a rise read
    later falls in. Till then, a reminder due through BREAK with none at work is not shown (rested).

    An account at work as its readings began to fail (rate limited, an outage: its last rise within `active` of its
    last good reading) is neither at work nor resting from that good reading until one comes in again, for at most
    WORK: that time counts toward neither the hour nor a break. Failing longer (a computer asleep, an account let
    go), the rest of it counts as rest.

    The rises are kept and the hour counted from them again as they change; those older than KEEP before the latest
    reading are summed up (`base`), as is all before a reminder that went on."""
    KEEP = 2 * 60 * 60  # seconds: no reading comes in that late (a snapshot file goes OLD in a quarter of an hour)
    READ = ('ok', 'quota_unavailable')  # a reading that came in, with numbers or without; any other status failed

    def __init__(self, active=None):
        if active is None:
            from token_tv.state import ACTIVE_SECONDS as active  # here: `token-tv notify` loads no more than it needs
        self.active = active
        self.seen = {}  # account key -> its rose_at as last read: another is a rise
        self.failing = {}  # account key -> while its readings fail: since when it is held (at work then), or None
        self.held = []  # [(from, to)]: an account at work whose readings failed, till one came in again
        self.rises = []  # the rises counted from `base` on, oldest first
        # The hour as summed up: (from when the rises count, when the hour began, the work in it by then, when the
        # reminder fell due, when the work before ended); nothing yet, at first.
        self.base = (None, None, 0.0, None, None)
        self.last = None  # the latest rise of any account
        self.mark = None  # how far the readings tell (the latest reading's time)
        self.kind = None  # the break picked for the reminder due now: once, as it falls due
        self.counted = None  # count() of the rises as they stand, till they change
        self.start, self.credit, self.due = None, 0.0, None  # up to `mark`: the hour's start, its work, the reminder

    def observe(self, rows, now):
        """The rises in a reading (`rows`: a snapshot's accounts), and whose readings fail, as of the wall clock's
        `now`."""
        for key, row in rows.items():
            if not isinstance(row, dict):
                continue
            at = row.get('rose_at')
            if number(at) and at != self.seen.get(key):
                self.seen[key] = at
                self.rise(min(at, now))
            self.reading(key, row)
        self.advance(now)
        self.trim()

    def reading(self, key, row):
        """Whether `key`'s reading came in: one at work as its readings began to fail is held till one does."""
        status = row.get('status')
        if status in self.READ:
            began = self.failing.pop(key, None)
            if began is not None:  # in again: neither at work nor resting from its last good reading to this one
                good = row.get('last_success_at')
                self.held.append((began, good if number(good) and good > began else began))
                self.counted = None
        elif isinstance(status, str) and status != 'loading' and key not in self.failing:
            good, rose = row.get('last_success_at'), row.get('rose_at')
            self.failing[key] = good if number(good) and number(rose) and good - rose < self.active else None
            if self.failing[key] is not None:
                self.counted = None

    def holding(self, start, end):
        """Seconds of [start, end) when an account at work could not be read (each for at most WORK)."""
        spans = sorted([(a, min(b, a + WORK)) for a, b in self.held] +
                       [(a, a + WORK) for a in self.failing.values() if a is not None])
        total, reach = 0.0, start
        for a, b in spans:
            a, b = max(a, reach), min(b, end)
            if b > a:
                total, reach = total + b - a, b
        return total

    def rise(self, at):
        """An account's usage rose at `at`, read in whatever order: it counts for when it was measured."""
        since, start, credit, due, ended = self.base
        if since is not None and at + self.active <= since:  # its work ended before what is summed up: only its edge
            self.base = (since, start, credit, due, at + self.active if ended is None else max(ended, at + self.active))
        else:
            bisect.insort(self.rises, at)
        self.last = at if self.last is None else max(self.last, at)
        self.counted = None

    def spans(self):
        """When someone was at work by the rises kept: [[from, to]], oldest first, none touching another."""
        out = []
        for at in self.rises:
            if out and at <= out[-1][1]:
                out[-1][1] = max(out[-1][1], at + self.active)
            else:
                out.append([at, at + self.active])
        return out

    def count(self, upto=None):
        """(when the hour began, the work in it, when the reminder fell due or would, when the work known ends): the
        rises from `base` on, counted to the end of the work they tell (or up to `upto`)."""
        since, start, credit, due, ended = self.base
        for begin, end in self.spans():
            if upto is not None and begin >= upto:
                break
            if (ended is not None and (since is None or begin > since)
                    and begin - ended - self.holding(ended, begin) >= BREAK):
                start, credit, due = begin, 0.0, None  # a break before it: the hour starts over at it
            if start is None:
                start = begin
            low = max(begin, start) if since is None else max(begin, start, since)
            high = end if upto is None else min(end, upto)
            if high > low:
                if due is None and credit + (high - low) >= WORK - 1e-6:
                    due = low + max(0.0, WORK - credit)
                credit += high - low
            ended = end if ended is None else max(ended, end)
        return start, credit, due, ended

    def advance(self, now):
        """Count the hour's work up to `now`: the reminder falls due as the hour completes."""
        self.mark = now if self.mark is None else max(self.mark, now)
        if self.counted is None:
            self.counted = self.count()
        start, credit, due, ended = self.counted
        self.start = start
        self.credit = credit if ended is None else max(0.0, credit - max(0.0, ended - self.mark))
        if due is not None and due <= self.mark + 1e-6:
            if self.kind is None:
                self.kind = RANDOM.choice(BREAKS)  # its break, picked once as it falls due
            self.due = (due, self.kind)
        else:
            self.due = self.kind = None

    def trim(self):
        """Sum up the rises older than KEEP before the latest reading, so that a long run keeps a short list."""
        if self.mark is None or not self.rises or self.rises[0] + self.active > self.mark - self.KEEP:
            return
        upto = self.mark - self.KEEP
        self.base = (upto, *self.count(upto))
        self.rises = [at for at in self.rises if at + self.active > upto]
        self.prune()

    def prune(self):
        """Let go of the holds over before the work summed up ended: no break after it can take from them."""
        ended = self.base[4]
        if ended is not None:
            self.held = [(a, b) for a, b in self.held if min(b, a + WORK) > ended]
        self.counted = None

    def rested(self, now):
        """Whether nobody has been at work for BREAK by `now`, the time an account at work could not be read left out
        (the rise that ends it settles the break)."""
        if self.last is None:
            return False
        if self.counted is None:
            self.counted = self.count()
        ended = self.counted[3]
        return now - ended - self.holding(ended, now) >= BREAK

    def next_due(self, now):
        """When the reminder falls due if the work goes on as it is (no new rise needed), or None."""
        self.advance(now)
        due = self.counted[2]
        return due if self.due is None and due is not None else None

    def shown(self, at):
        """The reminder went on the clock at `at`: the next hour counts from there."""
        self.advance(at)
        ended = self.base[4]
        for rise in self.rises:
            if rise + self.active <= at:  # (its work over by then: only where it ended counts, for a break after)
                ended = rise + self.active if ended is None else max(ended, rise + self.active)
        self.rises = [rise for rise in self.rises if rise + self.active > at]
        self.base = (at, at, 0.0, None, ended)
        self.kind = None
        self.prune()
        self.advance(at)


class Moments:
    """The moments, as what the clock should show now: Claude waiting (outstanding waits counted across sessions,
    as old as the first continuous wait, more insistent at HOP and SIGN), one bow when a turn ends, Clawd petted or
    given a snack (/tokentv pet, /tokentv snack), the pets' break after an hour of work (Work), or the usual face. A
    wait outranks the rest; a bow is dropped, never queued, inside COOLDOWN.

    The waits come as names only: each ask counts one more, each answer one fewer. The wait ends when the count is
    back to none, or EXPIRE after the continuous wait began, whichever comes first; then everything counted is let
    go (an answer with none counted closes nothing), and the next ask starts a new wait at the hand.

    A pet or a snack plays one loop of Clawd's. One asked for while another is still to show or showing is dropped,
    and so is one asked for while Claude waits; a wait drops one not shown yet. Nothing is queued: what is not shown
    is gone. A break due while Claude waits plays after it, if the work did not stop for a break meanwhile, and one
    the clock could not take stays due till it can. Each of these takes its own loop, a bow first, then a treat,
    then the break.

    wanted() says what is due and since when, for the publisher to show at the end of the loop the clock is playing
    then; shown() is told when a picture went on the clock (a bow, a treat or the break plays that one loop, and what
    follows is due after it)."""

    def __init__(self, services, wake=None, active=None):
        self.services = set(services)  # the services this TokenTV shows: a moment of any other is ignored
        self.wake = wake  # called when what the clock should show changes
        self.lock = threading.Lock()
        self.waits = 0  # Claude waits outstanding, every session's
        self.since = None  # when the continuous wait on the clock began
        self.started = None  # the same, on the wall clock (the drawing's `since`)
        self.bow = None  # (service, when it was asked for, the same on the wall clock): a bow due at the loop's end
        self.bowed = None  # when the last bow went on the clock: the cooldown runs from there
        self.treat = None  # ('pet' or 'snack', when it was asked for): one loop of Clawd's at the loop's end
        self.on = None  # what the clock last started showing: a press while a treat is on it is dropped
        self.work = Work(active)  # the hour of work toward the pets' break
        self.calm = 0.0  # when the usual face last became due
        self.count = 0  # goes up with every change of what is due, so a waiting publisher knows to look again

    def note(self, name):
        """Take one moment by name; True when it changed what the clock should show. Unknown names: ValueError."""
        if name not in MOMENTS:
            raise ValueError('Unknown moment')
        service = name.partition('.')[0]
        if service not in self.services:  # nothing of it is shown, nor kept for a service added later
            return False
        with self.lock:
            now = CLOCK.now()
            self.expire(now)
            before = self.due(now)[0]
            if name == 'claude.ask':
                if not self.waits:
                    self.since, self.started = now, time.time()
                self.waits += 1
                self.bow = self.treat = None  # a wait outranks them; one put off is dropped, not kept for later
            elif name == 'claude.answered':
                if self.waits:  # (an answer with none counted, from a wait already let go, closes nothing)
                    self.waits -= 1
                    if not self.waits:
                        self.since = self.started = None
                        self.calm = now
            elif name in TREATS:
                if not (self.waits or self.treat or (self.on is not None and self.on[0] == 'treat')):
                    self.treat = (TREATS[name], now)
            elif not (self.waits or self.bow or self.cooling(now)):
                self.bow = (service, now, time.time())
            changed = self.due(now)[0] != before
            if changed:
                self.count += 1
        if changed and self.wake:
            self.wake()
        return changed

    def observe(self, snapshot):
        """Take a reading of the usage (the store's snapshot) for the pets' break: an account whose usage rose is at
        work. True when that changed what the clock should show."""
        with self.lock:
            now = CLOCK.now()
            before = self.due(now)[0]  # as the publisher last saw it: the hour may be done since
            self.expire(now)
            self.work.observe(snapshot.get('accounts') or {}, self.walls(now))
            changed = self.due(now)[0] != before
            if changed:
                self.count += 1
        if changed and self.wake:
            self.wake()
        return changed

    def walls(self, now):
        """The wall clock's time at CLOCK's `now`: the readings' times are its."""
        return time.time() - (CLOCK.now() - now)

    def expire(self, now, wall=None):
        if self.waits and self.since + EXPIRE <= now:  # waited EXPIRE in all: every wait counted is let go
            self.calm = self.since + EXPIRE  # due from the deadline itself, however late it is looked at
            self.waits, self.since, self.started = 0, None, None
            self.count += 1
        due = self.work.due
        self.work.advance(self.walls(now) if wall is None else wall)
        if self.work.due != due:  # the hour of work is done
            self.count += 1

    def cooling(self, now):
        return self.bowed is not None and now - self.bowed < COOLDOWN

    def resting(self, now):
        """The break the pets are due, as (when it fell due on CLOCK, which break), or None."""
        wall = self.walls(now)
        if self.work.due is None or self.work.rested(wall):
            return None
        at, kind = self.work.due
        return now - (wall - at), kind

    def due(self, now):
        """(what, since when): ('needs', level), ('done', service), ('treat', 'pet' or 'snack'), ('break', 'drink' or
        'stretch'), or None for the usual face."""
        if self.waits:
            waited = now - self.since
            level = 3 if waited >= SIGN else 2 if waited >= HOP else 1
            return ('needs', level), self.since + (0, 0, HOP, SIGN)[level]
        if self.bow:
            return ('done', self.bow[0]), self.bow[1]
        if self.treat:
            return ('treat', self.treat[0]), self.treat[1]
        rest = self.resting(now)
        if rest:  # due since the hour was done, or since what kept it off the clock ended
            return ('break', rest[1]), max(rest[0], self.calm)
        return None, self.calm

    def wanted(self, now=None):
        """(what, since when, the row's `moment` for the drawing or None) for the clock now."""
        with self.lock:
            now = CLOCK.now() if now is None else now
            self.expire(now)
            what, since = self.due(now)
            if what is None:
                mark = None
            elif what[0] == 'needs':
                mark = {'kind': 'needs', 'since': self.started, 'level': what[1]}
            elif what[0] == 'done':
                mark = {'kind': 'done', 'at': self.bow[2]}
            else:
                mark = {'kind': what[1]}
            return what, since, mark

    def waited(self):
        """Seconds the continuous Claude wait has lasted, or None with no wait open: TokenTV's answer to an ask says
        it, so the mod that asked knows when TokenTV lets that wait go, and sends no answer after (it would close
        another, newer wait)."""
        with self.lock:
            now = CLOCK.now()
            self.expire(now)
            return now - self.since if self.waits else None

    def next_change(self, now=None):
        """When what is due changes by itself (a wait grows more insistent or is let go, the hour of work is done);
        None when nothing will."""
        with self.lock:
            now = CLOCK.now() if now is None else now
            wall = self.walls(now)
            self.expire(now, wall)
            times = [t for t in (self.since + HOP, self.since + SIGN, self.since + EXPIRE) if t > now] if self.waits else []
            done = self.work.next_due(wall)  # (counted to `wall` already: nothing changes here)
            if done is not None:
                times.append(now + max(1e-6, done - wall))
            return min(times) if times else None

    def busy(self):
        """Whether a wait, a bow, a treat or the break is due: the hidden one-offs keep out of their way."""
        with self.lock:
            now = CLOCK.now()
            self.expire(now)
            return bool(self.waits or self.bow or self.treat or self.resting(now))

    def shown(self, what, at, wall=None):
        """The clock started showing `what` at `at` (CLOCK; `wall`, the wall clock then): a bow, a treat or the break
        plays that one loop, and what follows is due after it."""
        with self.lock:
            self.on = what
            if not what:
                return
            if what[0] == 'done' and self.bow and self.bow[0] == what[1]:
                self.bow, self.bowed, self.calm = None, at, at
                self.count += 1
            elif what[0] == 'treat' and self.treat and self.treat[0] == what[1]:
                self.treat, self.calm = None, at
                self.count += 1
            elif what[0] == 'break' and self.work.due and self.work.due[1] == what[1]:
                self.work.shown(self.walls(at) if wall is None else wall)
                self.calm = at
                self.count += 1

    def drop_bow(self):
        """No clock to bow on now (none set, another face, or it does not answer): the bow is dropped, and does not
        hold the next one back; so is a pet or a snack. The break stays due: it goes when the clock takes a picture
        of ours again, and its hour counts again only once it is on the clock (shown)."""
        with self.lock:
            if self.bow or self.treat:
                self.bow = self.treat = None
                self.count += 1


def overlay(snapshot, what, mark):
    """`snapshot` with the moment on the rows of its service (Claude's wait or treat, or the service that bows), or
    on every row for the break: a copy, for drawing only. Nothing is added: a service without an account has no row
    to mark."""
    if what is None:
        return snapshot
    service = None if what[0] == 'break' else 'claude' if what[0] in ('needs', 'treat') else what[1]
    accounts = {key: dict(row, moment=dict(mark)) if service in (None, row.get('provider')) else row
                for key, row in snapshot.get('accounts', {}).items()}
    return dict(snapshot, accounts=accounts)


def loop_end(shown, at):
    """When the loop the clock is playing at `at` ends: the first end of a loop at or after `at`, counted from the
    picture's start ('at') and its loop ('loop'); None when nothing loops there (send at once)."""
    if shown.get('at') is None or not shown.get('loop'):
        return None
    loops = max(1, math.ceil((at - shown['at']) / shown['loop'] - 1e-9))
    return shown['at'] + loops * shown['loop']


# --- Sending one (Codex's notify) --------------------------------------------------------------------------------

LOOPBACK = {'127.0.0.1': '127.0.0.1', 'localhost': '127.0.0.1', '[::1]': '::1'}


def address(text):
    """(host, port) of a running TokenTV from its live.url, only when that is this computer's loopback (127.0.0.1,
    localhost or [::1]) with a port and nothing else; else None. Nothing is looked up: a name that is not one of
    these, or anything with a path, a user or a query, is not ours to send to."""
    text = (text or '').strip()
    if not text.startswith('http://'):
        return None
    host, sep, port = text[7:].rpartition(':')
    if not sep or host not in LOOPBACK or not port.isdigit() or len(port) > 5 or not 0 < int(port) < 65536:
        return None
    return LOOPBACK[host], int(port)


class UnixConnection(HTTPConnection):
    """HTTP over TokenTV's own socket in its state folder: no proxy, no other program, nothing to redirect to."""
    def __init__(self, path, host, timeout):
        super().__init__(host, timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def post(state_dir, name, timeout=1.0):
    """Tell the TokenTV whose state folder is `state_dir` the moment `name`; True once it took it. Quiet whatever
    happens: no TokenTV running, no answer. Nothing is retried or kept. On Linux and macOS it goes only over
    TokenTV's socket (live.sock): a live.url without it may be left from a TokenTV that stopped, its port another
    program's now. On Windows, to TokenTV's port on this computer."""
    if name not in MOMENTS:
        raise ValueError('Unknown moment')
    state_dir = Path(state_dir)
    try:
        place = address((state_dir / 'live.url').read_text(encoding='utf-8'))
    except (OSError, UnicodeError):
        return False
    if place is None:
        return False
    host, port = place
    netloc = f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
    sock = state_dir / 'live.sock'
    if WINDOWS:
        conn = HTTPConnection(host, port, timeout=timeout)
    elif sock.is_socket():
        conn = UnixConnection(str(sock), host, timeout)
    else:
        return False
    try:
        conn.request('POST', '/moment', json.dumps({'moment': name}),
                     {'Host': netloc, 'Content-Type': 'application/json'})
        return conn.getresponse().status == 204
    except (OSError, HTTPException, ValueError):
        return False
    finally:
        conn.close()
