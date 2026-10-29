"""Hidden one-offs, shipped locked.

The rarer Arcade scenes are not in this source tree. A release bundles them pre-rendered and
encrypted (`assets/eggs.bin`), each box sealed with the situation that opens it: a few facts such as
`weekday=tue` or `claude:idle`. The bundle keeps only a salted hash of each situation, and the key to a
box comes from the same facts, so a box opens when its situation happens on your clock. It is a spoiler
guard, not a secret: the clock itself must try the facts every minute, so anyone patient enough to try
them all can open every box; reading this file alone tells you what kinds of facts exist, not which
ones open anything, nor what plays.

Every minute the live loop lists the facts true right now for each account, hashes every set of up
to `MAX_FACTS` of them and looks for a box with that hash. Like a game's rare drops, a box rolls once
each time its situation comes about (not every minute it lasts). The odds are set for the clock as a
whole: each rare or unique tier aims at one opening every `PACE` days, shared by the boxes of that tier
whose situations come about on this clock, so a box whose situation comes daily gets small odds and one
that comes weekly gets large ones, and a box that comes less often than its share opens every time (doubled
until first seen; sure once a box is twice its share overdue).
A win waits a random moment while the situation holds; a cooldown keeps one scene from repeating soon,
two of a tier keep `SPACING` apart, and two hidden one-offs keep `GAP` apart unless the second is a legend.
"""
import base64
import copy
import hashlib
import io
import itertools
import json
import os
import random
import time
import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from token_tv.display import ASSETS, shown_windows
from token_tv.state import ACTIVE_SECONDS, NEWS_SECONDS

BUNDLE = ASSETS / 'eggs.bin'
MAX_FACTS = 4
GAP = 30 * 60  # seconds between two hidden one-offs, unless the second is a legend
RECENT = NEWS_SECONDS  # how long a reading's news (a jump, a crossing) counts as now
PROVIDERS = ('claude', 'codex', 'grok', 'copilot')
WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
TIERS = ('common', 'rare', 'unique', 'legend')
# A limit's period, and a step back to the one before: weeks for a weekly window, months for the rest.
PERIOD = {'WEEK': lambda day: '%d-W%02d' % day.isocalendar()[:2], 'MONTH': lambda day: day.strftime('%Y-%m'),
          'BUDGET': lambda day: day.strftime('%Y-%m')}
BACK = {'WEEK': lambda day: day - timedelta(days=7), 'MONTH': lambda day: day.replace(day=1) - timedelta(days=1),
        'BUDGET': lambda day: day.replace(day=1) - timedelta(days=1)}
PACE = {'rare': 3, 'unique': 8}  # days between two openings of a tier on the clock as a whole
SPACING = {'rare': 86400, 'unique': 3 * 86400}  # at least this between two of a tier, so they do not clump
MET_DAYS = 28  # a box shares its tier's pace while its situation has come about this recently
DELAY = 3 * 60  # a won box plays at a random moment within this, if its situation still holds (a legend at once)
NEW_AFTER = 60 * 60  # a situation that has not held for an hour is a new occurrence when it comes back


def per_day(count, days):
    """How often a situation comes about: `count` times in `days` days, counted over a week at least so a box new
    to the clock is not over-trusted."""
    return count / max(7, days)


def shares(rates, pace):
    """Days between openings for each box of a tier, so that together they open about once every `pace` days: a
    box whose situation comes about less often than its share opens every time, and the rest split what is left."""
    budget, rest = 1 / pace, sorted(rates)
    while rest:
        each = budget / len(rest)
        if rest[0] >= each:
            return 1 / each
        budget -= rest.pop(0)
    return 0  # every box of the tier comes about less often than the pace: each opens every time


def odds(count, days, share, first):
    """The chance for one occurrence of a box that should open about once every `share` days, when its situation
    came about `count` times in `days` days on this clock (a week at least, so a new box is not over-trusted);
    doubled until the box is first seen."""
    return min(1.0, (2 if first else 1) / max(share * per_day(count, days), 1e-9))


def daypart(hour):
    """midnight 0–1, night 2–4, dawn 5, morning 6–11, afternoon 12–17, evening 18–21, late 22–23."""
    for end, name in ((2, 'midnight'), (5, 'night'), (6, 'dawn'), (12, 'morning'), (18, 'afternoon'),
                      (22, 'evening'), (24, 'late')):
        if hour < end:
            return name


def same_day(a, b):
    return time.localtime(a)[:3] == time.localtime(b)[:3]


