# Making a clock face

A clock face is one Python function that turns a usage snapshot into a 240×240 picture.
The clock only ever receives that picture.

## 1. Try a face without touching the code

Save this as `my_face.py` in the repository root and run `python3 my_face.py`.
It draws one line per provider with the same helpers the built-in faces use, from sample data.

```python
"""A tiny clock face: one line per provider. Run: python3 my_face.py"""
import time

from token_tv.display import account_label, overview_rows
from token_tv.sample import D, H, snapshot
from token_tv.themes import Canvas, band, face, gauge, number_text, reading


def render_mono(data):
    cv = Canvas('#000000')
    for index, row in enumerate(overview_rows(data)):
        y = 8 + index * 78
        used, period, old, reset = reading(row)  # used is None when there is no reading
        cv.text((10, y), account_label(row), face('vt323.woff2', 20), '#c8c8c8')
        cv.text((10, y + 18), number_text(used), face('vt323.woff2', 40), '#ffffff')  # a dash, never a fake 0
        cv.text((230, y + 30), ('OLD ' if old else '') + reset, face('vt323.woff2', 20),
                '#ff5d8f' if old else '#c8c8c8', anchor='ra')
        gauge(cv, (10, y + 60, 230, y + 66), used, band('digital', used or 0), stale=old)
    return cv.finish()


if __name__ == '__main__':
    data = snapshot(time.time(), [
        ('claude_a', 'CLAUDE A', 'claude', [('5H', 72, 2 * H)]),
        ('codex_a', 'CODEX A', 'codex', [('WEEK', 15, 4 * D)]),
        ('grok_a', 'GROK A', 'grok', []),  # unknown: no window was reported
    ])
    data['accounts']['codex_a']['status'] = 'stale'  # an old reading must look old
    render_mono(data).save('my-face.png')
    print('wrote my-face.png')
```

Open `my-face.png`. Judge it at its real size too: the clock is 240 pixels wide and about
3 cm across, so text under about 9 px is hard to read.

## 2. Add it to TokenTV

1. Move the function into `token_tv/themes.py` and add it to `RENDERERS`.
2. Add its name to `STYLES` in `token_tv/display.py`. The dashboard's **Clock display** list
   reads `STYLES`, so the new face appears there without other changes.
3. Run `token-tv demo` (or `python3 -m token_tv demo`) and check `token-tv-demo/demo-<name>.jpg`.
4. Run `python3 -B -m unittest discover -s tests`.
5. Optionally refresh the README sheet with `python3 scripts/render_clock_faces.py`.

## 3. Use it from your own fork — no approval needed

```bash
git clone https://github.com/<you>/token-tv && cd token-tv
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/token-tv demo     # your face from sample data; no config, login or clock needed
```

To show it on a real clock you need the normal setup first: a config (`token-tv setup`, or reuse
the one you already have with `--config`), logged-in accounts (`token-tv connect`, then
`token-tv doctor --live`) and `device_url` set to your clock. Then:

```bash
.venv/bin/token-tv run      # dashboard → Gallery
```

Your face is listed in the **Gallery** as **Local**. Press **Preview**, then the usual
**Apply to clock**. It works without any pull request; nothing is downloaded from anyone else.
Because the install is editable, later edits to your renderer show up after restarting `token-tv run`.

## 4. Share it (optional)

There are two different ways, and only the second one puts a face in the Gallery.

| | Share an image | Add it to the Gallery |
| --- | --- | --- |
| How | [Share a face](https://github.com/click6067-ship-it/token-tv/issues/new?template=share_a_face.md) issue: an image, optionally the prompt and your fork link | Pull request with the *New clock face* template: id, name, author, license, a 240×240 preview from sample data |
| What happens | It is just shown in the issue. Nothing is added to the Gallery automatically | After review the maintainer adds it to `token_tv/assets/theme-catalog.json` (with `added_at`, `min_version` and a likes issue) in the next release |
| Who sees it | People reading the issue | Everyone on that release, in the **Gallery**, sorted by **Popular** or **New** |

Popular uses 👍 on each face's GitHub issue, counted by hand before releases (the Gallery shows when).
It is not a live ranking. Older installs show "update TokenTV" instead of downloading anything.

## Rules every face keeps

- **Sample data only.** Build previews with `token_tv.sample.snapshot`. Never paste real
  account names, emails or usage into issues, pull requests or images.
- **Unknown is not zero.** When `used` is `None`, draw a dash and an empty gauge (`gauge`
  does this for you). Never show `0%` for a missing reading.
- **Old is visibly old.** When `reading()` returns `old=True`, mark it (the built-in faces
  write `OLD` and hatch the gauge with `stale=True`).
- **Live text, not pictures of text.** Numbers and times must come from the snapshot.
- **One picture, 240×240, JPEG.** `render_page` saves the image; animated faces return GIF
  bytes like `token_tv/space.py`.
- Fonts must be in `token_tv/web/` with their license file next to them.

## Worked example

[Pixel → Game Boy](../examples/gameboy/README.md) includes the render function, the same sample data before and after, and an old/missing-data check. It was made with Claude Code and runs without a clock or account.
