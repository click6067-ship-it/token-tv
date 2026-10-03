"""Render docs/images/clock-faces.png: all six clock faces from the real renderers.

Every face shows the same synthetic accounts (25 / 72 / 94 %) so they compare at a glance:
    python3 scripts/render_clock_faces.py
"""
import io
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from token_tv.display import render_page  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402


def rows(claude, codex, grok):
    return [(f'{p}_{k.lower()}', f'{p.upper()} {k}', p, [(w, used, reset)])
            for p, (k, w, used, reset) in zip(('claude', 'codex', 'grok'), (claude, codex, grok))]


# The same sample on every face so they compare at a glance: low, busy and near the limit.
SAMPLE_ROWS = rows(('A', '5H', 25, 3 * H + 41 * 60), ('A', 'WEEK', 72, 2 * D + 6 * H), ('A', 'BUDGET', 94, 12 * D + 3 * H))
FACES = [(style, title, SAMPLE_ROWS) for style, title in (
    ('digital', 'Digital'), ('neon', 'Neon'), ('retro', 'Pixel Retro'),
    ('hud', 'Sci-Fi HUD'), ('pixel', 'Pixel'), ('space', 'Space (animated)'))]
TILE, GAP, MARGIN, CAPTION = 480, 36, 38, 62


def main():
    out = ROOT / 'docs' / 'images' / 'clock-faces.png'
    width = 2 * MARGIN + 3 * TILE + 2 * GAP
    sheet = Image.new('RGB', (width, 2 * MARGIN + 2 * (TILE + CAPTION)), '#0b0e12')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(ROOT / 'token_tv' / 'web' / 'manrope.ttf'), 22)
    now = time.time()
    for index, (style, title, sample) in enumerate(FACES):
        frame = Image.open(io.BytesIO(render_page(snapshot(now, sample), style=style))).convert('RGB')
        x = MARGIN + index % 3 * (TILE + GAP)
        y = MARGIN + index // 3 * (TILE + CAPTION)
        sheet.paste(frame.resize((TILE, TILE), Image.Resampling.NEAREST), (x, y))
        draw.text((x + TILE / 2, y + TILE + 30), title, font=font, fill='#c9d1d9', anchor='mm')
    sheet.save(out, optimize=True)
    print(out)


if __name__ == '__main__':
    main()
