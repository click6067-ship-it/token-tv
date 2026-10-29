# Reading usage from CodexBar

Already watching your limits with [CodexBar](https://github.com/steipete/CodexBar)? TokenTV can take
CodexBar's usage JSON and put it on a ~$5 AliExpress Wi-Fi desk clock, with no firmware flashing.
CodexBar keeps doing the sign-in and fetching; TokenTV only reads what CodexBar prints, draws the
picture and uploads it to the clock's stock photo album.

## What has been checked

CodexBar CLI 0.74.0 (Linux x86_64 release tarball) on Ubuntu 24.04, 2026-10-11, with real accounts:

| Provider | CodexBar call | Result on the clock |
|---|---|---|
| Claude | `codexbar usage --provider claude --source oauth --format json` | 5-hour and weekly windows |
| Codex | `codexbar usage --provider codex --format json` (CodexBar used its `oauth` source) | Weekly window. This account reported no 5-hour window, so that stays a dash |
| Claude, default source | `codexbar usage --provider claude --format json` | Failed: on Linux CodexBar fell back to Claude Code's `/usage` and could not read the output of Claude Code 2.1.289. Set `"codexbar_source": "oauth"` |

`codexbar serve` (`GET /usage`) returned the same entries for both providers. TokenTV accepts the
CodexBar input for `claude`, `codex`, `copilot` and `antigravity` accounts. Copilot has not been checked with a real
account yet: its mapping follows CodexBar's [Copilot notes](https://github.com/steipete/CodexBar/blob/main/docs/copilot.md)
(sign in once with `codexbar config login --provider copilot`). Copilot and Antigravity accounts can only be read
through CodexBar. Google's two are one account on the clock: an Antigravity account reads CodexBar's
`antigravity` entry, or with `"codexbar_provider": "gemini"` its `gemini` one (the Gemini CLI quota, a daily
window, or the Gemini app's 5-hour and weekly limits); a config that still says `"provider": "gemini"` is read
as Antigravity. Neither has been checked with a real account yet.
CodexBar's macOS app has not been tried.

## Config

```json
{
  "device_url": "http://<clock-ip>",
  "accounts": [
    {"key": "claude_a", "alias": "CLAUDE A", "provider": "claude", "email": "you@example.com",
     "codexbar_command": "codexbar", "codexbar_source": "oauth"},
    {"key": "codex_a", "alias": "CODEX A", "provider": "codex", "email": "you@example.com",
     "codexbar_command": "codexbar"},
    {"key": "copilot_a", "alias": "COPILOT A", "provider": "copilot", "email": "you@example.com",
     "codexbar_command": "codexbar"},
    {"key": "anti_a", "alias": "ANTI A", "provider": "antigravity", "email": "you@example.com",
     "codexbar_command": "codexbar"}
  ]
}
```

- `codexbar_command`: the CodexBar CLI, a name on `PATH` or a full path. Each poll runs
  `<command> usage --provider <provider> --format json`.
- `codexbar_source` (optional): passed as `--source` (`auto`, `web`, `cli`, `oauth`, `api`).
  Without it, CodexBar uses its own setting.
- `codexbar_url` instead of `codexbar_command`: a `codexbar serve` address such as
  `http://127.0.0.1:8080/usage`. CodexBar's config then picks the source. The address may carry
  `?provider=` but no user name, password or other query. CodexBar asks for a bearer token on
  non-loopback addresses and TokenTV does not send one, so run TokenTV on the same computer.
- `source_home` (optional): runs CodexBar with that CLI home (`CLAUDE_CONFIG_DIR` or `CODEX_HOME`),
  for example for a second Codex account.

Then `token-tv doctor --live` and `token-tv run`, as in [setup](setup.md). The dashboard lists the
account's source as CodexBar.

## What is read

- The `primary` and `secondary` windows. A 300-minute window is the 5-hour limit and a 10080-minute
  window is the weekly limit. A window without a length is shown without a label; TokenTV does not
  guess one from CodexBar's display names. Copilot's windows carry no length: its primary is the
  monthly premium-request allowance (`MO`) and its secondary is chat. GitHub gives no reset time, so
  Copilot's reset stays a dash.
- Model-only windows (for example Claude's "Fable only") and `tertiary` are not shown, so they never
  replace the weekly reading.
- A missing window is a dash, never 0%.
- If CodexBar reports an account email (it did for Codex), every reported email must match `email`
  or the account shows a mismatch. CodexBar's Claude OAuth output carried no email, so that account is unverified and
  `doctor --live` says so.
- When CodexBar fails, the account shows an error status. CodexBar's error text is not kept.
