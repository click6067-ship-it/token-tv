"""Small, explicit usage windows. Missing measurements stay missing."""
import math
from datetime import datetime


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if math.isfinite(value) and value > 0 else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.timestamp()) if parsed.tzinfo else None
        except ValueError:
            pass
    return None


class FormatChanged(ValueError):
    """A reply in a shape TokenTV does not read: the service changed its format (TokenTV needs an update)."""


def part(data, key):
    """`data[key]` when it is an object, {} when it is missing; FormatChanged when either is something else."""
    if not isinstance(data, dict):
        raise FormatChanged(key)
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise FormatChanged(key)
    return value


def window(label, percent, reset=None, duration=None):
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return None
    if not math.isfinite(percent) or percent < 0:
        return None
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        duration = None
    return {"label": label, "used_percent": float(percent),
            "resets_at": timestamp(reset), "duration_minutes": duration}


def normalize_claude(data):
    result = []
    for key, label, duration in (("five_hour", "5H", 300), ("seven_day", "WEEK", 10080)):
        value = part(data, key)
        item = window(label, value.get("utilization"), value.get("resets_at"), duration)
        if item:
            result.append(item)
    return result


def normalize_codex(data):
    result = []
    limits = part(data, "rateLimits")
    for key in ("primary", "secondary"):
        value = part(limits, key)
        duration = value.get("windowDurationMins")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            duration = None
        label = {300: "5H", 10080: "WEEK"}.get(duration, "WINDOW")
        item = window(label, value.get("usedPercent"), value.get("resetsAt"), duration)
        if item:
            result.append(item)
    return result


def reset_credits(data):
    """Codex's saved limit resets: {'count', 'expires_at'} with the soonest expiry of those still
    available, or None when the reply has no such record."""
    record = data.get("rateLimitResetCredits") if isinstance(data, dict) else None
    count = record.get("availableCount") if isinstance(record, dict) else None
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return None
    expiry = [timestamp(item.get("expiresAt")) for item in record.get("credits") or []
              if isinstance(item, dict) and str(item.get("status", "")).lower() == "available"]
    expiry = [at for at in expiry if at]
    return {"count": count, "expires_at": min(expiry) if expiry else None}


def normalize_codexbar(entry):
    """One provider entry of CodexBar's usage JSON (`codexbar usage --format json`, `serve` GET /usage).
    Only the primary and secondary slots: tertiary and extra windows are model-scoped and would
    overwrite the weekly reading if they shared its label."""
    result, labels = [], []
    usage = part(entry, "usage")
    # Copilot's slots carry no length: the primary is the monthly premium-request allowance, the secondary chat.
    unnamed = {"primary": "MONTH", "secondary": "CHAT"} if entry.get("provider") == "copilot" else {}
    for key in ("primary", "secondary"):
        value = part(usage, key)
        if not value:
            continue
        duration = value.get("windowMinutes")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            duration = None
        label = {300: "5H", 1440: "DAY", 10080: "WEEK"}.get(duration) or unnamed.get(key, "WINDOW")
        # Readings are compared window by window, so a window keeps one name: an unnamed second window is always
        # WINDOW2, and a second window as long as the first gets a 2.
        if label in labels or (key == "secondary" and label == "WINDOW"):
            label += "2"
        labels.append(label)
        item = window(label, value.get("usedPercent"), value.get("resetsAt"), duration)
        if item:
            result.append(item)
    return result


def normalize_grok(data):
    config = part(data, "config")
    percent = config.get("creditUsagePercent")
    cycle = part(config, "currentPeriod")
    reset = cycle.get("end") or config.get("billingPeriodEnd")
    item = window("BUDGET", percent, reset)
    if item:
        return [item]
    # CLI credits are a billing budget, not a fabricated web-message quota.
    limit = part(data, "monthlyLimit").get("val")
    used = part(part(data, "usage"), "includedUsed").get("val")
    if isinstance(limit, (int, float)) and limit > 0 and isinstance(used, (int, float)):
        item = window("BUDGET", used / limit * 100, part(data, "billingCycle").get("billingPeriodEnd"))
        if item:
            return [item]
    return []
