"""Polling owns provider requests; HTTP readers only see cached state."""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from token_tv.sources import STALE_SECONDS, fetch_account
from token_tv.usage import even_day, today_window, window_minutes

# An account counts as working for this long after its used % last went up. It outlasts the slowest
# fetch below, so a steady worker keeps running between readings.
ACTIVE_SECONDS = 600
# Claude's usage endpoint answers frequent callers with 429s, so its accounts are read at most every
# five minutes even when the clock refreshes every minute.
MIN_FETCH_SECONDS = {"claude": 300}
RETRY_CAP = 6 * 3600  # the longest a provider's Retry-After is waited for
BACKOFF_CAP = 900  # the longest wait between two tries of a failing account that gave no Retry-After


def backoff(failures):
    """Seconds to wait after `failures` failed readings in a row of an account: none after the first (one poll
    later, as always), then doubling from a minute up to BACKOFF_CAP."""
    return 0 if failures < 2 else min(BACKOFF_CAP, 60 * 2 ** (failures - 2))


def comparable(previous, row):
    """Two readings can be compared window by window only when they name the same windows: a reading where a
    window went missing (or a second one took its name) says nothing about work or resets."""
    return {w["label"] for w in previous.get("windows", [])} == {w["label"] for w in row.get("windows", [])}


def rose(previous, row):
    """True when any window's used % is higher than the previous reading of the same window."""
    if row["status"] != "ok" or not comparable(previous, row):
        return False
    before = {w["label"]: w.get("used_percent") for w in previous.get("windows", [])}
    return any(w.get("used_percent") is not None and before.get(w["label"]) is not None
               and w["used_percent"] > before[w["label"]] for w in row["windows"])


def ticket_spent(previous, row):
    """A saved reset was used: one fewer than before, and the one going first had not simply run out."""
    held, now_held = previous.get("reset_credits") or {}, row.get("reset_credits") or {}
    if held.get("count", 0) <= now_held.get("count", 0):
        return False
    expires = held.get("expires_at")
    return not expires or expires > row.get("fetched_at", 0)


def event_of(previous, row):
    """'full' when a window reaches 100%, 'reset' when one falls back near zero or a saved reset is
    spent, else None."""
    if row["status"] != "ok":
        return None
    spent = ticket_spent(previous, row)
    before = {w["label"]: w.get("used_percent") for w in previous.get("windows", [])} if comparable(previous, row) else {}
    event = None
    resets = {w["label"]: w.get("resets_at") for w in previous.get("windows", [])}
    for w in row["windows"]:
        old, new = before.get(w["label"]), w.get("used_percent")
        if old is None or new is None:
            continue
        if old < 100 <= new:
            return "full"
        was, now_at = resets.get(w["label"]), w.get("resets_at")
        # a minute's leeway for the provider's clock against ours
        due = not was or was <= row["fetched_at"] + 60 or (now_at and now_at - was > 3600)
        if old - new >= 20 and new <= 10 and due:  # a drop before its reset time is a correction, not a reset
            event = "reset"
    return event or ("reset" if spent and row.get("reset_credits") else None)


NEWS_SECONDS = 600  # what a reading brought (a jump, a crossing, a spent reset) stays news this long


RATE_SECONDS = 600  # a jump is the rise in used % over ten minutes

# x3: a window running out. Its pace is its rise over the last RATE_WINDOW, from its readings there (one at or
# before the window's start, and every one since); at that pace, a window still under 100% that would reach it in
# under HORIZON is SLOW. A window's readings are its own: a new reset time (beyond SAME_WINDOW, as a reset time
# wobbles by seconds) or a drop in its use starts them over, so a reset is never taken for use.
RATE_WINDOW = 15 * 60
HORIZON = 30 * 60
SAME_WINDOW = 600


def same_window(a, b):
    """Whether two reset times are one window's."""
    return (a is None) == (b is None) and (a is None or abs(a - b) <= SAME_WINDOW)


def exact(value):
    """A reading's number as the decimal it was read as: 55.3 is 553/10, not the binary float nearest it."""
    return Fraction(str(value))


