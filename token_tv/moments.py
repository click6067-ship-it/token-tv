"""What the agents are doing right now (v2): Claude Code waiting for you, a turn done, Clawd petted or given a snack,
the pets' break once an hour of work, and Clawd's phase-3a moments: the courtroom for a risky command, the ghost of a
deleted file, its back turned for a rude prompt, dizzy after a failed tool, squeezing its head on a compaction, and
Claude Code's own thinking word in the readout.

A moment arrives as its name and nothing else (MOMENTS, or WORD and one word of letters): from the TokenTV mod in
Claude Code (claude-plugin/) and from Codex's notify program (`token-tv notify`). TokenTV keeps what they mean in
memory only, never on disk and never in a log, so a restart forgets them (a word included). The break comes from the
usage readings alone (Work). Time here is CLOCK's, which a test or a grader can replace to run a half-hour wait at
once; the readings' times are the wall clock's (`time.time()`), which moves with it.
"""
import bisect
import json
import math
import os
import random
import re
import socket
import sys
import threading
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path

MOMENTS = ('claude.ask', 'claude.answered', 'claude.end', 'codex.end', 'claude.pet', 'claude.snack',
           'claude.risky', 'claude.deleted', 'claude.rude', 'claude.calm', 'claude.failed', 'claude.compact',
           'claude.stop')
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

# Phase 3a, from Claude Code (each name from the mod; nothing else of the call, the prompt or the session comes):
COURT_LIMIT = 24 * 60 * 60  # e3: one courtroom in any 24 hours, from the last one's start on the clock
COURT_STALE = 2 * 60  # a courtroom not on the clock this long after its command is dropped (a prompt left open)
COURTS = ('verdict', 'objection')  # its two variants (claude_moments.py), one picked at random each time
GHOST = 60  # e4: a ghost floats a minute from the deletion; a fresh one meanwhile makes it a minute from that one
GHOSTS = ('drift', 'wave')  # its two variants, one picked at random as it appears
BACK = 60  # e7: the back turned a minute from the rude prompt (a fresh one: from that one), or till a calm prompt
FACES = {'claude.failed': 'failed', 'claude.compact': 'compact'}  # x5: one loop of dizzy, or of the squeeze...
FACE_COOLDOWN = 60  # ...at most one of the two in any 60 s, from the last one's start on the clock
WORD = 'claude.word:'  # x6: Claude Code's own thinking word, one word of 1 to WORD_MAX letters A-Z after it
WORD_MAX = 14
WORD_FORM = re.compile(r'claude\.word:([A-Za-z]{1,%d})' % WORD_MAX)
WORD_INTERVAL = 60  # a new word on the clock at most once a minute, from one word's start to the next's
WORD_STALE = 30 * 60  # a word not said again for this long is let go (a session that ended without saying so)


def word_of(name):
    """The thinking word a moment's name carries, in capitals ('claude.word:Pondering' -> 'PONDERING'), or None: one
    word of WORD_MAX ASCII letters at most, nothing before or after it."""
    found = WORD_FORM.fullmatch(name) if isinstance(name, str) else None
    return found.group(1).upper() if found else None


def known(name):
    """Whether `name` is a moment TokenTV takes: one of MOMENTS, or WORD and its word."""
    return isinstance(name, str) and (name in MOMENTS or word_of(name) is not None)


