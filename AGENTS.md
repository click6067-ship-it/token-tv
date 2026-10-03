# Agent guide

TokenTV draws AI usage limits on a 240×240 desk clock. Python 3.10+, Pillow, no other runtime deps.

## Run without accounts or a clock

```bash
pip install -e .
token-tv demo --out token-tv-demo     # every face from sample data
python3 -B -m unittest discover -s tests
```

## Rules

- Never read, print or copy credential files (`.credentials.json`, `auth.json`, Keychain items) or
  real config files. Tests use `token_tv/sample.py` and temporary folders.
- Do not publish, push, open issues or create releases on the user's behalf.
- A missing reading is a dash, an old one is marked OLD. Never turn unknown into `0`.
- `token-tv setup --yes --<provider>-email ...` is non-interactive and never overwrites a config.
  `token-tv doctor --live` contacts providers; ask the user before running it.

## Make a clock face

Follow `docs/clock-faces.md`: write a render function, add it to `RENDERERS` and `STYLES`, render
with `token-tv demo`, and look at the 240×240 result at real size. It then appears in the dashboard's
Themes list as a Local face and can be applied to the clock without any upstream change.
