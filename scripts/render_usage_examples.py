"""Render docs/images/usage-examples.png: the Digital face at several sample usage levels.

Every frame comes from the real renderer with synthetic accounts (no real usage):
    python3 scripts/render_usage_examples.py
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

SCENES = [
    ('Fresh morning', [('claude_a', 'CLAUDE A', 'claude', [('5H', 8, 4 * H + 50 * 60)]),
                       ('codex_a', 'CODEX A', 'codex', [('WEEK', 21, 5 * D)]),
                       ('grok_a', 'GROK A', 'grok', [('BUDGET', 12, 20 * D)])]),
    ('Busy afternoon', [('claude_a', 'CLAUDE A', 'claude', [('5H', 63, 2 * H + 5 * 60)]),
                        ('codex_a', 'CODEX A', 'codex', [('5H', 47, 3 * H)]),
                        ('grok_a', 'GROK A', 'grok', [('BUDGET', 55, 9 * D)])]),
    ('Near the limit', [('claude_a', 'CLAUDE A', 'claude', [('5H', 97, 18 * 60)]),
                        ('codex_a', 'CODEX A', 'codex', [('WEEK', 88, D + 6 * H)]),
                        ('grok_a', 'GROK A', 'grok', [('BUDGET', 92, 2 * D)])]),
]
SCALE, PAD, LABEL = 2, 24, 44


def main():
    out = ROOT / 'docs' / 'images' / 'usage-examples.png'
    side = 240 * SCALE
    sheet = Image.new('RGB', (PAD + len(SCENES) * (side + PAD), LABEL + side + PAD + 30), '#0b0e12')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(ROOT / 'token_tv' / 'web' / 'manrope.ttf'), 22)
    small = ImageFont.truetype(str(ROOT / 'token_tv' / 'web' / 'manrope.ttf'), 16)
    now = time.time()
    for index, (title, sample) in enumerate(SCENES):
        frame = Image.open(io.BytesIO(render_page(snapshot(now, sample), style='digital'))).convert('RGB')
        x = PAD + index * (side + PAD)
        sheet.paste(frame.resize((side, side), Image.Resampling.NEAREST), (x, LABEL))
        draw.text((x, 12), title, font=font, fill='#d9dde1')
    draw.text((PAD, LABEL + side + 10), 'DEMO · sample data rendered by TokenTV’s own Digital face (240×240, shown 2×)',
              font=small, fill='#8a949e')
    sheet.save(out, optimize=True)
    print(out)


if __name__ == '__main__':
    main()
