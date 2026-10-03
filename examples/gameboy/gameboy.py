"""Game Boy style clock face, written for the request «게임보이 스타일로 시계 화면 바꿔줘».

A separate example: it is not registered as a product theme. Four-shade LCD palette only.
Run from the repository root:
    PYTHONPATH=. python3 examples/gameboy/gameboy.py
"""
import io
import sys
import time
from pathlib import Path

from PIL import Image

from token_tv.display import account_label, overview_rows, render_page, row_shift
from token_tv.sample import D, H, snapshot
from token_tv.themes import Canvas, bot_sprite, face, gauge, number_text, place_bot, reading

DARKEST, DARK, LIGHT, LIGHTEST = '#0f380f', '#306230', '#8bac0f', '#9bbc0f'
PALETTE = [DARKEST, DARK, LIGHT, LIGHTEST]
OUT = Path(__file__).resolve().parent


def to_four_shades(image):
    """Snap every pixel to the nearest of the four LCD shades (the real Game Boy had only four)."""
    palette = Image.new('P', (1, 1))
    flat = [int(c[i:i + 2], 16) for c in PALETTE for i in (1, 3, 5)]
    palette.putpalette(flat + [0] * (768 - len(flat)))
    return image.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB')


def render_gameboy(data):
    cv = Canvas(LIGHTEST)
    pixel = lambda size: face('press-start-2p.ttf', size)
    rows = overview_rows(data)
    pitch = 79
    for index, row in enumerate(rows):
        y = 3 + index * pitch + row_shift(len(rows), pitch)
        used, period, old, reset = reading(row)  # used is None when nothing was reported
        cv.draw.rectangle((4, y, 235, y + 74), outline=DARKEST, width=2)
        cv.draw.rectangle((7, y + 3, 232, y + 71), outline=DARK, width=1)
        place_bot(cv.ink, bot_sprite(row['provider'], 22, 18, DARKEST, LIGHTEST), (11, y + 7, 22, 18))
        cv.text((38, y + 11), account_label(row), pixel(8), DARKEST)
        cv.text((229, y + 11), ('OLD ' if old else '') + period, pixel(8), DARK, anchor='ra')
        cv.text((12, y + 31), number_text(used), pixel(20), DARKEST)  # a dash, never a fake 0
        if used is not None:
            cv.text((12 + cv.draw.textlength(number_text(used), font=pixel(20)) + 2, y + 39), '%', pixel(10), DARKEST)
        cv.text((229, y + 34), 'RESET', pixel(7), DARK, anchor='ra')
        cv.text((229, y + 45), reset, pixel(8), DARKEST, anchor='ra')
        gauge(cv, (12, y + 58, 227, y + 66), used, (DARKEST, DARK), gap=2, track=LIGHT, empty=DARK, stale=old)
    return to_four_shades(cv.finish())


def sample(stale_and_unknown=False):
    data = snapshot(time.time(), [
        ('claude_a', 'CLAUDE A', 'claude', [('5H', 25, 3 * H + 41 * 60)]),
        ('codex_a', 'CODEX A', 'codex', [('WEEK', 72, 2 * D + 6 * H)]),
        ('grok_a', 'GROK A', 'grok', [] if stale_and_unknown else [('BUDGET', 94, 12 * D + 3 * H)]),
    ])
    if stale_and_unknown:
        data['accounts']['codex_a']['status'] = 'stale'
    return data


if __name__ == '__main__':
    before = Image.open(io.BytesIO(render_page(sample(), style='pixel'))).convert('RGB')
    before.save(OUT / 'before.png')
    render_gameboy(sample()).save(OUT / 'after.png')
    render_gameboy(sample(stale_and_unknown=True)).save(OUT / 'after-old-unknown.png')
    print('wrote before.png, after.png, after-old-unknown.png')
    sys.exit(0)