def running_out(readings):
    """Whether a window's readings [(measured at, used %, resets at)], oldest first, the first at or before
    RATE_WINDOW before the last, say it runs out within HORIZON at its pace: its rise over the last RATE_WINDOW (the
    use at that window's start read between the two readings either side of it). Exact, in fractions of the numbers
    as read (exact()): an ETA of just HORIZON is not under it. A history shorter than RATE_WINDOW says nothing."""
    if len(readings) < 2:
        return False
    (t0, u0, _), (t1, u1, _), (at, used, _) = readings[0], readings[1], readings[-1]
    t0, u0, t1, u1, at, used = (exact(value) for value in (t0, u0, t1, u1, at, used))
    start = at - RATE_WINDOW
    if t0 > start:
        return False
    begun = u0 + (u1 - u0) * (start - t0) / (t1 - t0)
    rise, left = used - begun, 100 - used
    return rise > 0 and left > 0 and left * RATE_WINDOW < rise * HORIZON


def lasting(row, slow, now, good):
    """The SLOW labels `slow` that a row whose reading did not come in (failed, or grew old) keeps at `now`, each its
    own window's: while the good reading it was found at (`good`: label -> (measured at, used %, resets at), the last
    one taken into that window's pace) is under HORIZON old, and while the row shows that window still, no lower. A
    reading or two failing do not make the warning drop and come back; one that brings a new window (another reset
    time, same_window) or a lower use lets it go, and so do readings failing past the warning's own horizon, however
    new the old copies among them."""
    windows = {w.get("label"): w for w in row.get("windows", [])}
    kept = []
    for label in slow:
        reading, shown = good.get(label), windows.get(label)
        if reading is None or shown is None or now - reading[0] >= HORIZON:
            continue
        used = shown.get("used_percent")
        if same_window(reading[2], shown.get("resets_at")) and not (used is not None and used < reading[1]):
            kept.append(label)
    return kept


# x7: today's use, for the survival HUD's bar, read from one window (usage.today_window: its week over its 5 hours) on
# this computer's local date. It is the sum over the day's windows (a window is one reset period, new_window) of each
# one's last reading less its first that day, in the window's points: a window that began today counts from nothing,
# and for the one the day began in, a reading taken within DAY_EDGE before midnight (TokenTV was reading then) stands
# for midnight. Any fall within a window is a correction. The row's 'today' is that as a share of an even day
# (usage.even_day: a seventh of a week). It goes into the state folder with the snapshot, so a restart mid-day keeps it.
DAY_EDGE = 15 * 60
DAY_FIELDS = {"date": str, "label": str, "minutes": int, "base": (int, float), "used": (int, float),
              "at": (int, float), "carried": (int, float)}


def day_start(at):
    """The local midnight that began `at`'s day."""
    t = time.localtime(at)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def day_of(at):
    return time.strftime("%Y-%m-%d", time.localtime(at))


def new_window(day, value):
    """Whether the reading `value` is of a new window, not the one `day` follows: its reset time moved later than
    same_window allows, or, with no reset time known, its use fell to under half and below 10 %."""
    was, resets = day.get("resets_at"), value.get("resets_at")
    if was is not None and resets is not None:
        return resets - was > SAME_WINDOW
    return value["used_percent"] < min(10, day["used"] / 2)


def day_step(day, value, at):
    """An account's day after a good reading `value` of the window today's use is read from (of a known length),
    measured at `at`: {'date', 'label', 'minutes', 'resets_at', 'base', 'used', 'at', 'carried'}. Today's use is
    'used' (the window's last reading) less 'base' (its first today, or nothing for one begun today), plus 'carried'
    (the day's windows before it). An older reading changes nothing."""
    if value is None or value.get("used_percent") is None:
        return day
    used, resets, start = value["used_percent"], value.get("resets_at"), day_start(at)
    fresh = {"date": day_of(at), "label": value["label"], "minutes": window_minutes(value), "resets_at": resets,
             "base": used, "used": used, "at": at, "carried": 0}
    if not day or day.get("label") != value["label"]:
        return fresh  # the first reading, or another window read now: counted from here
    if at < day["at"]:
        return day
    today = day["date"] == fresh["date"]
    if new_window(day, value):  # begun its length before its reset time, else after the old one's last reading
        began = resets - 60 * fresh["minutes"] if resets is not None else day["at"]
        return dict(fresh, base=0 if began >= start - DAY_EDGE else used,
                    carried=day["carried"] + max(0, day["used"] - day["base"]) if today else 0)
    if today:  # the same window, risen or corrected
        return dict(day, used=used, at=at, resets_at=resets, minutes=fresh["minutes"])
    watched = day["at"] >= start - DAY_EDGE  # read just before midnight: that reading stands for it
    return dict(fresh, base=day["used"] if watched else used)


