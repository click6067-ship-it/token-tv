"""Four LCD themes that match the web appearances; every reading stays live text.

Each 240×240 frame shows one account per provider in three rows. Fonts are the
bundled web fonts, gauges keep ten 10% cells, and each used-quota band is drawn as
a two-tone gradient from its start colour to its tip (tokens.css lvl-*-2 → lvl-*).
"""
import functools
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from token_tv.display import (
    PROVIDER_INK, STATUS, account_label, mascot, overview_rows, primary_window, quota_period, row_shift, time_left,
)

WEB = Path(__file__).with_name('web')
ASSET_DIR = Path(__file__).with_name('assets')
SIZE = 240
ROWS = (3, 82, 161)
ROW_H = 76

# (start, tip) per used-quota band: below 50, 50–79, 80–89, 90–100.
BANDS = {
    'digital': (('#13b884', '#3dfcb0'), ('#6fd13a', '#c3f562'), ('#ff6a2b', '#ff9d45'), ('#e8243f', '#ff5a6a')),
    'neon': (('#00b894', '#2cf5b0'), ('#1f7bff', '#38d6ff'), ('#ff8a1f', '#ffc23d'), ('#ff2a4a', '#ff3d81')),
    'retro': (('#2aa84a', '#5ee06a'), ('#8fc93a', '#d3e84a'), ('#ff7a1f', '#ffab3d'), ('#d62b3c', '#ff5a5f')),
    'hud': (('#14a874', '#35e0a0'), ('#1a7dff', '#3cc4ff'), ('#ff7a1a', '#ffb23f'), ('#e01e3c', '#ff4d6a')),
}
ACCENT = {
    'neon': {'claude': ('#ff8a2b', '#ffd23f'), 'codex': ('#7a9dff', '#b1a7ff'), 'grok': ('#e8eaf0', '#ffffff')},
    'retro': {'claude': ('#ff9f43', '#ffcf6b'), 'codex': ('#3ee68b', '#9bffc8'), 'grok': ('#b388ff', '#e0d0ff')},
    'hud': {'claude': ('#ff8a3d', '#ffb47a'), 'codex': ('#7a9dff', '#b1a7ff'), 'grok': ('#dfe3ea', '#ffffff')},
}


@functools.lru_cache(maxsize=None)
def face(name, size, weight=None):
    try:
        loaded = ImageFont.truetype(str(WEB / name), size)
    except OSError:
        return ImageFont.load_default()
    if weight is not None:
        try:
            loaded.set_variation_by_axes([weight])
        except (OSError, ValueError, AttributeError):
            pass
    return loaded


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) if isinstance(color, str) else tuple(color[:3])


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def band(theme, used):
    return BANDS[theme][0 if used < 50 else 1 if used < 80 else 2 if used < 90 else 3]


def reading(row):
    value = primary_window(row)
    used = max(0, min(100, value['used_percent'])) if value else None
    period = quota_period(value) if value else STATUS.get(row['status'], 'NO DATA')
    old = bool(value) and row['status'] != 'ok'
    reset = time_left(value.get('resets_at')) if value else '--'
    return used, period, old, reset


def ghost(text):
    """Unlit seven-segment cells: every lit glyph cell becomes 8."""
    return ''.join(c if c in ' :' else '8' for c in text)


class Canvas:
    """Background, a blurred bloom layer and a crisp ink layer, composited once."""

    def __init__(self, background):
        self.base = Image.new('RGBA', (SIZE, SIZE), background)
        self.ink = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
        self.bloom = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
        self.back = ImageDraw.Draw(self.base)
        self.draw = ImageDraw.Draw(self.ink)
        self.glow = ImageDraw.Draw(self.bloom)

    def text(self, xy, text, font, fill, glow=None, anchor='la', **options):
        try:
            self.draw.text(xy, text, font=font, fill=fill, anchor=anchor, **options)
            if glow:
                self.glow.text(xy, text, font=font, fill=glow, anchor=anchor, **options)
        except (KeyError, ValueError):
            # Font features need libraqm; fall back to the default glyph forms.
            options.pop('features', None)
            self.draw.text(xy, text, font=font, fill=fill, anchor=anchor, **options)
            if glow:
                self.glow.text(xy, text, font=font, fill=glow, anchor=anchor, **options)

    def spaced(self, xy, text, font, fill, tracking, anchor='la'):
        x, y = xy
        width = sum(self.draw.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)
        if anchor[0] == 'r':
            x -= width
        for c in text:
            self.draw.text((x, y), c, font=font, fill=fill, anchor='l' + anchor[1])
            x += self.draw.textlength(c, font=font) + tracking

    def finish(self, blur=3):
        out = self.base.copy()
        if self.bloom.getbbox():
            out.alpha_composite(self.bloom.filter(ImageFilter.GaussianBlur(blur)))
            out.alpha_composite(self.bloom.filter(ImageFilter.GaussianBlur(blur * 2.5)))
        out.alpha_composite(self.ink)
        return out.convert('RGB')


