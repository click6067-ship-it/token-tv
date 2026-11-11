# TokenTV for Claude Code

While Claude Code waits for you to answer a permission prompt, Clawd on your
[TokenTV](https://github.com/click6067-ship-it/token-tv) desk clock raises a hand (then hops, then holds up a
sign); when a turn is done, it bows. `/tokentv pet` and `/tokentv snack` give it a pat or a snack, one loop of
hearts or a cookie. A risky command puts Clawd on trial, a deleted file leaves a ghost about, a rude prompt turns
its back, a failed tool makes it dizzy and a compaction makes it squeeze its head; the readout says Claude Code's own
thinking word while a turn runs. `/tokentv sound on` adds a short sound on this computer when a prompt waits and
when a turn is done. Install it in Claude Code:

```
/plugin install tokentv --marketplace click6067-ship-it/token-tv
```

The mod tells the TokenTV running on this computer the moment's name and nothing else (`claude.ask`,
`claude.answered`, `claude.end`, `claude.stop`, `claude.pet`, `claude.snack`, `claude.risky`, `claude.deleted`,
`claude.rude`, `claude.calm`, `claude.failed`, `claude.compact`, and `claude.word:` with the spinner's one word):
no prompt, command, path or id leaves it or is kept, nor the words typed after `/tokentv`, and nothing of Claude
Code's work is blocked or changed. With no TokenTV running it does nothing.
On Windows it sends nothing for now.
The whole story, Codex's half and how to turn it off: [docs/claude-code-mod.md](../docs/claude-code-mod.md).

Tests: `claude plugin test claude-plugin` (tested with Claude Code 2.1.321).