def urgent(what):
    """Whether `what` (as Moments.due() says it, or as the clock shows it) takes the clock from a one-off: any moment
    but the usual face and its states (a ghost, the back turned, the thinking word), which a one-off hides for its
    loop, their minutes running on meanwhile."""
    return what is not None and what[0] != 'state'


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

    Phase 3a. A risky command brings the courtroom, one loop, at most once in COURT_LIMIT from the last one's start on
    the clock; one asked for while one is to show, or inside that day, is dropped (never kept for the day's end). It
    comes after a bow and a treat and before the break, and waits out a wait (a risky command is mostly one Claude
    Code asks you about), but only for COURT_STALE from its command: one not on the clock by then is dropped, and
    takes nothing of the day. A failed tool or a compaction brings one loop of a tool face, the lowest of the one-offs:
    under everything above, at most one in any FACE_COOLDOWN from the last one's start; one while another is to show
    or inside that minute is dropped, and so is one while Claude waits (a wait drops one not shown yet). The ghost
    (a minute from the last deletion), the back turned (a minute from the last rude prompt, or till a calm one) and
    the thinking word are states of the usual face, drawn together: every one-off hides them for its loop, their
    minutes running on; one over meanwhile is simply gone. When the back turned ends on the clock (not hidden), one
    loop of Clawd turning back round follows (dropped if anything else goes on first). Clawd does not bow while its
    back is turned: a turn's end then brings no bow, and a bow still to show goes as the back turns. The word shows
    from the moment it is said, a new one at most once in WORD_INTERVAL from the last new one's start readable on the
    clock (the newest waits for it, no others); a turn's end (claude.end, or claude.stop for one cut short) takes it
    away at once.

    wanted() says what is due and since when, for the publisher to show at the end of the loop the clock is playing
    then; shown() is told when a picture went on the clock (a bow, a treat, the break or a phase-3a one-off plays
    that one loop, and what follows is due after it)."""

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
        self.court = None  # (when the risky command came, which courtroom): one loop of it due at the loop's end
        self.courted = None  # when the last courtroom went on the clock: COURT_LIMIT runs from there
        self.ghost = None  # [when its minute is up, which ghost] while one floats about
        self.back = None  # when the back turned's minute is up, while Clawd sulks
        self.forgiven = None  # when Clawd turning back round fell due: one loop of it at the loop's end
        self.face = None  # ('failed' or 'compact', when it came): one loop of a tool face due at the loop's end
        self.faced = None  # when the last tool face went on the clock: FACE_COOLDOWN runs from there
        self.word = None  # Claude Code's thinking word to show now, in capitals
        self.word_next = None  # a newer one, waiting for WORD_INTERVAL from the last new word's start
        self.word_at = None  # when the last new word went on the clock, readable in the readout...
        self.word_shown = None  # ...and which word that was
        self.heard = None  # when the word (or the newer one) was last said: let go WORD_STALE after
        self.settled = 0.0  # when the usual face's states (the ghost, the back turned, the word) last changed

    def note(self, name):
        """Take one moment by name; True when it changed what the clock should show. Unknown names: ValueError. The
        publisher is woken for a change, and for one that changes nothing yet but comes sooner than it would look
        again (next_change(): a newer word waiting for its minute)."""
        word = word_of(name)
        if name not in MOMENTS and word is None:
            raise ValueError('Unknown moment')
        service = name.partition('.')[0]
        if service not in self.services:  # nothing of it is shown, nor kept for a service added later
            return False
        with self.lock:
            now = CLOCK.now()
            wall = self.walls(now)
            self.expire(now, wall)
            before, soon = self.due(now)[0], self.soonest(now, wall)
            if word is not None:
                self.say(word, now)
            elif name == 'claude.ask':
                if not self.waits:
                    self.since, self.started = now, time.time()
                self.waits += 1
                # A wait outranks them; one put off is dropped, not kept for later (a courtroom waits it out, for
                # COURT_STALE at most).
                self.bow = self.treat = self.face = self.forgiven = None
            elif name == 'claude.answered':
                if self.waits:  # (an answer with none counted, from a wait already let go, closes nothing)
                    self.waits -= 1
                    if not self.waits:
                        self.since = self.started = None
                        self.calm = now
            elif name in TREATS:
                if not (self.waits or self.treat or (self.on is not None and self.on[0] == 'treat')):
                    self.treat = (TREATS[name], now)
            elif name == 'claude.risky':
                if not (self.court or (self.courted is not None and now - self.courted < COURT_LIMIT)):
                    self.court = (now, RANDOM.choice(COURTS))
            elif name == 'claude.deleted':
                if self.ghost:  # still about: a minute from this one, the same ghost and picture
                    self.ghost[0] = now + GHOST
                else:
                    self.ghost = [now + GHOST, RANDOM.choice(GHOSTS)]
                    self.settled = max(self.settled, now)
            elif name == 'claude.rude':
                if self.back is None:
                    self.settled = max(self.settled, now)
                self.back = now + BACK  # (a fresh one: a minute from this one)
                self.forgiven = None
                if self.bow and self.bow[0] == 'claude':  # a sulking Clawd does not bow, not even for a turn before
                    self.bow = None
            elif name == 'claude.calm':
                if self.back is not None:
                    self.turn_round(now)
            elif name in FACES:
                if not (self.waits or self.face or (self.faced is not None and now - self.faced < FACE_COOLDOWN)):
                    self.face = (FACES[name], now)
            elif name == 'claude.stop':  # a turn cut short: its word goes, and nothing bows
                self.unsay(now)
            else:  # a turn done: its word goes, and its pet bows unless a wait or the bows' minute says no (or Clawd
                # sulks: its back turned, the rude prompt's own turn included)
                if name == 'claude.end':
                    self.unsay(now)
                if not (self.waits or self.bow or self.cooling(now) or (service == 'claude' and self.back is not None)):
                    self.bow = (service, now, time.time())
            changed = self.due(now)[0] != before
            if changed:
                self.count += 1
            sooner = self.soonest(now, wall)
            woken = changed or (sooner is not None and (soon is None or sooner < soon))
        if woken and self.wake:
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

    def say(self, word, now):
        """Claude Code's thinking word `word` (a turn is going): in place of the usual one from now, or, inside
        WORD_INTERVAL of the last new word's start on the clock, once that is up (the newest only). The same word
        again changes nothing (and a newer one waiting gives way to it)."""
        self.heard = now
        if word == self.word:
            self.word_next = None
        elif self.word_at is None or now - self.word_at >= WORD_INTERVAL:
            self.word, self.word_next = word, None
            self.settled = max(self.settled, now)
        else:
            self.word_next = word

    def unsay(self, at):
        """The turn is over at `at`: its word goes, whatever WORD_INTERVAL says, and one waiting goes with it. The
        next word on the clock, the same one again included, is a new word's start (WORD_INTERVAL from this one's)."""
        if self.word is not None:
            self.settled = max(self.settled, at)
        self.word = self.word_next = self.word_shown = None

    def turn_round(self, at):
        """The back turned is over at `at` (a calm prompt, or its minute up): Clawd turns back round for one loop if
        the clock was showing the sulk; not for a sulk it never showed, nor one a moment had hidden."""
        self.back = None
        self.settled = max(self.settled, at)
        if self.on and self.on[0] == 'state' and self.on[2]:
            self.forgiven = at

    def expire(self, now, wall=None):
        if self.waits and self.since + EXPIRE <= now:  # waited EXPIRE in all: every wait counted is let go
            self.calm = self.since + EXPIRE  # due from the deadline itself, however late it is looked at
            self.waits, self.since, self.started = 0, None, None
            self.count += 1
        due = self.work.due
        self.work.advance(self.walls(now) if wall is None else wall)
        if self.work.due != due:  # the hour of work is done
            self.count += 1
        if self.court and self.court[0] + COURT_STALE <= now:  # not on the clock in time: news no more
            self.court = None
            self.count += 1
        # The usual face's states, each changed from its own deadline, however late it is looked at.
        if self.ghost and self.ghost[0] <= now:
            self.settled = max(self.settled, self.ghost[0])
            self.ghost = None
            self.count += 1
        if self.back is not None and self.back <= now:
            self.turn_round(self.back)
            self.count += 1
        if self.word_next is not None and self.word_at + WORD_INTERVAL <= now:
            self.settled = max(self.settled, self.word_at + WORD_INTERVAL)
            self.word, self.word_next = self.word_next, None
            self.count += 1
        if (self.word or self.word_next) and self.heard + WORD_STALE <= now:
            self.unsay(self.heard + WORD_STALE)
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
        """(what, since when): ('needs', level), ('done', service), ('treat', 'pet' or 'snack'), ('risky', which
        courtroom), ('break', 'drink' or 'stretch'), ('calm',) for the turn back round, ('face', 'failed' or
        'compact'), or the usual face: ('state', which ghost or None, the back turned?, the word or None) with any
        of those on it, else None."""
        if self.waits:
            waited = now - self.since
            level = 3 if waited >= SIGN else 2 if waited >= HOP else 1
            return ('needs', level), self.since + (0, 0, HOP, SIGN)[level]
        if self.bow:
            return ('done', self.bow[0]), self.bow[1]
        if self.treat:
            return ('treat', self.treat[0]), self.treat[1]
        if self.court:
            return ('risky', self.court[1]), self.court[0]
        rest = self.resting(now)
        if rest:  # due since the hour was done, or since what kept it off the clock ended
            return ('break', rest[1]), max(rest[0], self.calm)
        if self.forgiven is not None:
            return ('calm',), self.forgiven
        if self.face:
            return ('face', self.face[0]), self.face[1]
        ghost = self.ghost[1] if self.ghost else None
        if ghost or self.back is not None or self.word:
            return ('state', ghost, self.back is not None, self.word), max(self.calm, self.settled)
        return None, max(self.calm, self.settled)

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
            elif what[0] == 'risky':
                mark = {'kind': 'risky', 'style': what[1]}
            elif what[0] == 'calm':
                mark = {'kind': 'calm'}
            elif what[0] == 'state':  # what goes on Clawd's rows: the sulk (with the ghost round it) or the ghost
                _, ghost, back, word = what
                moment = (dict({'kind': 'rude'}, **({'ghost': ghost} if ghost else {})) if back else
                          {'kind': 'deleted', 'style': ghost} if ghost else None)
                mark = {'moment': moment, 'word': word}
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
        """When what is due changes by itself (a wait grows more insistent or is let go, the hour of work is done, a
        courtroom not shown in time is dropped, a ghost's or the back turned's minute is up, a newer word's minute has
        come, a word goes stale); None when nothing will."""
        with self.lock:
            now = CLOCK.now() if now is None else now
            wall = self.walls(now)
            self.expire(now, wall)
            return self.soonest(now, wall)

    def soonest(self, now, wall):
        """next_change() at `now` (`wall` on the wall clock), with the lock held and expire() done."""
        times = [t for t in (self.since + HOP, self.since + SIGN, self.since + EXPIRE) if t > now] if self.waits else []
        done = self.work.next_due(wall)  # (counted to `wall` already: nothing changes here)
        if done is not None:
            times.append(now + max(1e-6, done - wall))
        if self.court:
            times.append(self.court[0] + COURT_STALE)
        if self.ghost:
            times.append(self.ghost[0])
        if self.back is not None:
            times.append(self.back)
        if self.word_next is not None:
            times.append(self.word_at + WORD_INTERVAL)
        if self.word or self.word_next:
            times.append(self.heard + WORD_STALE)
        return min(times) if times else None

    def busy(self):
        """Whether a wait, a bow, a treat, the break or one of phase 3a's one-offs is due: the hidden one-offs keep
        out of their way (not out of the usual face's states: a one-off hides those for its loop)."""
        with self.lock:
            now = CLOCK.now()
            self.expire(now)
            return bool(self.waits or self.bow or self.treat or self.resting(now) or self.court or self.face
                        or self.forgiven is not None)

    def shown(self, what, at, wall=None, readable=True):
        """The clock started showing `what` at `at` (CLOCK; `wall`, the wall clock then): a bow, a treat, the break or
        a phase-3a one-off plays that one loop, and what follows is due after it; a new word on it starts its minute,
        if it is `readable` there: a readout's label (the publisher knows from the picture: SLOW may take the label)."""
        with self.lock:
            self.on = what
            if self.forgiven is not None and what != ('calm',):  # something else went on first: no turning round
                self.forgiven = None
                self.count += 1
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
            elif what[0] == 'risky' and self.court and self.court[1] == what[1]:
                self.court, self.courted, self.calm = None, at, at
                self.count += 1
            elif what == ('calm',):
                self.forgiven, self.calm = None, at
                self.count += 1
            elif what[0] == 'face' and self.face and self.face[0] == what[1]:
                self.face, self.faced, self.calm = None, at, at
                self.count += 1
            elif (what[0] == 'state' and what[3] and what[3] != self.word_shown and not (what[1] or what[2])
                  and readable):
                self.word_at, self.word_shown = at, what[3]  # a new word's start on the clock, readable there (the
                # ghost's BOO!, the sulk's SULKING and SLOW say their own word instead: it starts once it shows)

    def drop_bow(self):
        """No clock to bow on now (none set, another face, or it does not answer): the bow is dropped, and does not
        hold the next one back; so is a pet or a snack, and a phase-3a one-off (a courtroom not shown takes nothing
        of its day). The break stays due: it goes when the clock takes a picture of ours again, and its hour counts
        again only once it is on the clock (shown). The ghost, the back turned and the word stay, their minutes
        running on."""
        with self.lock:
            if self.bow or self.treat or self.court or self.face or self.forgiven is not None:
                self.bow = self.treat = self.court = self.face = self.forgiven = None
                self.count += 1


def overlay(snapshot, what, mark):
    """`snapshot` with the moment on the rows of its service (Claude's wait, treat or phase-3a moments, or the
    service that bows), or on every row for the break: a copy, for drawing only. The usual face's states go on
    Claude's rows as their moment and the thinking word as the row's 'word'. Nothing is added: a service without an
    account has no row to mark."""
    if what is None:
        return snapshot
    if what[0] == 'state':
        def marked(row):
            row = dict(row, moment=dict(mark['moment'])) if mark.get('moment') else dict(row)
            return dict(row, word=mark['word']) if mark.get('word') else row
        accounts = {key: marked(row) if row.get('provider') == 'claude' else row
                    for key, row in snapshot.get('accounts', {}).items()}
        return dict(snapshot, accounts=accounts)
    claude = ('needs', 'treat', 'risky', 'calm', 'face')
    service = None if what[0] == 'break' else 'claude' if what[0] in claude else what[1]
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
