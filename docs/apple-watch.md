# Apple Watch complication

The ~$5 clock stays the live display. If you also want a number on your wrist, the computer that
already runs TokenTV serves a small JSON file, `/watch.json`, and a JSON complication app on the
iPhone and Apple Watch shows one value from it. No TokenTV app, no extra login on the phone.

## What has been checked

- `/watch.json` on a Linux host with seven real accounts (2026-10-12): every account gets the same
  number, window and OLD / NO DATA state the clock shows.
- Not checked yet: a real Apple Watch, and which complication apps accept a plain `http://` address.

## 1. Let the phone reach the computer

TokenTV listens on `127.0.0.1` unless you tell it otherwise. Start it on your home network address:

```bash
token-tv run --host 0.0.0.0        # or the computer's LAN IP, e.g. --host 192.168.0.20
```

On the iPhone, on the same Wi-Fi, open `http://<computer-ip>:8787/watch.json` in Safari. You should
see JSON like the sample below. Anyone on that network can also open the dashboard and switch the
clock face, so do not forward this port to the internet. It answers only by the computer's own addresses and
names (its host name, `name.local`, `localhost`), so a web page that renames itself to your computer
gets nothing; open it by the computer's IP, as above.

## 2. Add the complication

Install a free app that turns a JSON URL into a complication, for example
[Complicator](https://apps.apple.com/us/app/-/id6758154567) or
[ComplicaJSON](https://www.complicajson.com/). Add a data source with:

- URL: `http://<computer-ip>:8787/watch.json`
- JSON path: `accounts.claude_a.used_percent` (a number), `accounts.claude_a.used` (0–1, for a
  gauge) or `accounts.claude_a.text` (`44% WK`)

Then add the app's complication to a watch face. watchOS decides how often complications refresh,
usually every 15–30 minutes, so the watch lags the clock.

## Fields

Accounts are keyed by the name the clock shows: `CLAUDE A` is `claude_a`, `CODEX B` is `codex_b`.
Config keys are not included.

```json
{
  "updated_at": 1791803649,
  "summary": "CLAUDE A 44% WK · CODEX A 12% 5H OLD · GROK A NO DATA",
  "accounts": {
    "claude_a": {"label": "CLAUDE A", "used_percent": 44, "used": 0.44, "window": "WK",
                 "resets_in": "1d 2h", "resets_at": 1791897249, "text": "44% WK", "state": "ok"},
    "codex_a": {"label": "CODEX A", "used_percent": 12, "used": 0.12, "window": "5H",
                "resets_in": "1h 0m", "resets_at": 1791807249, "text": "12% 5H OLD", "state": "old"},
    "grok_a": {"label": "GROK A", "used_percent": null, "used": null, "window": null,
               "resets_in": "--", "resets_at": null, "text": "NO DATA", "state": "missing"}
  }
}
```

| Field | Meaning |
|---|---|
| `used_percent` | Used share of the tightest window, 0–100. `null` when nothing was reported, never 0 |
| `used` | The same as 0–1, for gauge complications |
| `window` | `5H`, `WK` or `BUD`, as on the clock |
| `resets_in`, `resets_at` | Time left as text (computed when the watch asks), and the reset as a Unix time |
| `text` | What the clock row says, e.g. `44% WK` or `NO DATA` |
| `state` | `ok`, `old` (the last good value; the latest check failed) or `missing` |
| `summary` | Every account on one line |

## Away from home

The watch can only reach the address while it is on the same network as the computer. TokenTV does
not upload your usage anywhere. If you want the number outside, put the computer and the phone on a
private network you already trust (a VPN such as Tailscale) and use that address; this has not been
checked with a watch yet.