@functools.lru_cache(maxsize=None)
def glyph(provider, size, color, stroke=None):
    """Provider marks drawn at 4× and reduced for clean edges (burst, cube, ringed slash)."""
    s = size * 4
    image = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = round((stroke or max(1.6, size / 10)) * 4)
    c = s / 2
    if provider == 'claude':
        reach = (0.49, 0.38, 0.46, 0.36, 0.48, 0.39, 0.47, 0.36, 0.49, 0.38, 0.46, 0.37)
        for i, r in enumerate(reach):
            a = math.radians(i * 30 + (4 if i % 2 else 0) - 90)
            draw.line((c + math.cos(a) * s * 0.13, c + math.sin(a) * s * 0.13,
                       c + math.cos(a) * s * r, c + math.sin(a) * s * r), fill=color, width=width)
    elif provider == 'codex':
        k = s / 48
        hexagon = [(24, 5), (40.5, 14.5), (40.5, 33.5), (24, 43), (7.5, 33.5), (7.5, 14.5), (24, 5)]
        draw.line([(x * k, y * k) for x, y in hexagon], fill=color, width=width, joint='curve')
        for end in ((7.5, 14.5), (40.5, 14.5), (24, 43)):
            draw.line((24 * k, 24 * k, end[0] * k, end[1] * k), fill=color, width=width)
    else:
        r = s * 0.27
        draw.ellipse((c - r, c - r, c + r, c + r), outline=color, width=width)
        draw.polygon([(s * 0.1, s * 0.9), (s * 0.86, s * 0.12), (s * 0.9, s * 0.1), (s * 0.16, s * 0.9)], fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


@functools.lru_cache(maxsize=None)
def bot_sprite(provider, box_w, box_h, tint=None, detail=(4, 7, 10)):
    """The provider's bundled pixel bot, trimmed and scaled with hard edges to fit a box.

    With `tint`, the body becomes that one colour and the details (eyes, prompt) a dark ink, so the
    bot keeps its face in single-colour styles such as Neon and HUD.
    """
    with Image.open(ASSET_DIR / f'{provider}-pixel.png') as source:
        sprite = source.convert('RGBA')
    sprite = sprite.crop(sprite.getbbox())
    if tint is not None:
        lum = [sum(p[:3]) / 3 for p in sprite.getdata() if p[3] > 128]
        body = sorted(lum)[len(lum) // 2]
        ink, mark = rgb(tint), rgb(detail)
        sprite.putdata([(0, 0, 0, 0) if p[3] <= 128 else
                        (mark if abs(sum(p[:3]) / 3 - body) > 60 else ink) + (255,) for p in sprite.getdata()])
    scale = min(box_w / sprite.width, box_h / sprite.height)
    size = (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale)))
    return sprite.resize(size, Image.Resampling.NEAREST)


def scanlined(sprite, keep=150):
    """Dim every other row of a sprite, like a projected hologram."""
    out = sprite.copy()
    alpha = out.getchannel('A')
    draw = ImageDraw.Draw(alpha)
    for yy in range(1, out.height, 2):
        row = [alpha.getpixel((xx, yy)) for xx in range(out.width)]
        for xx, v in enumerate(row):
            if v:
                draw.point((xx, yy), fill=keep)
    out.putalpha(alpha)
    return out

