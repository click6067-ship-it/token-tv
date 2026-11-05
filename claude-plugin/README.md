# TokenTV for Claude Code

While Claude Code waits for you to answer a permission prompt, Clawd on your
[TokenTV](https://github.com/click6067-ship-it/token-tv) desk clock raises a hand (then hops, then holds up a
sign); when a turn is done, it bows. `/tokentv pet` and `/tokentv snack` give it a pat or a snack, one loop of
hearts or a cookie. Install it in Claude Code:

```
/plugin install tokentv --marketplace click6067-ship-it/token-tv
```

The mod tells the TokenTV running on this computer the moment's name and nothing else (`claude.ask`,
`claude.answered`, `claude.end`, `claude.pet`, `claude.snack`): no prompt, command, path or id leaves it, nor the
words typed after `/tokentv`. With no TokenTV running it does nothing.
On Windows it sends nothing for now.
The whole story, Codex's half and how to turn it off: [docs/claude-code-mod.md](../docs/claude-code-mod.md).

Tests: `claude plugin test claude-plugin` (tested with Claude Code 2.1.289).