def today_share(day, now):
    """Today's use at `now` as a share of an even day (1.0: a seventh of the week), or None when it is not known: no
    reading of the window today, nor one in the DAY_EDGE before midnight (that one stands for the day's start)."""
    if not day or not even_day(day.get("minutes")):
        return None
    if day["date"] == day_of(now):
        points = day["carried"] + max(0, day["used"] - day["base"])
    elif day_start(now) - DAY_EDGE <= day["at"] < day_start(now):
        points = 0  # the day has only just begun, and nothing read since
    else:
        return None
    return points / even_day(day["minutes"])


def valid_day(day):
    """A day kept in the state folder, as day_step makes them, or None."""
    if not isinstance(day, dict) or not all(isinstance(day.get(k), t) and not isinstance(day.get(k), bool)
                                            for k, t in DAY_FIELDS.items()):
        return None
    resets = day.get("resets_at")
    if resets is not None and (isinstance(resets, bool) or not isinstance(resets, (int, float))):
        return None
    return {k: day[k] for k in (*DAY_FIELDS, "resets_at")}


def trail_of(row):
    """The good readings behind `row` for rates, oldest first: [(measured at, {label: used %})], the ones in the
    ten minutes before it and its own (a stale row keeps the windows and the time they were measured)."""
    since = row.get("last_success_at") or row.get("fetched_at")
    own = [(since, {w["label"]: w.get("used_percent") for w in row.get("windows", [])})] if since else []
    return [tuple(point) for point in row.get("trail") or ()] + own


def news_of(previous, row):
    """What this reading brought, for the hidden one-offs (`lockbox.py`): the sharpest rise in used % (per ten
    minutes, so a reading after a long gap is not a sudden jump), the thresholds crossed, the account's first rise
    of the day, its return after an hour or more without a rise, and a spent saved reset with the days it still had.
    Each item is {'kind', 'value', 'at'}."""
    at, out = row["fetched_at"], []
    if row["status"] != "ok":
        return out
    before = {w["label"]: w.get("used_percent") for w in previous.get("windows", [])} if comparable(previous, row) else {}
    jumps, crossed = [0], set()
    for w in row["windows"]:
        old, new = before.get(w["label"]), w.get("used_percent")
        if old is None or new is None:
            continue
        for then, used in trail_of(previous):  # the rise over the last ten minutes, or its pace over a longer gap
            was = used.get(w["label"])
            if was is not None and at > then:
                jumps.append((new - was) * RATE_SECONDS / max(RATE_SECONDS, at - then))
        crossed.update((t, w["label"]) for t in (70, 80, 90, 95, 100) if old < t <= new)
    if max(jumps) > 0:
        out.append({"kind": "jump", "value": max(jumps), "at": at})
    out += [{"kind": "crossed", "value": t, "label": label, "at": at} for t, label in sorted(crossed)]
    last = previous.get("rose_at")
    if rose(previous, row) and (not last or time.localtime(last)[:3] != time.localtime(at)[:3]):
        out.append({"kind": "first_today", "value": True, "at": at})
    if rose(previous, row) and last and at - last >= 3600:  # back at work after a break of an hour or more
        out.append({"kind": "back", "value": round((at - last) / 3600, 1), "at": at})
    held, now_held = previous.get("reset_credits") or {}, row.get("reset_credits")
    if now_held and ticket_spent(previous, row):
        expires = held.get("expires_at")
        out.append({"kind": "ticket_spent", "value": (expires - at) / 86400 if expires else 99, "at": at})
    return out


