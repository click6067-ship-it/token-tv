# Game Boy style face — example

**Request:** «게임보이 스타일로 시계 화면 바꿔줘» ("change the clock face to a Game Boy style")
**Made by:** the TokenTV author with Claude Code (CC). Sample data only, not a real account.
This is a separate example. It is **not** registered as a product theme and was not applied to any clock.

| before (built-in Pixel) | after (Game Boy) | after, old + unknown |
| --- | --- | --- |
| ![before](before.png) | ![after](after.png) | ![old/unknown](after-old-unknown.png) |

The first two images use the same sample: Claude A 25% (5H, 3h 41m), Codex A 72% (WK, 2d 6h), Grok A 94% (BUD, 12d 3h).
The third image marks Codex as an old reading and gives Grok no data.

## Run it (no clock, no login, no fork)

Checked on Linux (2026-10-04). Python 3.10+.

```bash
git clone https://github.com/click6067-ship-it/token-tv && cd token-tv
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python examples/gameboy/gameboy.py   # writes before.png, after.png, after-old-unknown.png here
```

## Make your own in three steps

1. Copy the folder (commands below were checked on Linux):
   `.venv/bin/python -c "import shutil; shutil.copytree('examples/gameboy', 'examples/my-face')"`
2. In `examples/my-face/gameboy.py`, change the four colours on the line `DARKEST, DARK, LIGHT, LIGHTEST = ...`
   (or ask your AI for a different look).
3. Run `.venv/bin/python examples/my-face/gameboy.py` and open `examples/my-face/after.png` (240×240).

Want to keep it on GitHub? Fork the repository and commit your folder. Want others to see it? [Share a face](https://github.com/click6067-ship-it/token-tv/issues/new?template=share_a_face.md).

## What the face does

- Four LCD shades only (`#0f380f #306230 #8bac0f #9bbc0f`). The final image is snapped to those four.
- Each pixel bot uses the darkest shade; text is the Press Start 2P pixel font bundled with TokenTV.
- Keeps the meaning of every value: used %, window (5H/WK/BUD), reset time, account label.
- Old reading: "OLD" next to the window and a hatched gauge. No data: a dash, "NO DATA" and an empty dotted gauge, never 0%.

## Checked (2026-10-04)

- All three images are 240×240. `after.png` and `after-old-unknown.png` contain exactly 4 colours.
- Viewed at real size (1×) and 3×; labels, numbers and reset times are readable. The smallest text ("RESET", 7 px) is legible but small.
