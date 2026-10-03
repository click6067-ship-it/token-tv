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
        value = data.get(key) or {}
        item = window(label, value.get("utilization"), value.get("resets_at"), duration)
        if item:
            result.append(item)
    return result


def normalize_codex(data):
    result = []
    limits = data.get("rateLimits") or {}
    for key in ("primary", "secondary"):
        value = limits.get(key) or {}
        duration = value.get("windowDurationMins")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            duration = None
        label = {300: "5H", 10080: "WEEK"}.get(duration, "WINDOW")
        item = window(label, value.get("usedPercent"), value.get("resetsAt"), duration)
        if item:
            result.append(item)
    return result


def normalize_grok(data):
    config = data.get("config") or {}
    percent = config.get("creditUsagePercent")
    cycle = config.get("currentPeriod") or {}
    reset = cycle.get("end") or config.get("billingPeriodEnd")
    item = window("BUDGET", percent, reset)
    if item:
        return [item]
    # CLI credits are a billing budget, not a fabricated web-message quota.
    limit = (data.get("monthlyLimit") or {}).get("val")
    used = ((data.get("usage") or {}).get("includedUsed") or {}).get("val")
    if isinstance(limit, (int, float)) and limit > 0 and isinstance(used, (int, float)):
        item = window("BUDGET", used / limit * 100,
                      (data.get("billingCycle") or {}).get("billingPeriodEnd"))
        if item:
            return [item]
    return []