class UsageStore:
    def __init__(self, accounts, fetch=fetch_account, min_fetch_seconds=None):
        self.accounts = accounts
        self.fetch = fetch
        self.min_fetch_seconds = min_fetch_seconds or {}
        self.fetched = {}  # account key -> monotonic time of its last fetch
        self.failures = {}  # account key -> failed readings in a row (rate limited or an error)
        self.waits = {}  # account key -> (monotonic, wall, asked): not read again before; asked = the service said so
        self.lock = threading.Lock()
        self.updated_at = 0
        self.paces = {}  # (account key, window label) -> its readings for running_out, in memory only
        self.rows = {a["key"]: {"key": a["key"], "alias": a["alias"], "provider": a["provider"],
                               "status": "loading", "windows": [], "fetched_at": 0,
                               "identity_verified": False, "source": "mini"}
                     for a in accounts}

    def restore(self, snapshot):
        """Carry over when each account last rose (and its run's start) and its day (today's use) from the snapshot
        the last run wrote, so a restart does not make a second 'first use of the day', forget a break or start today
        over."""
        for key, old in (snapshot or {}).get("accounts", {}).items():
            if key in self.rows and isinstance(old, dict):
                for field in ("rose_at", "active_since"):
                    if isinstance(old.get(field), (int, float)) and not isinstance(old.get(field), bool):
                        self.rows[key][field] = old[field]
                if valid_day(old.get("day")):
                    self.rows[key]["day"] = valid_day(old["day"])

    def fetch_one(self, account):
        """This account's reading. Whatever goes wrong while reading it is its own error, named by its type only (a
        message may hold a token or a path): the other accounts' readings are kept all the same."""
        try:
            row = self.fetch(account)
            if not (isinstance(row, dict) and row.get("key") == account["key"] and isinstance(row.get("status"), str)
                    and isinstance(row.get("windows"), list) and isinstance(row.get("fetched_at"), (int, float))):
                raise TypeError("not a reading of this account")
            return row
        except Exception as error:
            return {"key": account["key"], "alias": account["alias"], "provider": account["provider"], "status": "error",
                    "error_code": "unexpected:" + type(error).__name__, "windows": [], "fetched_at": time.time(),
                    "identity_verified": False, "source": self.rows[account["key"]].get("source", "mini")}

    def refresh(self):
        started, wall = time.monotonic(), time.time()

        def due(account):
            """An account told to wait is due once either clock has passed its time (monotonic time may stand still
            while a computer sleeps); at the time its service gave, even before the account's own minimum. Else a
            few seconds of slack, so a five-minute account is not pushed to the next one-minute tick."""
            key = account["key"]
            mono, at, asked = self.waits.get(key, (0, 0, False))
            if started < mono and wall < at:
                return False
            if asked:
                return True
            return key not in self.fetched or started - self.fetched[key] + 15 >= self.min_fetch_seconds.get(account["provider"], 0)
        due = [a for a in self.accounts if due(a)]
        if not due:
            return
        with ThreadPoolExecutor(max_workers=min(4, len(due))) as executor:
            rows = list(executor.map(self.fetch_one, due))
        with self.lock:
            for account in due:
                self.fetched[account["key"]] = started
            for row in rows:
                self.schedule(row, started, wall)
                previous = self.rows[row["key"]]
                row["rose_at"] = row["fetched_at"] if rose(previous, row) else previous.get("rose_at")
                if rose(previous, row):  # the start of this run of work, kept while it goes on
                    going = previous.get("rose_at") and row["fetched_at"] - previous["rose_at"] < ACTIVE_SECONDS
                    row["active_since"] = previous.get("active_since") if going else row["fetched_at"]
                else:
                    row["active_since"] = previous.get("active_since")
                row["news"] = [item for item in previous.get("news", [])
                               if row["fetched_at"] - item["at"] < NEWS_SECONDS] + news_of(previous, row)
                row["trail"] = [point for point in trail_of(previous) if row["fetched_at"] - point[0] < RATE_SECONDS] \
                    if row["status"] == "ok" else previous.get("trail", [])
                peak = max((w.get("used_percent") or 0 for w in row.get("windows", [])), default=0)
                row["worry"] = (peak >= 90 or (bool(previous.get("worry")) and peak >= 85)  # on at 90, off below 85
                                if row["status"] == "ok" else previous.get("worry"))  # an outage changes nothing
                event = event_of(previous, row)  # a one-off for the animated faces: fireworks or a flop
                row["event"], row["event_at"] = (event, row["fetched_at"]) if event else (previous.get("event"), previous.get("event_at"))
                measured = row.get("measured_at")  # when the source measured it, if not just now
                if row["status"] in ("ok", "quota_unavailable"):
                    row["last_success_at"] = measured or row["fetched_at"]
                elif row["status"] == "stale" and row["windows"] and measured and measured >= previous.get("last_success_at", 0):
                    row["last_success_at"] = measured  # an old reading, but the newest there is: shown as it is, OLD
                elif row["status"] != "identity_mismatch" and previous.get("windows") and previous.get("last_success_at"):
                    row["error_code"] = row.get("error_code", row["status"])
                    row["status"] = "stale"
                    row["windows"] = previous["windows"]
                    if previous.get("reset_credits"):
                        row["reset_credits"] = previous["reset_credits"]
                    row["last_success_at"] = previous["last_success_at"]
                    row["identity_verified"] = previous.get("identity_verified", False)
                # x3: the windows running out, for the battery to blink (a reading not in keeps the last good one's)
                row["slow"] = (self.slow(row) if row["status"] == "ok" else
                               lasting(row, previous.get("slow") or [], wall, self.good(row["key"])))
                # x7: today's use goes on from a reading that came in; one that did not keeps the day as it was
                row["day"] = (day_step(previous.get("day"), today_window(row["windows"]), row["last_success_at"])
                              if row["status"] == "ok" else previous.get("day"))
                self.rows[row["key"]] = row
            self.updated_at = int(time.time())

    def slow(self, row):
        """The labels of `row`'s windows running out (running_out), its reading (one that came in) taken into their
        histories."""
        at, found, kept = row.get("last_success_at") or row["fetched_at"], [], set()
        for w in row["windows"]:
            used = w.get("used_percent")
            if used is None:
                continue
            key = (row["key"], w["label"])
            kept.add(key)
            readings = self.paces.setdefault(key, [])
            if not readings or at > readings[-1][0]:  # (a reading already taken, or an older one, adds nothing)
                if readings and (used < readings[-1][1] or not same_window(readings[-1][2], w.get("resets_at"))):
                    readings.clear()  # a new window, or a correction: its pace starts over
                readings.append((at, used, w.get("resets_at")))
            while len(readings) > 1 and readings[1][0] <= readings[-1][0] - RATE_WINDOW:
                readings.pop(0)  # one at or before the window's start is enough
            if running_out(readings):
                found.append(w["label"])
        for key in [key for key in self.paces if key[0] == row["key"] and key not in kept]:
            del self.paces[key]  # a window no longer reported
        return found

    def good(self, key):
        """The last good reading of each of account `key`'s windows, as taken into its pace: {label: (measured at,
        used %, resets at)}. Only a reading that came in goes there, never an old copy (lasting)."""
        return {label: readings[-1] for (owner, label), readings in self.paces.items() if owner == key and readings}

    def schedule(self, row, started, wall):
        """When a failing account is read next: when its service said (Retry-After, at most RETRY_CAP), else after a
        backoff that grows with each failure in a row; a reading that works starts it over. Other accounts are
        never held back by it."""
        key = row["key"]
        if row["status"] not in ("rate_limited", "error"):
            self.failures.pop(key, None)
            self.waits.pop(key, None)
            row.pop("retry_at", None)
            return
        self.failures[key] = self.failures.get(key, 0) + 1
        asked = row.get("retry_at")
        wait = min(RETRY_CAP, max(0, asked - wall)) if isinstance(asked, (int, float)) else backoff(self.failures[key])
        if wait:
            self.waits[key] = (started + wait, wall + wait, isinstance(asked, (int, float)))
            row["retry_at"] = int(wall + wait)  # for the dashboard: 'rate limited until HH:MM'
        else:
            self.waits.pop(key, None)
            row.pop("retry_at", None)

    def snapshot(self):
        with self.lock:
            rows = copy.deepcopy(self.rows)
            updated = self.updated_at
            good = {key: self.good(key) for key in rows}
        now = time.time()
        for key, row in rows.items():
            if row["status"] == "ok" and now - row.get("last_success_at", row["fetched_at"]) > STALE_SECONDS:
                row["status"] = "stale"
                row.setdefault("error_code", "snapshot_old")
            if row["status"] != "ok":  # OLD: the last good reading's SLOW, only while it is under HORIZON old
                row["slow"] = lasting(row, row.get("slow") or [], now, good[key])
            row["active"] = bool(row.get("rose_at")) and now - row["rose_at"] < ACTIVE_SECONDS
            row["today"] = today_share(row.get("day"), now)  # a share of an even day; None while not known
            by_label = {w["label"]: w for w in row["windows"]}
            for prefix, label in (("session", "5H"), ("weekly", "WEEK")):
                value = by_label.get(label, {})
                row[prefix + "_percent"] = value.get("used_percent")
                reset = value.get("resets_at")
                row[prefix + "_reset_minutes"] = max(0, int((reset - now + 59) // 60)) if reset else None
        return {"schema": 1, "updated_at": updated, "accounts": rows}
