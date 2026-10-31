"""Render docs/images/arcade.gif: the animated Arcade face, each character at work for a few seconds.

Sample readings only, and only the everyday scenes (the hidden ones are not in this tree):
    python3 scripts/render_arcade_demo.py
"""
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from token_tv import arcade  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402

# Each character at work on its own clock: the picture is its gauge (moon, garden, fuel, clouds, pellets).
CAST = [('claude', 'CLAUDE A', [('5H', 38, 3 * H), ('WEEK', 61, 3 * D)]), ('codex', 'CODEX A', [('WEEK', 47, 4 * D)]),
        ('grok', 'GROK A', [('BUDGET', 52, 12 * D)]), ('copilot', 'COPILOT A', [('MONTH', 46, 9 * D)]),
        ('antigravity', 'ANTI A', [('5H', 30, 2 * H)])]
SHOWN = 21  # pictures of each: three seconds at the clock's pace
CLOCK_MS = 140  # how long a SmallTV shows each picture (filmed 2026-10-31), so the page moves as the clock does
SCALE = 2


def main():
    now = time.mktime((2026, 10, 28, 14, 0, 0, 0, 0, -1))  # daytime: the stage is not dimmed
    frames = []
    for provider, alias, windows in CAST:
        data = snapshot(now, [(f'{provider}_a', alias, provider, windows)])
        data['accounts'][f'{provider}_a']['active'] = True
        if provider == 'grok':
            data['accounts']['grok_a']['role'] = 'crew'
        frames += [f.convert('RGB').resize((240 * SCALE, 240 * SCALE), Image.Resampling.NEAREST)
                   for f in arcade.arcade_frames(data, now)[:SHOWN]]
    colours = {c for f in frames[::6] for _, c in f.getcolors(maxcolors=1 << 16)}
    if len(colours) <= 256:  # every colour exactly
        palette = Image.new('P', (1, 1))
        palette.putpalette([v for c in sorted(colours) for v in c])
    else:  # the closest 256 over a sample of every character's frames
        sheet = Image.new('RGB', (240 * SCALE, 240 * SCALE * len(frames[::12])))
        for n, f in enumerate(frames[::12]):
            sheet.paste(f, (0, 240 * SCALE * n))
        palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    out = ROOT / 'docs' / 'images' / 'arcade.gif'
    indexed[0].save(out, save_all=True, append_images=indexed[1:], duration=CLOCK_MS, loop=0, disposal=1,
                    optimize=False)
    print(f'{out} {out.stat().st_size // 1024} KB, {len(frames)} frames')


if __name__ == '__main__':
    main()
