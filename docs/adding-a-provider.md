# Adding a service (provider)

TokenTV reads Claude, Codex and Grok today. A new service is more than one function: the name is
listed in several places. This is the full list as of 2026-10-04; an AI agent can follow it.

**First check the service exposes usage you can read** (percent used and reset time) through its
own signed-in CLI or a documented API. If it does not, it cannot be added honestly.

| Where | What to add |
| --- | --- |
| `token_tv/sources.py` | allowed name in `load_config`; CLI home variable in `scoped_env`; a `<name>_payload()` that reads usage with the CLI's own login; an identity check; a branch in `fetch_account`; a branch in `logged_in_email` |
| `token_tv/usage.py` | `normalize_<name>()` turning the payload into windows (`label`, `used_percent`, `resets_at`) |
| `token_tv/cli.py` | `PROVIDERS` entry: CLI command, default home, login file, login hint |
| `token_tv/connect.py` | `DEFAULT_HOMES` entry and a `login_command` branch |
| `token_tv/display.py` | `PROVIDERS` order and `PROVIDER_INK` colour |
| `token_tv/themes.py` | colours in `ACCENT` (neon/retro/hud), Pixel Retro scene seed and sky, `glyph()` mark |
| `token_tv/space.py` | bubble colour if it should differ |
| `token_tv/assets/<name>-pixel.png` + `token_tv/web_assets.py` | pixel mascot and its allowlist entry |
| `token_tv/web/app.js` | `PROVIDERS`, `COMPANIES`, scene seed |
| `tests/` | a payload → windows test with sample JSON, never real account data |

Limits: every clock face shows at most three rows. With more than three services configured, the
first three in `PROVIDERS` order are shown. Missing readings must stay a dash, never 0%.
