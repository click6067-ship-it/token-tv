"""Polling owns provider requests; HTTP readers only see cached state."""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from token_tv.sources import fetch_account

# An account counts as working for this long after its used % last went up. It outlasts the slowest
# fetch below, so a steady worker keeps running between readings.
ACTIVE_SECONDS = 600
# Claude's usage endpoint answers frequent callers with 429s, so its accounts are read at most every
# five minutes even when the clock refreshes every minute.
MIN_FETCH_SECONDS = {"claude": 300}


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
        self.lock = threading.Lock()
        self.updated_at = 0
        self.rows = {a["key"]: {"key": a["key"], "alias": a["alias"], "provider": a["provider"],
                               "status": "loading", "windows": [], "fetched_at": 0,
                               "identity_verified": False, "source": "mini"}
                     for a in accounts}

    def restore(self, snapshot):
        """Carry over when each account last rose (and its run's start) from the snapshot the last run wrote,
        so a restart does not make a second 'first use of the day' or forget a break."""
        for key, old in (snapshot or {}).get("accounts", {}).items():
            if key in self.rows and isinstance(old, dict):
                for field in ("rose_at", "active_since"):
                    if isinstance(old.get(field), (int, float)) and not isinstance(old.get(field), bool):
                        self.rows[key][field] = old[field]

    def refresh(self):
        started = time.monotonic()
        # A few seconds of slack so a five-minute account is not pushed to the next one-minute tick.
        due = [a for a in self.accounts if a["key"] not in self.fetched
               or started - self.fetched[a["key"]] + 15 >= self.min_fetch_seconds.get(a["provider"], 0)]
        if not due:
            return
        with ThreadPoolExecutor(max_workers=min(4, len(due))) as executor:
            rows = list(executor.map(self.fetch, due))
        with self.lock:
            for account in due:
                self.fetched[account["key"]] = started
            for row in rows:
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
                if row["status"] in ("ok", "quota_unavailable"):
                    row["last_success_at"] = row["fetched_at"]
                elif row["status"] != "identity_mismatch" and previous.get("windows") and previous.get("last_success_at"):
                    row["error_code"] = row.get("error_code", row["status"])
                    row["status"] = "stale"
                    row["windows"] = previous["windows"]
                    if previous.get("reset_credits"):
                        row["reset_credits"] = previous["reset_credits"]
                    row["last_success_at"] = previous["last_success_at"]
                    row["identity_verified"] = previous.get("identity_verified", False)
                self.rows[row["key"]] = row
            self.updated_at = int(time.time())

    def snapshot(self):
        with self.lock:
            rows = copy.deepcopy(self.rows)
            updated = self.updated_at
        now = time.time()
        for row in rows.values():
            if row["status"] == "ok" and now - row.get("last_success_at", row["fetched_at"]) > 900:
                row["status"] = "stale"
                row.setdefault("error_code", "snapshot_old")
            row["active"] = bool(row.get("rose_at")) and now - row["rose_at"] < ACTIVE_SECONDS
            by_label = {w["label"]: w for w in row["windows"]}
            for prefix, label in (("session", "5H"), ("weekly", "WEEK")):
                value = by_label.get(label, {})
                row[prefix + "_percent"] = value.get("used_percent")
                reset = value.get("resets_at")
                row[prefix + "_reset_minutes"] = max(0, int((reset - now + 59) // 60)) if reset else None
        return {"schema": 1, "updated_at": updated, "accounts": rows}