class History:
    """What the hidden one-offs need to remember between runs, in the state folder: the first run, each
    account's peak per period of its limits, and each box's last opening, how often its situation came about,
    and its pending win."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault('fired', {})

    def save(self):
        """Write through a temporary file, so a crash mid-write keeps the old history."""
        spare = self.path.with_suffix('.tmp')
        spare.write_text(json.dumps(self.data))
        os.replace(spare, self.path)

    def observe(self, snapshot, now):
        """Note the first run and, for every account, this period's peak of its main limit: the week for a
        weekly window, the month for a monthly one or a budget."""
        self.data.setdefault('first_run', time.strftime('%Y-%m-%d', time.localtime(now)))
        peaks = self.data.setdefault('peaks', {})
        for row in snapshot.get('accounts', {}).values():
            for w in row.get('windows', []):
                if row.get('status') != 'ok' or w.get('used_percent') is None or w.get('label') not in PERIOD:
                    continue
                periods = peaks.setdefault(row['key'], {}).setdefault(w['label'], {})
                here = PERIOD[w['label']](date.fromtimestamp(now))
                periods[here] = max(periods.get(here, 0), w['used_percent'])
                for old in sorted(periods)[:-8]:  # eight periods back is plenty
                    del periods[old]
            for w in row.get('windows', []):  # 5-hour windows have no calendar: each is known by when it resets
                if row.get('status') == 'ok' and w.get('label') == '5H' and w.get('resets_at') and w.get('used_percent') is not None:
                    runs = self.data.setdefault('five', {}).setdefault(row['key'], {})
                    here = str(round(w['resets_at'] / 600))  # to ten minutes, as a reset time can wobble
                    runs[here] = max(runs.get(here, 0), w['used_percent'])
                    for old in sorted(runs, key=int)[:-8]:
                        del runs[old]
        self.save()

    def five_hour_run(self, key):
        """How many of the account's latest 5-hour windows in a row it used up."""
        count = 0
        for here in sorted(self.data.get('five', {}).get(key, {}), key=int, reverse=True):
            if self.data['five'][key][here] < 100:
                break
            count += 1
        return count

    def full_streak(self, key, now):
        """Periods in a row, up to this one, in which the account used its whole limit (the longest of its
        limits); counted by the calendar, so a clock change cannot double a week."""
        best = 0
        for label, periods in self.data.get('peaks', {}).get(key, {}).items():
            count, day = 0, date.fromtimestamp(now)
            while periods.get(PERIOD[label](day), 0) >= 100:
                count, day = count + 1, BACK[label](day)
            best = max(best, count)
        return best

    def anniversary(self, now):
        first = self.data.get('first_run')
        today = time.strftime('%Y-%m-%d', time.localtime(now))
        return bool(first) and today[5:] == first[5:] and today[:4] > first[:4]


def facts(snapshot, history, now):
    """{account key: the facts true now for it}: the shared ones (time, all four at once) and its own."""
    t = time.localtime(now)
    shared = {f'hour={t.tm_hour}', f'minute={t.tm_min}', f'weekday={WEEKDAYS[t.tm_wday]}',
              'weekend=' + ('yes' if t.tm_wday >= 5 else 'no'), f'daypart={daypart(t.tm_hour)}',
              f'date={t.tm_mon:02d}-{t.tm_mday:02d}'}
    rows = list(snapshot.get('accounts', {}).values())
    worked = lambda row: bool(row.get('rose_at')) and same_day(row['rose_at'], now)
    fresh = lambda row: row.get('status') == 'ok'  # working or idle is known only from a good reading
    if all(any(r['provider'] == p and fresh(r) and r.get('active') for r in rows) for p in PROVIDERS):
        shared.add('all_active')
    if all(any(r['provider'] == p and worked(r) for r in rows) for p in PROVIDERS):
        shared.add('all_used_today')
    if any(fresh(r) and r.get('active') for r in rows):
        shared.add('someone_active')
    if history.anniversary(now):
        shared.add('anniversary')
    found, shared_news = {}, set()
    for row in rows:
        p, own = row['provider'], set()
        since = row.get('active_since')
        main = shown_windows(row, 3) if row.get('windows') else []
        main_label = main[0]['label'] if main else None
        main_used = main[0].get('used_percent') if main else None
        if fresh(row):
            own.add(f'{p}:active' if row.get('active') else f'{p}:idle')
            if row.get('active') and since:
                own.update(f'{p}:active_{h}h' for h in (1, 2) if now - since >= h * 3600)
        for item in row.get('news') or ():
            if now - item.get('at', 0) >= RECENT:
                continue
            kind, value = item.get('kind'), item.get('value')
            if kind == 'jump' and value >= 10:
                own.add(f'{p}:jump_10')
            elif kind == 'crossed':
                own.add(f'{p}:crossed_{value}')
                if item.get('label') == main_label and main_used is not None and value <= main_used < 100:
                    own.add(f'{p}:main_crossed_{value}')  # the pet's picture's window, and still where it crossed
            elif kind == 'first_today':
                own.add(f'{p}:first_today')
                shared_news.add('day_start')
            elif kind == 'back':
                own.add(f'{p}:back')
            elif kind == 'ticket_spent':
                own.add(f'{p}:ticket_spent')
                if value < 1:
                    own.add(f'{p}:ticket_spent_last_day')
        if worked(row):
            own.add(f'{p}:worked_today')
        if history.full_streak(row['key'], now) >= 4:
            own.add(f'{p}:full_4')
        found[row['key']] = own
    return {key: shared | shared_news | own for key, own in found.items()}  # the first use of the day counts for all


