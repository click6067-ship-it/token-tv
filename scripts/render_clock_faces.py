"""Render docs/images/clock-faces.png: all six clock faces from the real renderers.

Each face gets its own synthetic accounts so the sheet shows a spread of usage:
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


FACES = [
    ('digital', 'Digital', rows(('A', 'WEEK', 86, 3 * D), ('A', '5H', 34, 2 * H + 12 * 60), ('B', 'BUDGET', 94, D + H))),
    ('neon', 'Neon', rows(('B', '5H', 52, 3 * H + 41 * 60), ('B', 'WEEK', 91, D + 4 * H), ('A', 'BUDGET', 18, 12 * D + 3 * H))),
    ('retro', 'Pixel Retro', rows(('C', 'WEEK', 73, 2 * D + 6 * H), ('A', '5H', 8, 4 * H + 51 * 60), ('B', 'BUDGET', 61, 6 * D + 2 * H))),
    ('hud', 'Sci-Fi HUD', rows(('A', '5H', 97, 38 * 60), ('B', 'WEEK', 45, 5 * D + 11 * H), ('A', 'BUDGET', 82, 2 * D + 9 * H))),
    ('pixel', 'Pixel', rows(('B', 'WEEK', 27, 6 * D + H), ('A', '5H', 66, H + 5 * 60), ('B', 'BUDGET', 88, 3 * D + 14 * H))),
    ('space', 'Space (animated)', rows(('A', 'WEEK', 86, 3 * D), ('A', '5H', 34, 2 * H), ('B', 'BUDGET', 61, 6 * D))),
]
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
