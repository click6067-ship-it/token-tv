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
- **A risky command.** When Claude Code runs a Bash command of a short list of risky kinds (`rm -rf`, `git push
  --force` or `-f`, `git reset --hard`, `git clean -fd`, `DROP TABLE` or `DROP DATABASE` given to a database client,
  `mkfs`, `dd of=/dev/…`, `chmod -R 777 /`), Clawd stands trial for one loop: Judge Clawd's verdict on it in the
  dock (`ORDER!`), or its own `OBJECTION!`, one or the other at random. At most once a day (24 hours from the last
  one); one inside that day is simply skipped. A prompt waiting for you comes first; the courtroom follows it if it
  can reach the clock within two minutes of the command. One held longer (its prompt left open, say) is dropped, not
  played later, and the day's courtroom is still to come.
- **A deleted file.** When a Bash command deletes files (`rm`, `git rm`, `find … -delete`, `unlink`; even one file)
  and succeeds, a little ghost of a page floats round Clawd's scene for a minute (`BOO!`): either drifting past
  whatever Clawd does, or with Clawd watching it and waving. More deletions in that minute keep it there a minute
  more, in the same picture (nothing new goes to the clock).
- **A rude prompt.** A prompt you type in capitals (at least 8 letters, four in five of them capitals) or with a
  swear in it turns Clawd's back for a minute (`SULKING`, a foot tapping, a glare over its shoulder now and then).
  The next calm prompt, or the minute's end, turns it back round, with a heart (`FORGIVEN`, one loop). A sulking
  Clawd does not bow: a turn that ends while its back is turned, the rude prompt's own turn included, gets no `DONE`.
- **A failed tool, a compaction.** A tool call that ran and failed makes Clawd dizzy for one loop (`DIZZY`); a
  compaction of the conversation makes it squeeze its head (`COMPACTING`), a thought bubble popping out at each
  squeeze. At most one of the two a minute, and both give way to everything above.
- **What Claude is thinking.** While a turn runs, the readout says Claude Code's own spinner word in place of what
  Clawd does (`PONDERING`; up to 12 letters in the readout's own size, 13 or 14 in its small letters on the same
  line). It changes at most once a minute, counted from when a word can be read on the clock (behind `SLOW`, `BOO!`
  or `SULKING` it cannot), and goes when the turn ends, cut short or not. A moment's own word, a waiting prompt's
  `NEEDS YOU`, `DONE` and `SLOW` are never covered by it.

Every change reaches the clock as the animation it is playing finishes its loop, never in the middle of one, and
a moment that does not change the picture sends nothing to the clock. The ghost, the back turned and the word stay
in the picture the clock loops; any of the one-off moments above hides them for its loop while their minutes run on.

## Claude Code

Install the TokenTV plugin (Claude Code 2.1.275 or later) in a Claude Code session:

```
/plugin install tokentv --marketplace click6067-ship-it/token-tv
```

or add the marketplace first and install from it: `/plugin marketplace add click6067-ship-it/token-tv`, then
`/plugin install tokentv@token-tv`. To try a copy of this repository without installing:
`claude --plugin-dir ./claude-plugin`.

