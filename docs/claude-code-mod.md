# Your agents' moments on the clock: Claude Code and Codex

On the Arcade face, TokenTV's pets also show what your agents are doing right now:

- **Claude Code waits for you.** When a permission prompt opens, Clawd raises a hand, with the readout
  `NEEDS YOU`, and has the clock to itself (the other services' pets come back after). After 5 minutes unanswered
  it hops; after 15 it holds up a sign. Once you answer (yes or no) or the turn ends, the usual face comes back,
  even while the command you allowed is still running. After 30 minutes unanswered it gives up and
  goes back to the usual face too. With several Claude Code sessions, the hand stays up while any one of them
  waits, and the 30 minutes count from the first prompt of that wait: then every prompt still open is let go
  together, and the next one to open starts a new wait at the raised hand.
- **A turn is done.** When a Claude Code turn ends, Clawd bows once, with the readout `DONE`; when a Codex turn
  ends, the Codex cloud bows. At most one bow a minute, Claude and Codex together: a turn that ends inside that
  minute gets no bow, and none is saved for later. A waiting prompt always comes first.
- **A pat or a snack.** Type `/tokentv pet` or `/tokentv snack` in Claude Code: Clawd shows hearts (`PETTED`) or
  eats a cookie (`SNACKING`) for one loop. One at a time: a press while one is still to come or playing is dropped,
  not saved for later, and so is one while Claude Code waits for you.
- **A break.** Not from your agents but from your usage: after an hour of work on any of your accounts (an account
  is at work while its usage rose in the last ten minutes) since the last ten minutes with none at work, the pets on
  the clock drink a glass of water or stretch, one or the other, for one loop (`DRINKING`, `STRETCHING`). The next
  hour counts from there. A waiting prompt comes first; the break follows it, unless you took a break meanwhile.
  While an account at work cannot be read (rate limited, an outage), that time counts as neither work nor a break,
  for up to an hour.

Every change reaches the clock as the animation it is playing finishes its loop, never in the middle of one, and
a moment that does not change the picture sends nothing to the clock.

## Claude Code

Install the TokenTV plugin (Claude Code 2.1.275 or later) in a Claude Code session:

```
/plugin install tokentv --marketplace click6067-ship-it/token-tv
```

or add the marketplace first and install from it: `/plugin marketplace add click6067-ship-it/token-tv`, then
`/plugin install tokentv@token-tv`. To try a copy of this repository without installing:
`claude --plugin-dir ./claude-plugin`.

The plugin is a mod: a few lines of TypeScript that run inside Claude Code (`claude-plugin/hooks/register.ts`).
It watches Claude Code's own permission decision for each tool call, how Claude Code draws that call (running, as
soon as you said yes), the end of that call and the end of each turn, and changes none of them. It adds one slash
command, `/tokentv`, with two words after it: `/tokentv pet` and `/tokentv snack` (they touch nothing of Claude's
turn). Anything else after `/tokentv` sends nothing; the command says so, and says when no TokenTV is running on
this computer. It finds the TokenTV running on this computer from TokenTV's state
folder, beside the config that `token-tv start` uses
(`~/.config/token-tv/state`, or under `XDG_CONFIG_HOME`); for another config, set `TOKEN_TV_CONFIG` to its path in
the environment Claude Code runs in. Give it as an absolute path: a relative one like `config.json` is looked for
in the folder the Claude Code session started in (and TokenTV's in the folder TokenTV started in), which is seldom
the same place. With no TokenTV running it does nothing.

On Windows the plugin installs, but the mod sends nothing for now (`/tokentv` says so). There TokenTV has no
socket, and Claude Code's own requests over TCP follow a redirect wherever it points, whatever the mod asks
(measured with Claude Code 2.1.289), so a moment's name could leave this computer. Codex's `token-tv notify` and
everything else in TokenTV work on Windows as they do elsewhere.

## Codex

Codex runs a program of your choice when a turn ends. Add one line to `~/.codex/config.toml`, the one that
matches how you run TokenTV:

- installed with pip, pipx or uv tool: `notify = ["token-tv", "notify"]`
- run with uvx: `notify = ["uvx", "token-tv", "notify"]`
- run with npx: `notify = ["npx", "--yes", "token-tv", "notify"]`

For another config, add its path: `notify = ["token-tv", "notify", "--config", "/path/to/config.json"]`. Codex
takes one notify program; if you already have one, call `token-tv notify` from it with the same JSON argument.
`token-tv notify` reacts only to `agent-turn-complete`, prints nothing and is done within two seconds. With npx,
the very first run prepares TokenTV for about a minute; later runs are quick.

## What is sent, and what is kept

Only the moment's name, and only to the TokenTV on this computer: `claude.ask` (a prompt is waiting for you),
`claude.answered` (you answered that prompt, or it is over), `claude.end` (a Claude Code turn ended),
`claude.pet` and `claude.snack` (`/tokentv pet`, `/tokentv snack`) or `codex.end` (a Codex turn ended), as
`{"moment": "<name>"}` in a `POST /moment`; the words you type after `/tokentv` are not sent, only the name. On
Linux and macOS it goes only over TokenTV's own socket in its state folder (`live.sock`), where no proxy or redirect
can take it anywhere else;
with no socket there, nothing is sent. On Windows only `token-tv notify` sends: to TokenTV's port on `127.0.0.1`,
through no proxy and following no redirect. Your prompts, commands, file paths, outputs and session ids never
leave the mod or `token-tv notify`.

TokenTV keeps the moments in memory only: nothing is logged, nothing is written to disk, and a restart forgets
them. It takes moments only from this computer, by its own name, never from a web page. What goes to the clock
is the picture, as for everything else TokenTV shows.

## Turning it off

- Claude Code: `/plugin disable tokentv` (or `/plugin uninstall tokentv`).
- Codex: remove the `notify` line.
- On any face other than Arcade, the moments are not shown.

## Good to know

- The mod sees your answer as Claude Code draws the call again (running, or refused). Where no such drawing names
  the call (a desktop app older than that), the hand comes down when the call is over instead: after you approve a
  long command there, it stays up until the command finishes.
- In auto mode, Claude Code's classifier (not you) settles most calls, and those raise no hand; an ask rule or a
  hook that asks you still does. Where an organization manages Claude Code, the mod cannot read the permission
  mode, and auto mode's checks may briefly raise the hand.
- With several Claude accounts on the clock, every Claude pet shows the moment: Claude Code does not say which
  account a session uses.
- TokenTV and the agents have to run on the same computer.
- On Windows an old address left by a TokenTV that did not stop cleanly (ended from Task Manager, say) may name a
  port another program holds now: `token-tv notify` sends it the name `codex.end`, which stays on this computer.

## For developers

The endpoint takes exactly `{"moment": "<name>"}` (JSON, at most 256 bytes), the name one of the six above, and
answers `204` at once; anything else gets a `4xx` and changes nothing. Its `204` to a `claude.ask` says, in a
`TokenTV-Wait-Age` header, how many seconds the wait that ask joined has lasted, so the mod sends no answer after
TokenTV has let that wait go. A
`GET /moment` is no moment (`405`, `Allow: POST`). A moment's request has 2 seconds to arrive whole, the
dashboard's other requests 10; one that runs out is answered `408`, and a moment that came whole but late counts
for nothing. The moments' rules are in `token_tv/moments.py` (time comes from
`moments.CLOCK`, which tests replace with a fake clock; the break's hour from the readings' times on the wall clock,
`time.time()`, and `moments.RANDOM` picks each break), the clock timing in `token_tv/live.py` (`sync_moments`;
on an SD_PRO a loop is its GIF's pictures, each for its delay but at least `device_frame_ms`, 142 by default).
Tests: `python3 -B -m unittest discover -s tests` and `claude plugin test claude-plugin`.