def place_bot(layer, sprite, box):
    """Centre a sprite inside an (x, y, w, h) box."""
    x, y, w, h = box
    layer.alpha_composite(sprite, (x + (w - sprite.width) // 2, y + (h - sprite.height) // 2))


@functools.lru_cache(maxsize=None)
def spark_mark(size, color):
    """Our own drawing of a spark (twelve tapered rays of uneven length); not an official logo file."""
    s = size * 4
    c = s / 2
    image = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    reach = (.50, .40, .47, .36, .50, .41, .46, .37, .49, .39, .47, .38)
    for i, r in enumerate(reach):
        a = math.radians(i * 30 + (5 if i % 2 else -3) - 90)
        tip = (c + math.cos(a) * s * r, c + math.sin(a) * s * r)
        side, w = a + math.pi / 2, s * .075
        draw.polygon([(c + math.cos(side) * w, c + math.sin(side) * w), tip,
                      (c - math.cos(side) * w, c - math.sin(side) * w)], fill=color)
        draw.ellipse((tip[0] - s * .03, tip[1] - s * .03, tip[0] + s * .03, tip[1] + s * .03), fill=color)
    draw.ellipse((c - s * .12, c - s * .12, c + s * .12, c + s * .12), fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


@functools.lru_cache(maxsize=None)
def prompt_cloud_mark(size, color):
    """Our own drawing of a rounded cloud with a '>_' prompt cut out; not an official logo file."""
    s = size * 4
    image = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for box in ((s * .02, s * .30, s * .56, s * .92), (s * .20, s * .06, s * .82, s * .66), (s * .44, s * .30, s * .98, s * .92)):
        draw.ellipse(box, fill=color)
    draw.rounded_rectangle((s * .14, s * .50, s * .86, s * .92), radius=s * .2, fill=color)
    cut = Image.new('L', (s, s), 0)
    cd = ImageDraw.Draw(cut)
    w, cx, cy = round(s * .09), s * .27, s * .52
    cd.line((cx, cy - s * .13, cx + s * .14, cy, cx, cy + s * .13), fill=255, width=w, joint='curve')
    cd.line((cx + s * .24, cy + s * .15, cx + s * .48, cy + s * .15), fill=255, width=w)
    image.putalpha(Image.composite(Image.new('L', (s, s), 0), image.getchannel('A'), cut))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def clock_mark(cv, center, r, color, width=1):
    x, y = center
    cv.draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=width)
    cv.draw.line((x, y - r * 0.55, x, y, x + r * 0.45, y + r * 0.25), fill=color, width=width)


def gauge(cv, box, used, colors, *, gap=3, shape='rect', radius=2, skew=0, track=(255, 255, 255, 30),
          empty=(255, 255, 255, 70), stale=False, split=None, glow=False, shade=False, stepped=False):
    """Ten 10% cells; the filled length samples one start→tip gradient of the band."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0 + 1, y1 - y0 + 1
    cell = (width - skew - 9 * gap) / 10
    area = (width, height)
    track_mask, fill_mask = Image.new('L', area, 0), Image.new('L', area, 0)
    tm, fm = ImageDraw.Draw(track_mask), ImageDraw.Draw(fill_mask)

    def outline(draw, i, fraction, fill, hollow=False):
        a = i * (cell + gap)
        b = a + cell * fraction
        if shape == 'skew':
            points = [(a + skew, 0), (b + skew, 0), (b, height - 1), (a, height - 1)]
            draw.polygon(points, fill=None if hollow else fill, outline=fill if hollow else None)
        elif shape == 'round':
            draw.rounded_rectangle((a, 0, max(a + 1, b - 1), height - 1), radius=radius,
                                   fill=None if hollow else fill, outline=fill if hollow else None)
        else:
            draw.rectangle((a, 0, max(a, b - 1), height - 1), fill=None if hollow else fill,
                           outline=fill if hollow else None)

    for i in range(10):
        outline(tm, i, 1, 255, hollow=used is None)
        if used is not None and used / 10 - i > 0:
            outline(fm, i, min(1.0, used / 10 - i), 255)
    if used is None:
        dots = Image.new('L', area, 0)
        ImageDraw.Draw(dots).point([(x, y) for x in range(width) for y in range(height) if (x + y) % 3 == 0], fill=255)
        track_mask = Image.composite(track_mask, Image.new('L', area, 0), dots)
        cv.ink.paste(Image.new('RGBA', area, empty), (x0, y0), track_mask)
        return
    cv.ink.paste(Image.new('RGBA', area, track), (x0, y0), track_mask)
    if not used:
        return
    full = math.floor(used / 10)
    end = full * (cell + gap) + (used / 10 - full) * cell if used < 100 else width - skew
    start, tip = colors
    strip = Image.new('RGBA', area)
    sd = ImageDraw.Draw(strip)
    for x in range(width):
        position = x if not stepped else (math.floor(x / (cell + gap)) + 0.5) * (cell + gap)
        sd.line((x, 0, x, height), fill=mix(start, tip, position / max(1, end)) + (255,))
    if stale:
        for k in range(-height, width, 5):
            fm.line((k, height, k + height, 0), fill=0, width=2)
    if glow:
        cv.bloom.paste(strip, (x0, y0), fill_mask)
    cv.ink.paste(strip, (x0, y0), fill_mask)
    if shade:
        light = Image.new('RGBA', area, (255, 255, 255, 0))
        ImageDraw.Draw(light).rectangle((0, 0, width, 1), fill=(255, 255, 255, 110))
        ImageDraw.Draw(light).rectangle((0, height - 2, width, height), fill=(0, 0, 0, 80))
        layer = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
        layer.paste(light, (x0, y0), fill_mask)
        cv.ink.alpha_composite(layer)
    if split:
        for i in range(10):
            mid = x0 + i * (cell + gap) + cell / 2
            cv.draw.rectangle((round(mid) - 1, y0, round(mid), y1), fill=split)


def segment_time(reset):
    """Seven segments cannot draw 'm': show under-a-day resets as a clock (18:11)."""
    parts = reset.split()
    if len(parts) == 2 and parts[0].endswith('h') and parts[1].endswith('m'):
        return parts[0][:-1] + ':' + parts[1][:-1].zfill(2)
    return reset


def number_text(used):
    return '--' if used is None else str(round(used))


def render_digital(snapshot):
    mint, dim, line, amber, unlit = '#7dffd0', '#4dbb92', '#22694f', '#ffcf5a', '#0d3326'
    cv = Canvas('#020906')
    for y in range(0, SIZE, 3):
        cv.back.line((0, y, SIZE, y), fill='#04130d')
    vt, seg = (lambda s: face('vt323.woff2', s)), (lambda s: face('dseg7-classic-bold.woff2', s))
    rows = overview_rows(snapshot)
    for index, row in enumerate(rows):
        y = ROWS[index] + row_shift(len(rows), ROWS[1] - ROWS[0])
        used, period, old, reset = reading(row)
        cv.back.rectangle((4, y, 235, y + ROW_H - 1), fill='#03100b', outline=line)
        cv.back.line((5, y + 25, 234, y + 25), fill='#0f3a2c')
        # LCD: the bot lit in the same mint phosphor as the text, dark eyes, soft glow; no brand colours.
        place_bot(cv.ink, bot_sprite(row['provider'], 24, 17, mint, '#03100b'), (9, y + 4, 24, 17))
        place_bot(cv.bloom, bot_sprite(row['provider'], 24, 17, (61, 252, 176), '#03100b'), (9, y + 4, 24, 17))
        cv.text((38, y + 3), account_label(row) + ' >', vt(22), mint, glow=(61, 252, 176, 90))
        cv.text((229, y + 4), period + (' OLD' if old else ''), vt(20), amber if old else dim, anchor='ra')
        if used is None:
            cv.text((11, y + 31), '-- NO DATA', vt(26), dim)
        else:
            number = number_text(used)
            cv.text((11, y + 32), ghost(number), seg(25), unlit)
            cv.text((11, y + 32), number, seg(25), mint, glow=(61, 252, 176, 120))
            x = 11 + cv.draw.textlength(number, font=seg(25)) + 3
            cv.text((x, y + 38), '%', vt(24), mint)
        if reset != '--':
            clock = segment_time(reset)
            cv.text((229, y + 28), 'RESETS IN', vt(16), dim, anchor='ra')
            cv.text((229, y + 43), ghost(clock), seg(14), '#2a2108', anchor='ra')
            cv.text((229, y + 43), clock, seg(14), amber, glow=(255, 190, 70, 120), anchor='ra')
        gauge(cv, (11, y + 61, 229, y + 70), used, band('digital', used or 0), gap=3, track='#0b2a1f',
              empty='#2a6b52', stale=old, split='#03100b', glow=True)
    return cv.finish(blur=2)


def render_neon(snapshot):
    """Neon tubes: a bright core line over a wide halo; the number glows in the provider colour."""
    cv = Canvas('#04030a')
    for y in range(4, SIZE, 8):
        for x in range(4, SIZE, 8):
            cv.back.point((x, y), fill='#0e0b1c')
    orb, ox = (lambda s, w=700: face('orbitron.ttf', s, w)), (lambda s, w=800: face('oxanium.woff2', s, w))
    rows = overview_rows(snapshot)
    for index, row in enumerate(rows):
        y = ROWS[index] + row_shift(len(rows), ROWS[1] - ROWS[0])
        a, a2 = ACCENT['neon'][row['provider']]
        used, period, old, reset = reading(row)
        box = (5, y + 1, 234, y + ROW_H - 2)
        cv.back.rounded_rectangle(box, radius=12, fill=mix('#06050e', a, .05))
        cv.glow.rounded_rectangle(box, radius=12, outline=rgb(a) + (255,), width=3)
        cv.draw.rounded_rectangle(box, radius=12, outline=mix(a, '#ffffff', .45), width=1)
        # Neon: each row is already lit in its provider colour, so the bot takes that same colour with a halo.
        place_bot(cv.ink, bot_sprite(row['provider'], 26, 26, mix(a, '#ffffff', .35)), (12, y + 9, 26, 26))
        place_bot(cv.bloom, bot_sprite(row['provider'], 26, 26, a), (12, y + 9, 26, 26))
        cv.text((46, y + 9), account_label(row), orb(11), '#ffffff')
        cv.text((228, y + 9), period + (' OLD' if old else ''), orb(10), '#ff5d8f' if old else mix(a, '#ffffff', .2),
                glow=rgb(a) + (160,), anchor='ra')
        number = number_text(used)
        cv.text((45, y + 22), number, ox(33), '#ffffff')
        cv.glow.text((45, y + 22), number, font=ox(33), fill=rgb(a) + (255,), stroke_width=2, stroke_fill=rgb(a) + (255,))
        if used is not None:
            x = 45 + cv.draw.textlength(number, font=ox(33)) + 2
            cv.text((x, y + 36), '%', ox(16, 700), mix(a, '#ffffff', .6))
        cv.text((228, y + 31), reset, ox(17, 700), '#ffffff', glow=rgb(a) + (170,), anchor='ra')
        ring = 228 - cv.draw.textlength(reset, font=ox(17, 700)) - 12
        clock_mark(cv, (ring, y + 40), 7, mix(a, '#ffffff', .3), 1)
        cv.glow.ellipse((ring - 8, y + 32, ring + 8, y + 48), outline=rgb(a) + (220,), width=2)
        gauge(cv, (14, y + 59, 226, y + 66), used, band('neon', used or 0), gap=3, shape='round', radius=3,
              track='#15122a', empty='#4a4170', stale=old, glow=True)
    return cv.finish(blur=3)


def pixel_scene(cv, provider, top):
    """A 2-px pixel landscape behind each Pixel Retro row (sunset / forest city / space)."""
    rnd = random.Random({'claude': 11, 'codex': 23, 'grok': 37}[provider])
    sky = {'claude': ('#2a1330', '#3a1834', '#4d1f36', '#652836', '#7f3335', '#9a4133'),
           'codex': ('#06171d', '#082027', '#0b2a2e', '#0e3434', '#113f39', '#15493e'),
           'grok': ('#0d0a28', '#120d33', '#170f3e', '#1c1349', '#211654', '#271a5f')}[provider]
    d = cv.back
    for i, color in enumerate(sky):
        d.rectangle((6, top + 2 + i * 12, 233, top + 2 + (i + 1) * 12), fill=color)

    def px(x, y, color, w=1, h=1):
        d.rectangle((x * 2, top + y * 2, x * 2 + w * 2 - 1, top + y * 2 + h * 2 - 1), fill=color)

    def disc(cx, cy, r, color):
        for dy in range(-r, r + 1):
            w = round(math.sqrt(r * r - dy * dy))
            px(cx - w, cy + dy, color, 2 * w + 1)

    if provider == 'claude':
        disc(66, 12, 6, '#ff9e4f'); disc(66, 12, 4, '#ffc067')
        for yy in (14, 16):
            px(59, yy, sky[2], 15)
        heights = [30 - round(5 * max(0, math.sin((x - 20) / 9)) + 2 * math.sin(x / 3)) for x in range(3, 117)]
        for x, h in zip(range(3, 117), heights):
            px(x, h, '#5a2236', 1, 37 - h)
        for x in range(3, 117):
            px(x, 33 - round(math.sin(x / 4)), '#371428', 1, 5)
    elif provider == 'codex':
        for _ in range(14):
            px(rnd.randrange(20, 116), rnd.randrange(1, 12), '#9bffd2')
        disc(66, 7, 3, '#d9ffe9'); disc(67, 6, 2, sky[0])
        x = 40
        while x < 116:
            w, h = rnd.randrange(3, 6), rnd.randrange(6, 13)
            px(x, 32 - h, '#0b3530', w, h + 5)
            for wy in range(33 - h, 31, 2):
                if rnd.random() > .5:
                    px(x + 1, wy, '#7dffb9')
            x += w + 1
        for p in range(3, 117, 3):
            px(p, 33, '#05201a', 2, 5)
    else:
        for _ in range(40):
            px(rnd.randrange(3, 116), rnd.randrange(1, 30), rnd.choice(('#efe6ff', '#b9a6ff')))
        disc(66, 10, 5, '#8f6cf2'); disc(65, 9, 3, '#a98bff')
        for i in range(-9, 10):
            px(66 + i, 11 - round(i * .28), '#e2d6ff' if abs(i) < 5 else '#bca8ff')
        for x in range(3, 117):
            px(x, 33 - round(2 * abs(math.sin(x / 7))), '#120c33', 1, 6)


def render_retro(snapshot):
    outline_ink, cream = '#0a0d26', '#fff3d6'
    cv = Canvas('#0a0f2c')
    rnd = random.Random(5)
    for _ in range(70):
        x, y = rnd.randrange(0, SIZE), rnd.randrange(0, SIZE)
        cv.back.point((x, y), fill=rnd.choice(('#ffffff', '#b9c8ff', '#ffe9a8')))
    title = lambda s: face('press-start-2p.ttf', s)
    rows = overview_rows(snapshot)
    for index, row in enumerate(rows):
        y = ROWS[index] + row_shift(len(rows), ROWS[1] - ROWS[0])
        a, a2 = ACCENT['retro'][row['provider']]
        used, period, old, reset = reading(row)
        pixel_scene(cv, row['provider'], y)
        cv.back.rectangle((4, y, 235, y + ROW_H - 1), outline=outline_ink, width=2)
        cv.back.rectangle((6, y + 2, 233, y + ROW_H - 3), outline=a, width=2)
        for cx, cy in ((4, y), (234, y), (4, y + ROW_H - 2), (234, y + ROW_H - 2)):
            cv.back.rectangle((cx, cy, cx + 1, cy + 1), fill='#0a0f2c')
        cv.draw.rectangle((11, y + 8, 50, y + 47), fill=outline_ink, outline=a, width=2)
        if row['provider'] == 'grok':
            cv.draw.rectangle((16, y + 13, 45, y + 42), fill='#d9ccff')
        mascot(cv.ink, row['provider'], (7, y + 4), pixel=True, size=32)
        cv.text((57, y + 9), account_label(row), title(8), cream, stroke_width=1, stroke_fill=outline_ink)
        cv.text((57, y + 22), number_text(used) + ('%' if used is not None else ''), title(16), cream,
                stroke_width=2, stroke_fill=outline_ink)
        cv.text((57, y + 41), period + (' OLD' if old else ''), title(8), '#ff9a9a' if old else '#b9d2ff', stroke_width=1, stroke_fill=outline_ink)
        cv.draw.rectangle((153, y + 9, 228, y + 40), fill=outline_ink, outline=a, width=2)
        cv.text((159, y + 14), 'RESET IN', title(8), '#a9bdf0')
        cv.text((159, y + 27), reset.upper(), title(8), cream)
        cv.draw.rectangle((10, y + 51, 229, y + 66), fill=outline_ink)
        cv.draw.rectangle((12, y + 53, 227, y + 64), outline='#3a4fb0')
        gauge(cv, (14, y + 55, 225, y + 62), used, band('retro', used or 0), gap=2, track='#19235f',
              empty='#3a4ea8', stale=old, shade=True, stepped=True)
    return cv.finish()


def render_hud(snapshot):
    cv = Canvas('#03080e')
    for g in range(0, SIZE, 12):
        color = '#0b1a28' if g % 48 == 0 else '#06111b'
        cv.back.line((g, 0, g, SIZE), fill=color)
        cv.back.line((0, g, SIZE, g), fill=color)
    chakra = lambda s, bold=True: face('chakra-petch-700.woff2' if bold else 'chakra-petch-500.woff2', s)
    rows = overview_rows(snapshot)
    for index, row in enumerate(rows):
        y = ROWS[index] + row_shift(len(rows), ROWS[1] - ROWS[0])
        a, a2 = ACCENT['hud'][row['provider']]
        used, period, old, reset = reading(row)
        cut = 10
        frame = [(4, y), (235 - cut, y), (235, y + cut), (235, y + ROW_H - 1), (4 + cut, y + ROW_H - 1), (4, y + ROW_H - 1 - cut)]
        cv.back.polygon(frame, fill=mix('#06101a', a, .05))
        cv.draw.polygon(frame, outline=mix(a, '#1b3b58', .45))
        cv.glow.line(frame + [frame[0]], fill=rgb(a) + (150,), width=2)
        cv.draw.line((8, y + 4, 8, y + 12), fill=a, width=2)
        cv.draw.line((8, y + 4, 16, y + 4), fill=a, width=2)
        cv.draw.line((231, y + ROW_H - 5, 231, y + ROW_H - 13), fill=a, width=2)
        cv.draw.line((231, y + ROW_H - 5, 223, y + ROW_H - 5), fill=a, width=2)
        # HUD: the row's accent colour as a hologram: solid bot with every other line dimmed.
        place_bot(cv.ink, scanlined(bot_sprite(row['provider'], 21, 19, a)), (11, y + 8, 21, 19))
        place_bot(cv.bloom, bot_sprite(row['provider'], 21, 19, a), (11, y + 8, 21, 19))
        cv.text((38, y + 8), account_label(row), chakra(14), '#ffffff')
        cv.text((228, y + 9), period + (' OLD' if old else ''), chakra(10, False), '#ff4d6a' if old else '#8fadc6', anchor='ra')
        number = number_text(used)
        cv.text((12, y + 25), number, chakra(30), '#ffffff', glow=rgb(a) + (110,))
        if used is not None:
            x = 12 + cv.draw.textlength(number, font=chakra(30)) + 2
            cv.text((x, y + 37), '%', chakra(16), a, glow=rgb(a) + (200,))
        cv.draw.line((150, y + 30, 150, y + 52), fill='#22476a')
        cv.spaced((228, y + 30), 'RESETS IN', chakra(7, False), '#6c8aa5', 1.4, anchor='ra')
        cv.text((228, y + 40), reset, chakra(17), '#ffffff', anchor='ra')
        gauge(cv, (12, y + 60, 228, y + 68), used, band('hud', used or 0), gap=3, shape='skew', skew=4,
              track='#0c1c2b', empty='#22476a', stale=old, glow=True)
    return cv.finish(blur=2)


RENDERERS = {'digital': render_digital, 'neon': render_neon, 'retro': render_retro, 'hud': render_hud}