The plugin is a mod: TypeScript that runs inside Claude Code (`claude-plugin/hooks/register.ts`). It watches
Claude Code's own permission decision for each tool call, how Claude Code draws that call (running, as soon as you
said yes), each Bash command as it is called (only to tell whether it is risky or deletes files), the end of each
call (whether it failed), each prompt you type (only to tell whether it is in capitals or swears), compactions,
the spinner's word and the end of each turn, and changes none of them: nothing is blocked, rewritten or delayed.
What it reads it keeps nowhere. It adds one slash command, `/tokentv`: `/tokentv pet` and `/tokentv snack` (they
touch nothing of Claude's turn), and `/tokentv sound on` and `/tokentv sound off` (below). Anything else after
`/tokentv` sends nothing; the command says so, and says when no TokenTV is running on this computer. It finds the
TokenTV running on this computer from TokenTV's state
folder, beside the config that `token-tv start` uses
(`~/.config/token-tv/state`, or under `XDG_CONFIG_HOME`); for another config, set `TOKEN_TV_CONFIG` to its path in
the environment Claude Code runs in. Give it as an absolute path: a relative one like `config.json` is looked for
in the folder the Claude Code session started in (and TokenTV's in the folder TokenTV started in), which is seldom
the same place. With no TokenTV running it does nothing.

What counts, exactly. A command is read as a shell reads it: words in quotes, comments, here-documents and
redirections are data (`echo "rm -rf x"` and `git commit -m "rm -rf build"` are nothing), while `;`, `&&`, `|`,
`$(…)`, `bash -c '…'`, `find … -exec` and wrappers such as `sudo`, `env` or `timeout` lead to the commands they
run; `command -v rm`, `type rm`, `which rm` and `hash rm` only look a command up. Risky: `rm` both recursive and
forced (`-rf`, `-fr`, `-r -f`, `--recursive --force`), `git push` with `--force`, `-f` or `--force-with-lease`, or
a refspec with a `+` (`git push origin +main`), `git reset --hard`, `git clean` forced with directories and not a
dry run, a database client (`psql`, `mysql`, `sqlite3` and the like) given `DROP TABLE` or `DROP DATABASE` as SQL
(in a string, a quoted name or a comment it is data, as in `psql -c "SELECT 'DROP TABLE x'"`; where the SQL runs a
string as a statement, with `EXECUTE`, `PREPARE` or a `DO` block, its strings count too), `mkfs` (and
`mkfs.ext4`…), `dd` with `of=/dev/…`, and `chmod -R 777 /`. Deleting: `rm` with something to delete, `git rm` (not
`--cached`, not a dry run), `find … -delete` (or `-exec rm`; a value such as `-name '-delete'` is none) and
`unlink`. A command is read in one pass, so a long one reaches Claude Code at once. A prompt counts only when you
typed it (here, or through Remote Control), never a notification or another session's message; its letters of every
script count, so a Korean prompt with an English abbreviation in it is no shouting. The swears are two short lists
at the end of `register.ts`, whole English words (`fuck`, `shit`, `damn`, `wtf`, …) and Korean words starting so
(`씨발`, `시발` but not `시발점`, `병신` but not `병신년`, …): edit them there. A failed call is one Claude Code
reports as an error after it ran; one you refused, one a rule, a hook or auto mode refused, and one cut short are
none.

**Sounds.** `/tokentv sound on` plays a short sound on this computer when a permission prompt starts waiting for
you and when a turn is done (one each time, whatever the clock shows); `/tokentv sound off` stops them at once.
They are off until you turn them on, and the setting is kept in Claude Code's own store for the plugin, so it holds
in every session until you change it. Nothing goes to TokenTV for them. They are the plugin's own two clips
(`claude-plugin/sounds/`, under half a second each), played by Claude Code's own player: on macOS they sound; a
Linux or Windows terminal has no player in Claude Code (2.1.289) and stays silent. (Where Claude Code itself runs
with a web audio player, as its desktop app may, it plays them that way; not tried.)

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
`claude.stop` (a turn that showed a thinking word was cut short), `claude.pet` and `claude.snack` (`/tokentv pet`,
`/tokentv snack`), `claude.risky`, `claude.deleted`, `claude.rude`, `claude.calm`, `claude.failed`,
`claude.compact`, `claude.word:` and the spinner's word (one word of 1 to 14 letters A-Z, in capitals:
`claude.word:PONDERING`) or `codex.end` (a Codex turn ended), as `{"moment": "<name>"}` in a `POST /moment`; the
words you type after `/tokentv` are not sent, only the name. On
Linux and macOS it goes only over TokenTV's own socket in its state folder (`live.sock`), where no proxy or redirect
can take it anywhere else;
with no socket there, nothing is sent. On Windows only `token-tv notify` sends: to TokenTV's port on `127.0.0.1`,
through no proxy and following no redirect. Your prompts, commands, file paths, outputs and session ids never
leave the mod or `token-tv notify`, and the mod keeps none of them: it reads a command or a prompt to tell which
name it is, then lets it go.

TokenTV keeps the moments in memory only, the thinking word too: nothing is logged, nothing is written to disk
(no picture with a moment or a word in it either), and a restart forgets them. It takes moments only from this computer, by its own name, never from a web page. What goes to the clock
is the picture, as for everything else TokenTV shows.

## Turning it off

- Claude Code: `/plugin disable tokentv` (or `/plugin uninstall tokentv`). Sounds alone: `/tokentv sound off`.
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

The endpoint takes exactly `{"moment": "<name>"}` (JSON, at most 256 bytes), the name one of those above
(`moments.MOMENTS`), or `claude.word:` followed by one word of 1 to 14 letters A-Z in either case and nothing else,
and answers `204` at once; anything else gets a `4xx` and changes nothing. Its `204` to a `claude.ask` says, in a
`TokenTV-Wait-Age` header, how many seconds the wait that ask joined has lasted, so the mod sends no answer after
TokenTV has let that wait go. A
`GET /moment` is no moment (`405`, `Allow: POST`). A moment's request has 2 seconds to arrive whole, the
dashboard's other requests 10; one that runs out is answered `408`, and a moment that came whole but late counts
for nothing. The moments' rules are in `token_tv/moments.py` (time comes from
`moments.CLOCK`, which tests replace with a fake clock; the break's hour from the readings' times on the wall clock,
`time.time()`, and `moments.RANDOM` picks each break, courtroom and ghost), the clock timing in `token_tv/live.py`
(`sync_moments`; on an SD_PRO a loop is its GIF's pictures, each for its delay but at least `device_frame_ms`, 142 by
default), the phase-3a drawings in `token_tv/claude_moments.py`. Priority, from the first: a waiting prompt, a bow, a
pat or a snack, the courtroom, the break, the turn back round, a tool face; then the usual face with its states (the
ghost, the back turned, the word).
Tests: `python3 -B -m unittest discover -s tests` and `claude plugin test claude-plugin`.
