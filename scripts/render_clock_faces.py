"""Render docs/images/clock-faces.png (six clock faces, for the setup guide) and docs/images/four-faces.png (the
four the README shows, in a row) from the real renderers.

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
README_FACES = ('digital', 'neon', 'retro', 'hud')  # the README keeps four; Pixel and Space stay in the guide
TILE, GAP, MARGIN, CAPTION = 480, 36, 38, 62


def sheet_of(faces, columns, tile):
    rows = -(-len(faces) // columns)
    gap, margin, caption = round(GAP * tile / TILE), round(MARGIN * tile / TILE), round(CAPTION * tile / TILE)
    sheet = Image.new('RGB', (2 * margin + columns * tile + (columns - 1) * gap, 2 * margin + rows * (tile + caption)),
                      '#0b0e12')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(ROOT / 'token_tv' / 'web' / 'manrope.ttf'), round(22 * tile / TILE))
    now = time.time()
    for index, (style, title, sample) in enumerate(faces):
        frame = Image.open(io.BytesIO(render_page(snapshot(now, sample), style=style))).convert('RGB')
        x = margin + index % columns * (tile + gap)
        y = margin + index // columns * (tile + caption)
        sheet.paste(frame.resize((tile, tile), Image.Resampling.NEAREST), (x, y))
        draw.text((x + tile / 2, y + tile + caption / 2), title, font=font, fill='#c9d1d9', anchor='mm')
    return sheet


def main():
    for name, faces, columns, tile in (('clock-faces.png', FACES, 3, TILE),
                                       ('four-faces.png', [f for f in FACES if f[0] in README_FACES], 4, 240)):
        out = ROOT / 'docs' / 'images' / name
        sheet_of(faces, columns, tile).save(out, optimize=True)
        print(out, f'{out.stat().st_size // 1024} KB')


if __name__ == '__main__':
    main()
