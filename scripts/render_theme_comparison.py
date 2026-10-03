"""Render a three-face comparison from actual clock renderers and sample data."""
import io
import time

from PIL import Image, ImageDraw, ImageFont

from render_clock_faces import ROOT, SAMPLE_ROWS, render_page, snapshot


def main():
    tile, gap, margin = 480, 32, 40
    width = margin * 2 + tile * 3 + gap * 2
    sheet = Image.new('RGB', (width, 710), '#0b0e12')
    draw = ImageDraw.Draw(sheet)
    font_path = str(ROOT / 'token_tv/web/manrope.ttf')
    title = ImageFont.truetype(font_path, 40)
    label = ImageFont.truetype(font_path, 24)
    note = ImageFont.truetype(font_path, 20)
    draw.text((margin, 28), 'Same clock, different faces.', font=title, fill='#e5e9ef')
    data = snapshot(time.time(), SAMPLE_ROWS)
    for i, (style, name) in enumerate((('digital', 'Digital'), ('neon', 'Neon'), ('retro', 'Pixel Retro'))):
        frame = Image.open(io.BytesIO(render_page(data, style=style))).convert('RGB')
        assert frame.size == (240, 240), frame.size
        x = margin + i * (tile + gap)
        sheet.paste(frame.resize((tile, tile), Image.Resampling.NEAREST), (x, 108))
        draw.text((x + tile / 2, 616), name, font=label, fill='#c9d1d9', anchor='mm')
    draw.text((margin, 668), 'Actual 240 x 240 renders · Sample data: 25 / 72 / 94%', font=note, fill='#969faa')
    out = ROOT / 'docs/images/theme-comparison.png'
    sheet.save(out, optimize=True)
    print(out)


if __name__ == '__main__':
    main()
