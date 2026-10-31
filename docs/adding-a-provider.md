# Adding a service (provider)

TokenTV reads Claude, Codex, Grok and (through CodexBar) Copilot and Antigravity today. A new service is more than one function: the name is
listed in several places. This is the full list as of 2026-10-31; an AI agent can follow it, and
`tests/test_providers.py` fails until every place has the new name.

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
| `token_tv/arcade.py` | the Arcade scene (Arcade is the default face): a `<name>_scene(frame, draw, box, f, span, active, s, plan)` and its `SCENES` entry; `scene_plan` if it needs more than the used % and the mood |
| `token_tv/events.py` | a branch in `event_scene` for its one-offs: `reset` (a window starts over) and `full` (a window runs out) |
| `tests/` | a payload → windows test with sample JSON, never real account data; `tests/test_providers.py` checks the drawing entries above for every service `load_config` accepts |

Limits: every account gets its own row, at most four; past four the clock keeps the accounts in use,
then the fullest. Missing readings must stay a dash, never 0%.

Until its Arcade scene and events are drawn, a service plays as a plain stand-in pet on Arcade (it walks while
working, hops at a reset, flops when full), so a first try never stops the clock; the other faces need their
entries above. A scene that shows a gauge must show the real reading or none: never a made-up value.

A service that CodexBar already reads can come in through CodexBar instead of its own reader, as
Copilot and Antigravity do: allow it in `load_config` and `check_codexbar`, name its windows in
`normalize_codexbar`, then add the drawing entries above. New clock styles take each service's
colour from `BRAND` in `token_tv/display.py`.