# --- Sealing and opening ----------------------------------------------------------------------

def situation(fact_set):
    return '&'.join(sorted(fact_set)).encode()


def digest(*parts):
    return hashlib.sha256(b'|'.join(parts)).hexdigest()


def keystream(key, length):
    blocks = (hashlib.sha256(key + n.to_bytes(8, 'big')).digest() for n in itertools.count())
    return b''.join(itertools.islice(blocks, (length + 31) // 32))[:length]


def xor(data, key):
    return bytes(a ^ b for a, b in zip(data, keystream(key, len(data))))


def seal(salt, fact_set, content, chance=1.0, cooldown_days=7):
    """One locked box: `content` (a dict) opens only with exactly the facts in `fact_set`."""
    nonce = os.urandom(16)
    key = hashlib.sha256(b'key|' + salt + b'|' + nonce + b'|' + situation(fact_set)).digest()
    data = xor(zlib.compress(json.dumps(content).encode()), key)
    return {'check': digest(b'check', salt, situation(fact_set)), 'nonce': nonce.hex(), 'chance': chance,
            'cooldown_days': cooldown_days, 'data': base64.b64encode(data).decode()}


def open_box(salt, record, fact_set):
    key = hashlib.sha256(b'key|' + salt + b'|' + bytes.fromhex(record['nonce']) + b'|' + situation(fact_set)).digest()
    return json.loads(zlib.decompress(xor(base64.b64decode(record['data']), key)))


@dataclass(frozen=True)
class Box:
    """An opened one-off: the stage frames to play once (one per clock frame) for account `key`, and the quiet
    loop that stays for the rest of its `seconds`."""
    name: str
    tier: str
    key: str
    frames: tuple
    seconds: int
    after: tuple = ()
    intro: bool = True  # the cut-in at the start; off for the quiet loop that follows
    prop: str = ''  # what it leaves in the scene once played (a base64 PNG), if anything


def frames_of(strip, height):
    """The frames of a box, stacked top to bottom in one PNG."""
    image = Image.open(io.BytesIO(base64.b64decode(strip))).convert('RGB')
    return tuple(image.crop((0, y, image.width, y + height)) for y in range(0, image.height, height))


class Lockbox:
    def __init__(self, history_path, bundle=BUNDLE, roll=random.random):
        self.history = History(history_path)
        self.roll = roll
        self.undo = None  # what the last pick changed, until it is known to have played
        try:
            loaded = json.loads(Path(bundle).read_text())
            self.salt, self.boxes = bytes.fromhex(loaded['salt']), {b['check']: b for b in loaded['boxes']}
        except (OSError, ValueError, KeyError):
            self.salt, self.boxes = b'', {}

    @staticmethod
    def box_of(content, key, variant=0):
        """The box to play; a box with several `strips` plays the next one each time it is found."""
        strips = content.get('strips') or [content['strip']]
        after = frames_of(content['after'], content['height']) if content.get('after') else ()
        return Box(content['name'], content['tier'], key, frames_of(strips[variant % len(strips)], content['height']),
                   content['seconds'], after, prop=content.get('prop', ''))

    def collection(self):
        """The collection book: every box opened so far on this clock (newest first) and how many are still
        hidden. Nothing about the hidden ones is known until they open."""
        found = [dict(check=check, **{k: v for k, v in seen.items() if k not in ('combo', 'key')})
                 for check, seen in self.history.data.get('found', {}).items() if check in self.boxes]
        found.sort(key=lambda item: -item['last'])
        return {'found': found, 'total': len(self.boxes), 'hidden': len(self.boxes) - len(found)}

    def replay(self, check):
        """A box already found, opened again with the situation that opened it, to play once more; or None."""
        seen = self.history.data.get('found', {}).get(check)
        record = self.boxes.get(check)
        if not seen or not record:
            return None
        content = self.opened(record, tuple(seen['combo']))
        return self.box_of(content, seen['key'], seen['count'] - 1) if content else None

    def opened(self, record, combo):
        try:
            return open_box(self.salt, record, combo)
        except (ValueError, zlib.error):
            return None

    def pick(self, snapshot, now=None):
        """The hidden one-off to play now, or None."""
        now = time.time() if now is None else now
        self.history.observe(snapshot, now)
        if not self.boxes:
            return None
        data = self.history.data
        fired, met, spaced = data['fired'], data.setdefault('met', {}), data.setdefault('spaced', {})
        armed, held = data.setdefault('armed', {}), data.setdefault('held', {})
        matched = self.matches(facts(snapshot, self.history, now))
        for check, (record, combo, key) in matched.items():  # one roll each time a situation comes about
            new = now - held.get(check, float('-inf')) > NEW_AFTER
            held[check] = now
            if not new or check in armed or now - fired.get(check, 0) < record['cooldown_days'] * 86400:
                continue
            content = self.opened(record, combo)
            if not content:
                continue
            tier = content['tier']
            seen = met.setdefault(check, {'first': now, 'count': 0})
            seen.update(count=seen['count'] + 1, tier=tier)
            if now - spaced.get(tier, 0) < SPACING.get(tier, 0):
                continue  # one of its tier played lately
            if self.roll() < self.odds_now(record, check, tier, now):
                armed[check] = now + (0 if tier == 'legend' else self.roll() * DELAY)  # a legend's moment can be a minute
        due = []
        for check, at in list(armed.items()):
            if now - at > 2 * 86400:  # a win whose situation never came back
                del armed[check]
            elif at <= now and check in matched:
                record, combo, key = matched[check]
                content = self.opened(record, combo)
                if content:
                    due.append(((TIERS.index(content['tier']), len(combo)), check, content, key))
        chosen, self.undo = None, None
        # the rarer tier first, and within a tier the more particular situation (more facts)
        for _, check, content, key in sorted(due, key=lambda item: (-item[0][0], -item[0][1])):
            if content['tier'] != 'legend' and now - data.get('last_at', 0) < GAP:
                continue
            if now - spaced.get(content['tier'], 0) < SPACING.get(content['tier'], 0):
                continue  # won alongside another of its tier: it waits its turn (or lapses with its win)
            self.undo = copy.deepcopy({k: data.get(k) for k in ('fired', 'armed', 'spaced', 'found', 'last_at')})
            fired[check], data['last_at'], spaced[content['tier']] = now, now, now
            del armed[check]
            seen = data.setdefault('found', {}).setdefault(check, {
                'name': content['name'], 'title': content.get('title', content['name']), 'tier': content['tier'],
                'first': now, 'count': 0})
            seen.update(last=now, count=seen['count'] + 1, combo=list(matched[check][1]), key=key)
            chosen = self.box_of(content, key, seen['count'] - 1)
            break
        self.history.save()
        return chosen

    def matches(self, found):
        """{check: (record, facts, account key)} for every box whose situation holds in `found` (facts by account)."""
        matched = {}
        for key, fact_set in found.items():
            ordered = sorted(fact_set)
            for size in range(1, MAX_FACTS + 1):
                for combo in itertools.combinations(ordered, size):
                    record = self.boxes.get(digest(b'check', self.salt, situation(combo)))
                    if record:
                        matched.setdefault(record['check'], (record, combo, key))
        return matched

    def odds_now(self, record, check, tier, now):
        """This occurrence's chance: sure for a box sealed sure and for the tiers without a pace, else the box's
        share of its tier's pace, sure once twice its share has passed since it last opened (or was first met)."""
        if record.get('chance', 1) >= 1 or tier not in PACE:
            return 1.0
        data = self.history.data
        met, held, fired = data['met'], data['held'], data['fired']
        rates = [per_day(m['count'], (now - m['first']) / 86400) for c, m in met.items()
                 if m.get('tier') == tier and now - held.get(c, 0) < MET_DAYS * 86400]
        share, seen = shares(rates, PACE[tier]), met[check]
        if now - fired.get(check, seen['first']) >= 2 * share * 86400:
            return 1.0
        return odds(seen['count'], (now - seen['first']) / 86400, share, check not in fired)

    def forget(self):
        """The last pick never reached the screen: take it back, so it is neither seen nor resting."""
        if self.undo:
            for name, value in self.undo.items():
                if value is None:
                    self.history.data.pop(name, None)
                else:
                    self.history.data[name] = value
            self.undo = None
            self.history.save()
