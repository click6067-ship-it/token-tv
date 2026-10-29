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
    usage = entry.get("usage")
    # Copilot's slots carry no length: the primary is the monthly premium-request allowance, the secondary chat.
    unnamed = {"primary": "MONTH", "secondary": "CHAT"} if entry.get("provider") == "copilot" else {}
    for key in ("primary", "secondary"):
        value = usage.get(key) if isinstance(usage, dict) else None
        if not isinstance(value, dict):
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
