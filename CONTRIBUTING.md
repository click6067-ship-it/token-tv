# Contributing

Thanks for helping. The most useful contributions right now are:

- **Clock faces.** See [docs/clock-faces.md](docs/clock-faces.md). One function, previewed
  from sample data.
- **Hardware reports.** Does your clock model work? Open a *Hardware compatibility* issue.
- **Bug reports** with the output of `token-tv doctor`.

## Set up

```bash
git clone https://github.com/click6067-ship-it/token-tv && cd token-tv
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/token-tv demo          # renders every face with sample data, no login needed
.venv/bin/python -B -m unittest discover -s tests
```

## Ground rules

- Never put passwords, tokens, cookies, `.credentials.json`, `auth.json` or real config files
  in an issue, a pull request, a test or a screenshot. Tests use synthetic accounts
  (`token_tv/sample.py`, `@example.com` emails) and temporary folders.
- A missing reading shows as a dash and an old one says OLD. Please keep that true.
- Keep pull requests small: one face, one provider fix or one clock model at a time.
