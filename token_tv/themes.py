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
    PROVIDER_INK, account_label, fit_text, mascot, overview_rows, quota_period, reading, row_shift, shown_windows,
    slots, time_left,
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
    'neon': {'claude': ('#ff8a2b', '#ffd23f'), 'codex': ('#7a9dff', '#b1a7ff'), 'grok': ('#e8eaf0', '#ffffff'),
             'copilot': ('#22c7e0', '#5fe8cf'), 'antigravity': ('#78b6ee', '#e77345')},
    'retro': {'claude': ('#ff9f43', '#ffcf6b'), 'codex': ('#3ee68b', '#9bffc8'), 'grok': ('#b388ff', '#e0d0ff'),
              'copilot': ('#2fd0c0', '#8ff0e4'), 'antigravity': ('#78b6ee', '#94c45f')},
    'hud': {'claude': ('#ff8a3d', '#ffb47a'), 'codex': ('#7a9dff', '#b1a7ff'), 'grok': ('#dfe3ea', '#ffffff'),
            'copilot': ('#2fb8e8', '#7fe3f0'), 'antigravity': ('#78b6ee', '#e89646')},
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
    elif provider == 'copilot':  # its goggles
        r = s * 0.2
        for cx in (c - s * 0.22, c + s * 0.22):
            draw.ellipse((cx - r, c - r, cx + r, c + r), outline=color, width=width)
    elif provider == 'antigravity':  # its arch
        draw.arc((s * .14, s * .18, s * .86, s * 1.5), 180, 360, fill=color, width=round(width * 1.6))
        for side in (s * .14, s * .86 - width * 1.6):
            draw.rectangle((side, s * .84, side + width * 1.6, s * .9), fill=color)
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
    box = tuple(round(s * v) for v in (.14, .50, .86, .92))
    draw.rounded_rectangle(box, radius=min(round(s * .2), (box[3] - box[1]) // 2), fill=color)
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


def window_lines(cv, row, wins, box, skin):
    """Both windows (5H above WEEK) in a roomy row: each a name, a number, its reset and a gauge."""
    x0, y0, x1, y1 = box
    line = (y1 - y0) / len(wins)
    for i, value in enumerate(wins):
        used, period, old, reset = reading(row, value)
        top = y0 + i * line
        gh = max(4, round(line * .11))
        band_h = line - gh - 6
        nsize = max(12, min(skin['num_max'], round(band_h * .78)))
        lsize = max(7, round(nsize * .45))
        mid = top + band_h / 2 + 1
        label_font, num_font = skin['label'](lsize), skin['num'](nsize)
        cv.text((x0, round(mid - lsize / 2)), period + (' OLD' if old else ''), label_font,
                skin['old'] if old else skin['dim'], **skin.get('label_args', {}))
        nx = x0 + cv.draw.textlength(period + (' OLD' if old else ''), font=label_font) + max(4, lsize // 2)
        number = number_text(used)
        cv.text((round(nx), round(mid - nsize / 2)), number, num_font, skin['ink'], **skin.get('num_args', {}))
        if used is not None:
            px = nx + cv.draw.textlength(number, font=num_font) + 2
            cv.text((round(px), round(mid + nsize / 2 - lsize)), '%', skin['label'](lsize), skin['ink'])
        shown = skin.get('reset_fmt', lambda r: r)(reset)
        cv.text((x1, round(mid - skin.get('reset_size', lsize) / 2)), shown, skin.get('reset_font', skin['label'])(skin.get('reset_size', lsize)),
                skin.get('reset_ink', skin['ink']), anchor='ra', **skin.get('reset_args', {}))
        gy = round(top + line - gh - 3)
        style = dict(skin['gauge'](used, old))
        gauge(cv, (x0, gy, x1, gy + gh), used, style.pop('colors'), **style)


def render_digital(snapshot):
    mint, dim, line, amber, unlit = '#7dffd0', '#4dbb92', '#22694f', '#ffcf5a', '#0d3326'
    cv = Canvas('#020906')
    for y in range(0, SIZE, 3):
        cv.back.line((0, y, SIZE, y), fill='#04130d')
    vt, seg = (lambda s: face('vt323.woff2', s)), (lambda s: face('dseg7-classic-bold.woff2', s))
    rows = overview_rows(snapshot)
    for sl, row in zip(slots(len(rows)), rows):
        y, at, hero = sl.y, sl.at, sl.count == 1
        wins = shown_windows(row, sl.count)
        used, period, old, reset = reading(row, wins[0] if wins else None)
        cv.back.rectangle((4, y, 235, y + sl.h - 1), fill='#03100b', outline=line)
        bw, bh = round(24 * sl.icon), round(17 * sl.icon)
        head = y + bh + 8 if hero else at(25)
        cv.back.line((5, head, 234, head), fill='#0f3a2c')
        # LCD: the bot lit in the same mint phosphor as the text, dark eyes, soft glow; no brand colours.
        bot = (9, y + 4 if hero else at(4), bw, bh)
        place_bot(cv.ink, bot_sprite(row['provider'], bw, bh, mint, '#03100b'), bot)
        place_bot(cv.bloom, bot_sprite(row['provider'], bw, bh, (61, 252, 176), '#03100b'), bot)
        note = '' if len(wins) == 2 else ('OLD' if old else '') if sl.count == 4 else period + (' OLD' if old else '')
        room = 229 - (bw + 14) - (cv.draw.textlength(note, font=vt(sl.txt(20))) + 10 if note else 0)
        name = fit_text(cv.draw, account_label(row), vt(sl.txt(22)), room - cv.draw.textlength(' >', font=vt(sl.txt(22))))
        cv.text((bw + 14, bot[1] - 1), name + ' >', vt(sl.txt(22)), mint, glow=(61, 252, 176, 90))
        if len(wins) == 2:  # room for both windows: 5H above WEEK
            window_lines(cv, row, wins, (11, head + 4, 229, y + sl.h - 4), {
                'label': vt, 'num': seg, 'num_max': 40, 'ink': mint, 'dim': dim, 'old': amber,
                'num_args': {'glow': (61, 252, 176, 120)}, 'reset_font': seg, 'reset_fmt': segment_time,
                'reset_ink': amber, 'reset_args': {'glow': (255, 190, 70, 120)},
                'gauge': lambda u, o: {'colors': band('digital', u or 0), 'gap': 3, 'track': '#0b2a1f',
                                       'empty': '#2a6b52', 'stale': o, 'split': '#03100b', 'glow': True}})
            continue
        cv.text((229, bot[1]), note, vt(sl.txt(20)), amber if old else dim, anchor='ra')
        top = head + 12 if hero else at(32)
        if used is None:
            cv.text((11, top - 1), '-- NO DATA', vt(sl.num(26)), dim)
        else:
            number = number_text(used)
            cv.text((11, top), ghost(number), seg(sl.num(25)), unlit)
            cv.text((11, top), number, seg(sl.num(25)), mint, glow=(61, 252, 176, 120))
            x = 11 + cv.draw.textlength(number, font=seg(sl.num(25))) + 3
            cv.text((x, top + round(6 * sl.big)), '%', vt(sl.num(24)), mint)
        if reset != '--':
            clock = segment_time(reset)
            ry = top + sl.num(25) + 16 if hero else at(28)
            if sl.count < 4:
                cv.text((229, ry), 'RESETS IN', vt(sl.txt(16)), dim, anchor='ra')
                cy = ry + sl.txt(15)
            else:  # four rows: just the time, clear of the gauge
                cy = at(30)
            cv.text((229, cy), ghost(clock), seg(sl.txt(14)), '#2a2108', anchor='ra')
            cv.text((229, cy), clock, seg(sl.txt(14)), amber, glow=(255, 190, 70, 120), anchor='ra')
        gy = y + sl.h - 15 if hero else at(61)
        gauge(cv, (11, gy, 229, gy + max(6, round(9 * min(sl.k, 1.3)))), used, band('digital', used or 0), gap=3,
              track='#0b2a1f', empty='#2a6b52', stale=old, split='#03100b', glow=True)
    return cv.finish(blur=2)


def render_neon(snapshot):
    """Neon tubes: a bright core line over a wide halo; the number glows in the provider colour."""
    cv = Canvas('#04030a')
    for y in range(4, SIZE, 8):
        for x in range(4, SIZE, 8):
            cv.back.point((x, y), fill='#0e0b1c')
    orb, ox = (lambda s, w=700: face('orbitron.ttf', s, w)), (lambda s, w=800: face('oxanium.woff2', s, w))
    rows = overview_rows(snapshot)
    for sl, row in zip(slots(len(rows)), rows):
        y, at, hero = sl.y, sl.at, sl.count == 1
        a, a2 = ACCENT['neon'][row['provider']]
        wins = shown_windows(row, sl.count)
        used, period, old, reset = reading(row, wins[0] if wins else None)
        box = (5, y + 1, 234, y + sl.h - 2)
        cv.back.rounded_rectangle(box, radius=12, fill=mix('#06050e', a, .05))
        cv.glow.rounded_rectangle(box, radius=12, outline=rgb(a) + (255,), width=3)
        cv.draw.rounded_rectangle(box, radius=12, outline=mix(a, '#ffffff', .45), width=1)
        # Neon: each row is already lit in its provider colour, so the bot takes that same colour with a halo.
        bs = round(26 * sl.icon)
        bot = (12, y + 10 if hero else at(9), bs, bs)
        place_bot(cv.ink, bot_sprite(row['provider'], bs, bs, mix(a, '#ffffff', .35)), bot)
        place_bot(cv.bloom, bot_sprite(row['provider'], bs, bs, a), bot)
        note = '' if len(wins) == 2 else ('OLD' if old else '') if sl.count == 4 else period + (' OLD' if old else '')
        room = 228 - (bs + 20) - (cv.draw.textlength(note, font=orb(sl.txt(10))) + 8 if note else 0)
        cv.text((bs + 20, bot[1]), fit_text(cv.draw, account_label(row), orb(sl.txt(11)), room), orb(sl.txt(11)), '#ffffff')
        if len(wins) == 2:  # room for both windows: 5H above WEEK
            body = (16, bot[1] + bs + 4, 226, y + sl.h - 6) if hero else (bs + 20, bot[1] + sl.txt(11) + 6, 226, y + sl.h - 6)
            window_lines(cv, row, wins, body, {
                'label': lambda z: orb(z, 700), 'num': ox, 'num_max': 44, 'ink': '#ffffff',
                'dim': mix(a, '#ffffff', .2), 'old': '#ff5d8f', 'num_args': {'glow': rgb(a) + (150,)},
                'reset_font': lambda z: ox(z, 700), 'reset_args': {'glow': rgb(a) + (170,)},
                'gauge': lambda u, o: {'colors': band('neon', u or 0), 'gap': 3, 'shape': 'round', 'radius': 3,
                                       'track': '#15122a', 'empty': '#4a4170', 'stale': o, 'glow': True}})
            continue
        cv.text((228, bot[1]), note, orb(sl.txt(10)), '#ff5d8f' if old else mix(a, '#ffffff', .2),
                glow=rgb(a) + (160,), anchor='ra')
        number = number_text(used)
        nx, ny = (16, bot[1] + bs + 10) if hero else (bs + 19, at(22))
        cv.text((nx, ny), number, ox(sl.num(33)), '#ffffff')
        cv.glow.text((nx, ny), number, font=ox(sl.num(33)), fill=rgb(a) + (255,), stroke_width=2, stroke_fill=rgb(a) + (255,))
        if used is not None:
            x = nx + cv.draw.textlength(number, font=ox(sl.num(33))) + 2
            cv.text((x, ny + round(14 * sl.big)), '%', ox(sl.num(16), 700), mix(a, '#ffffff', .6))
        ry = ny + sl.num(33) + 14 if hero else at(31)
        cv.text((228, ry), reset, ox(sl.txt(17), 700), '#ffffff', glow=rgb(a) + (170,), anchor='ra')
        ring = 228 - cv.draw.textlength(reset, font=ox(sl.txt(17), 700)) - round(12 * sl.small)
        cr, cy = round(7 * sl.small), ry + round(9 * sl.small)
        clock_mark(cv, (ring, cy), cr, mix(a, '#ffffff', .3), 1)
        cv.glow.ellipse((ring - cr - 1, cy - cr - 1, ring + cr + 1, cy + cr + 1), outline=rgb(a) + (220,), width=2)
        gy = y + sl.h - 17 if hero else at(59)
        gauge(cv, (14, gy, 226, gy + max(5, round(7 * min(sl.k, 1.4)))), used, band('neon', used or 0), gap=3,
              shape='round', radius=3, track='#15122a', empty='#4a4170', stale=old, glow=True)
    return cv.finish(blur=3)


def pixel_scene(cv, provider, top, height=ROW_H):
    """A 2-px pixel landscape behind each Pixel Retro row (sunset / forest city / space).

    Sky things keep to the top and the ground to the bottom, so the scene fits any row height.
    """
    rnd = random.Random({'claude': 11, 'codex': 23, 'grok': 37, 'copilot': 41, 'antigravity': 53}[provider])
    sky = {'claude': ('#2a1330', '#3a1834', '#4d1f36', '#652836', '#7f3335', '#9a4133'),
           'codex': ('#06171d', '#082027', '#0b2a2e', '#0e3434', '#113f39', '#15493e'),
           'grok': ('#0d0a28', '#120d33', '#170f3e', '#1c1349', '#211654', '#271a5f'),
           'copilot': ('#062033', '#072a40', '#08344d', '#0a3f5b', '#0c4a68', '#0f5676'),
           'antigravity': ('#020208', '#03030c', '#040410', '#050514', '#060618', '#07071c')}[provider]
    d = cv.back
    band = (height - 4) / 6
    for i, color in enumerate(sky):
        d.rectangle((6, top + 2 + round(i * band), 233, top + 2 + round((i + 1) * band)), fill=color)
    drop = (height - ROW_H) // 2  # ground rows move with the bottom edge

    def px(x, y, color, w=1, h=1, ground=False):
        y0 = top + (y + (drop if ground else 0)) * 2
        y1 = min(top + height - 3, y0 + h * 2 - 1)
        if y0 < top + 2 or y0 > y1:
            return
        d.rectangle((x * 2, y0, x * 2 + w * 2 - 1, y1), fill=color)

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
            px(x, h, '#5a2236', 1, 37 - h + max(0, -drop), True)
        for x in range(3, 117):
            px(x, 33 - round(math.sin(x / 4)), '#371428', 1, 5, True)
    elif provider == 'codex':
        for _ in range(14):
            px(rnd.randrange(20, 116), rnd.randrange(1, 12), '#9bffd2')
        disc(66, 7, 3, '#d9ffe9'); disc(67, 6, 2, sky[0])
        x = 40
        while x < 116:
            w, h = rnd.randrange(3, 6), rnd.randrange(6, 13)
            px(x, 32 - h, '#0b3530', w, h + 5, True)
            for wy in range(33 - h, 31, 2):
                if rnd.random() > .5:
                    px(x + 1, wy, '#7dffb9', ground=True)
            x += w + 1
        for p in range(3, 117, 3):
            px(p, 33, '#05201a', 2, 5, True)
    elif provider == 'copilot':  # a teal-to-blue sky over a floor of clouds
        for _ in range(12):
            px(rnd.randrange(20, 116), rnd.randrange(1, 10), '#9fe8ff')
        for cx, cy, r in ((72, 9, 3), (76, 8, 4), (81, 9, 3)):
            disc(cx, cy, r, '#bfefff')
        for x in range(3, 117):
            px(x, 31 - round(1.5 * abs(math.sin(x / 5))), '#2b86b8', 1, 7, True)
            px(x, 33 - round(abs(math.sin(x / 3))), '#1b5f88', 1, 5, True)
    elif provider == 'antigravity':  # a dark maze: two walls, a row of dots between them, a power pellet
        for x in range(40, 117):
            px(x, 3, '#2121de')
            px(x, 30, '#2121de', 1, 1, True)
        for x in range(44, 114, 4):
            px(x, 16, '#ffb8ae')
        disc(52, 9, 2, '#ffb8ae')
    else:
        for _ in range(40):
            px(rnd.randrange(3, 116), round(rnd.randrange(1, 30) * (height - 16) / (ROW_H - 16)), rnd.choice(('#efe6ff', '#b9a6ff')))
        disc(66, 10, 5, '#8f6cf2'); disc(65, 9, 3, '#a98bff')
        for i in range(-9, 10):
            px(66 + i, 11 - round(i * .28), '#e2d6ff' if abs(i) < 5 else '#bca8ff')
        for x in range(3, 117):
            px(x, 33 - round(2 * abs(math.sin(x / 7))), '#120c33', 1, 6, True)


def render_retro(snapshot):
    outline_ink, cream = '#0a0d26', '#fff3d6'
    cv = Canvas('#0a0f2c')
    rnd = random.Random(5)
    for _ in range(70):
        x, y = rnd.randrange(0, SIZE), rnd.randrange(0, SIZE)
        cv.back.point((x, y), fill=rnd.choice(('#ffffff', '#b9c8ff', '#ffe9a8')))
    title = lambda s: face('press-start-2p.ttf', s)
    rows = overview_rows(snapshot)
    for sl, row in zip(slots(len(rows)), rows):
        y, at, hero, h = sl.y, sl.at, sl.count == 1, sl.h
        a, a2 = ACCENT['retro'][row['provider']]
        wins = shown_windows(row, sl.count)
        used, period, old, reset = reading(row, wins[0] if wins else None)
        pixel_scene(cv, row['provider'], y, h)
        cv.back.rectangle((4, y, 235, y + h - 1), outline=outline_ink, width=2)
        cv.back.rectangle((6, y + 2, 233, y + h - 3), outline=a, width=2)
        for cx, cy in ((4, y), (234, y), (4, y + h - 2), (234, y + h - 2)):
            cv.back.rectangle((cx, cy, cx + 1, cy + 1), fill='#0a0f2c')
        tile = round(40 * sl.icon)
        tx, ty = 11, (y + 8 if hero else at(8))
        cv.draw.rectangle((tx, ty, tx + tile - 1, ty + tile - 1), fill=outline_ink, outline=a, width=2)
        inner = tile - 10
        if row['provider'] == 'grok':  # white on the dark tile
            art = bot_sprite('grok', inner // 2, inner // 2, '#f2f4f8')
            place_bot(cv.ink, art.resize((art.width * 2, art.height * 2), Image.Resampling.NEAREST),
                      (tx + 5, ty + 5, inner, inner))
        else:
            mascot(cv.ink, row["provider"], (tx - 4, ty - 4), pixel=True,
                   size=round(32 * sl.icon), box=tile + 8)
        lx = tx + tile + 6
        room = (225 - lx) if hero or len(wins) == 2 else (147 - lx)  # clear of the reset box
        cv.text((lx, ty + 1), fit_text(cv.draw, account_label(row), title(sl.txt(8)), room), title(sl.txt(8)), cream,
                stroke_width=1, stroke_fill=outline_ink)
        if len(wins) == 2:  # room for both windows: 5H above WEEK, on a dark plate over the scene
            body = (14, ty + tile + 8, 225, y + h - 8) if hero else (lx, ty + sl.txt(8) + 8, 225, y + h - 8)
            cv.draw.rectangle((body[0] - 4, body[1] - 3, body[2] + 4, body[3] + 3), fill=outline_ink, outline=a, width=2)
            window_lines(cv, row, wins, body, {
                'label': title, 'num': title, 'num_max': 22, 'ink': cream, 'dim': '#b9d2ff', 'old': '#ff9a9a',
                'gauge': lambda u, o: {'colors': band('retro', u or 0), 'gap': 2, 'track': '#19235f', 'empty': '#3a4ea8',
                                       'stale': o, 'shade': True, 'stepped': True}})
            continue
        text = number_text(used) + ('%' if used is not None else '')
        nx, ny = (14, ty + tile + 10) if hero else (lx, at(22))
        cv.text((nx, ny), text, title(sl.num(16)), cream, stroke_width=2, stroke_fill=outline_ink)
        py = ty + sl.txt(8) + 12 if hero else at(41)
        cv.text((lx, py), period + (' OLD' if old else ''), title(sl.txt(8)), '#ff9a9a' if old else '#b9d2ff',
                stroke_width=1, stroke_fill=outline_ink)
        end = nx + cv.draw.textlength(text, font=title(sl.num(16))) + 8
        bx0 = max(153, round(end)) if not hero else 128
        by0, by1 = (ny, ny + 31) if hero else (at(9), at(40))
        if hero and end > 120:  # a long number pushes the reset box under it
            by0, by1 = ny + sl.num(16) + 10, ny + sl.num(16) + 41
        cv.draw.rectangle((bx0, by0, 228, by1), fill=outline_ink, outline=a, width=2)
        if sl.count == 4:  # a short row: just the time, centred in its box
            cv.text((bx0 + 6, (by0 + by1) // 2 - 4), reset.upper(), title(8), cream)
        else:
            cv.text((bx0 + 6, by0 + 5), 'RESET IN', title(sl.txt(8) if bx0 < 160 else 8), '#a9bdf0')
            cv.text((bx0 + 6, by0 + 18), reset.upper(), title(sl.txt(8) if bx0 < 160 else 8), cream)
        gy = y + h - 25 if hero else at(51)
        gh = max(12, round(15 * min(sl.k, 1.3)))
        cv.draw.rectangle((10, gy, 229, gy + gh), fill=outline_ink)
        cv.draw.rectangle((12, gy + 2, 227, gy + gh - 2), outline='#3a4fb0')
        gauge(cv, (14, gy + 4, 225, gy + gh - 4), used, band('retro', used or 0), gap=2, track='#19235f',
              empty='#3a4ea8', stale=old, shade=True, stepped=True)
    return cv.finish()


def retro_dual_windows(row):
    """The 5-hour and the weekly window, None where missing. A window of another length (Codex `WINDOW`,
    a Grok budget) fills whichever is empty, so a reported value is never dropped."""
    by_label = {w['label']: w for w in row['windows']}
    rest = iter([w for w in row['windows'] if w['label'] not in ('5H', 'WEEK')])
    return by_label.get('5H') or next(rest, None), by_label.get('WEEK') or next(rest, None)


def render_retro_dual(snapshot):
    """Pixel Retro cards with both the 5-hour and the weekly window per account, not just the more used one."""
    outline_ink, cream, dim, old_ink = '#0a0d26', '#fff3d6', '#b9d2ff', '#ff9a9a'
    ground = {'claude': '#371428', 'codex': '#05201a', 'grok': '#120c33', 'copilot': '#0a3f5b', 'antigravity': '#050514'}
    cv = Canvas('#0a0f2c')
    rnd = random.Random(5)
    for _ in range(70):
        cv.back.point((rnd.randrange(0, SIZE), rnd.randrange(0, SIZE)), fill=rnd.choice(('#ffffff', '#b9c8ff', '#ffe9a8')))
    title = lambda s: face('press-start-2p.ttf', s)
    rows = overview_rows(snapshot)
    # One or two services get tall cards with the mascot; three get compact cards without it.
    #       card height, label (x, dy), first line dy, line pitch, bar dy, bar height
    full = 116, (57, 12), 50, 31, 18, 11
    compact = 76, (12, 6), 16, 28, 17, 8
    with_mascot = len(rows) < 3
    card_h, (label_x, label_dy), first, pitch, bar_dy, bar_h = full if with_mascot else compact
    gap = 4
    top = (SIZE - len(rows) * card_h - (len(rows) - 1) * gap) // 2
    for index, row in enumerate(rows):
        y = top + index * (card_h + gap)
        a, _ = ACCENT['retro'][row['provider']]
        cv.back.rectangle((6, y + 2, 233, y + card_h - 3), fill=ground[row['provider']])
        pixel_scene(cv, row['provider'], y)
        cv.back.rectangle((4, y, 235, y + card_h - 1), outline=outline_ink, width=2)
        cv.back.rectangle((6, y + 2, 233, y + card_h - 3), outline=a, width=2)
        for cx, cy in ((4, y), (234, y), (4, y + card_h - 2), (234, y + card_h - 2)):
            cv.back.rectangle((cx, cy, cx + 1, cy + 1), fill='#0a0f2c')
        if with_mascot:
            cv.draw.rectangle((11, y + 8, 50, y + 47), fill=outline_ink, outline=a, width=2)
            if row['provider'] == 'grok':
                cv.draw.rectangle((16, y + 13, 45, y + 42), fill='#d9ccff')
            mascot(cv.ink, row['provider'], (7, y + 4), pixel=True, size=32)
        cv.text((label_x, y + label_dy), account_label(row), title(8), cream, stroke_width=1, stroke_fill=outline_ink)
        if not row['windows']:  # LOGIN, WAIT, NO DATA ...: say why both lines are empty
            cv.text((229, y + label_dy), reading(row)[1], title(8), old_ink, anchor='ra', stroke_width=1, stroke_fill=outline_ink)
        old = row['status'] != 'ok'
        for k, (default_name, w) in enumerate(zip(('5H', 'WK'), retro_dual_windows(row))):
            # A window nobody reported: a dash, no reset time and an empty bar.
            name, used, number, right, right_ink, stale = default_name, None, '--', '', cream, False
            if w:
                used = max(0, min(100, w['used_percent']))
                name, number, right = quota_period(w), number_text(used) + '%', time_left(w.get('resets_at')).upper()
                if old:
                    right, right_ink, stale = 'OLD ' + right, old_ink, True
            by = y + first + k * pitch
            cv.text((12, by + 5), name, title(8), dim, stroke_width=1, stroke_fill=outline_ink)
            number_x = max(38, 12 + round(cv.draw.textlength(name, font=title(8))) + 10)  # clear of a long name
            cv.text((number_x, by), number, title(16), cream, stroke_width=2, stroke_fill=outline_ink)
            cv.text((229, by + 5), right, title(8), right_ink, anchor='ra', stroke_width=1, stroke_fill=outline_ink)
            bar_top = by + bar_dy
            cv.draw.rectangle((10, bar_top, 229, bar_top + bar_h), fill=outline_ink)
            cv.draw.rectangle((11, bar_top + 1, 228, bar_top + bar_h - 1), outline='#3a4fb0')
            gauge(cv, (14, bar_top + 3, 225, bar_top + bar_h - 3), used, band('retro', used or 0), gap=2, track='#19235f',
                  empty='#3a4ea8', stale=stale, shade=True, stepped=True)
    return cv.finish()


def render_hud(snapshot):
    cv = Canvas('#03080e')
    for g in range(0, SIZE, 12):
        color = '#0b1a28' if g % 48 == 0 else '#06111b'
        cv.back.line((g, 0, g, SIZE), fill=color)
        cv.back.line((0, g, SIZE, g), fill=color)
    chakra = lambda s, bold=True: face('chakra-petch-700.woff2' if bold else 'chakra-petch-500.woff2', s)
    rows = overview_rows(snapshot)
    for sl, row in zip(slots(len(rows)), rows):
        y, at, hero, h = sl.y, sl.at, sl.count == 1, sl.h
        a, a2 = ACCENT['hud'][row['provider']]
        wins = shown_windows(row, sl.count)
        used, period, old, reset = reading(row, wins[0] if wins else None)
        cut = 10
        frame = [(4, y), (235 - cut, y), (235, y + cut), (235, y + h - 1), (4 + cut, y + h - 1), (4, y + h - 1 - cut)]
        cv.back.polygon(frame, fill=mix('#06101a', a, .05))
        cv.draw.polygon(frame, outline=mix(a, '#1b3b58', .45))
        cv.glow.line(frame + [frame[0]], fill=rgb(a) + (150,), width=2)
        cv.draw.line((8, y + 4, 8, y + 12), fill=a, width=2)
        cv.draw.line((8, y + 4, 16, y + 4), fill=a, width=2)
        cv.draw.line((231, y + h - 5, 231, y + h - 13), fill=a, width=2)
        cv.draw.line((231, y + h - 5, 223, y + h - 5), fill=a, width=2)
        # HUD: the row's accent colour as a hologram: solid bot with every other line dimmed.
        bw, bh = round(21 * sl.icon), round(19 * sl.icon)
        bot = (11, y + 10 if hero else at(8), bw, bh)
        place_bot(cv.ink, scanlined(bot_sprite(row['provider'], bw, bh, a)), bot)
        place_bot(cv.bloom, bot_sprite(row['provider'], bw, bh, a), bot)
        note = '' if len(wins) == 2 else ('OLD' if old else '') if sl.count == 4 else period + (' OLD' if old else '')
        room = 228 - (bw + 17) - (cv.draw.textlength(note, font=chakra(sl.txt(10), False)) + 8 if note else 0)
        cv.text((bw + 17, bot[1]), fit_text(cv.draw, account_label(row), chakra(sl.txt(14)), room), chakra(sl.txt(14)), '#ffffff')
        if len(wins) == 2:  # room for both windows: 5H above WEEK
            body = (12, bot[1] + bh + 4, 228, y + h - 8) if hero else (bw + 17, bot[1] + sl.txt(14) + 6, 228, y + h - 8)
            window_lines(cv, row, wins, body, {
                'label': lambda z: chakra(z, False), 'num': chakra, 'num_max': 42, 'ink': '#ffffff', 'dim': '#8fadc6',
                'old': '#ff4d6a', 'num_args': {'glow': rgb(a) + (110,)},
                'gauge': lambda u, o: {'colors': band('hud', u or 0), 'gap': 3, 'shape': 'skew', 'skew': 4,
                                       'track': '#0c1c2b', 'empty': '#22476a', 'stale': o, 'glow': True}})
            continue
        cv.text((228, bot[1] + 1), note, chakra(sl.txt(10), False), '#ff4d6a' if old else '#8fadc6', anchor='ra')
        number = number_text(used)
        ny = bot[1] + bh + 14 if hero else at(25)
        cv.text((12, ny), number, chakra(sl.num(30)), '#ffffff', glow=rgb(a) + (110,))
        if used is not None:
            x = 12 + cv.draw.textlength(number, font=chakra(sl.num(30))) + 2
            cv.text((x, ny + round(12 * sl.big)), '%', chakra(sl.num(16)), a, glow=rgb(a) + (200,))
        mid = ny + round(5 * sl.big)
        cv.draw.line((150, mid, 150, mid + round(22 * sl.big)), fill='#22476a')
        if sl.count < 4:
            cv.spaced((228, mid), 'RESETS IN', chakra(sl.txt(7), False), '#6c8aa5', 1.4, anchor='ra')
            cv.text((228, mid + sl.txt(10)), reset, chakra(sl.txt(17)), '#ffffff', anchor='ra')
        else:  # four rows: just the time, clear of the gauge
            cv.text((228, mid - 2), reset, chakra(sl.txt(17)), '#ffffff', anchor='ra')
        gy = y + h - 20 if hero else at(60)
        gauge(cv, (12, gy, 228, gy + max(6, round(8 * min(sl.k, 1.4)))), used, band('hud', used or 0), gap=3,
              shape='skew', skew=4, track='#0c1c2b', empty='#22476a', stale=old, glow=True)
    return cv.finish(blur=2)


GB_DARKEST, GB_DARK, GB_LIGHT, GB_LIGHTEST = '#0f380f', '#306230', '#8bac0f', '#9bbc0f'
GB_PALETTE = [GB_DARKEST, GB_DARK, GB_LIGHT, GB_LIGHTEST]


def to_four_shades(image):
    """Snap every pixel to the nearest of the four LCD shades (the real Game Boy had only four)."""
    palette = Image.new('P', (1, 1))
    flat = [int(c[i:i + 2], 16) for c in GB_PALETTE for i in (1, 3, 5)]
    palette.putpalette(flat + [0] * (768 - len(flat)))
    return image.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB')


def render_gameboy(data):
    cv = Canvas(GB_LIGHTEST)
    pixel = lambda size: face('press-start-2p.ttf', size)
    rows = overview_rows(data)
    for sl, row in zip(slots(len(rows), top=3, pitch=79, height=75), rows):
        y, at, hero, h = sl.y, sl.at, sl.count == 1, sl.h
        wins = shown_windows(row, sl.count)
        used, period, old, reset = reading(row, wins[0] if wins else None)  # used is None when nothing was reported
        cv.draw.rectangle((4, y, 235, y + h - 1), outline=GB_DARKEST, width=2)
        cv.draw.rectangle((7, y + 3, 232, y + h - 4), outline=GB_DARK, width=1)
        bw, bh = round(22 * sl.icon), round(18 * sl.icon)
        bot = (11, y + 8 if hero else at(7), bw, bh)
        place_bot(cv.ink, bot_sprite(row['provider'], bw, bh, GB_DARKEST, GB_LIGHTEST), bot)
        note = '' if len(wins) == 2 else ('OLD' if old else '') if sl.count == 4 else ('OLD ' if old else '') + period
        room = 229 - (bw + 16) - (cv.draw.textlength(note, font=pixel(sl.txt(8))) + 8 if note else 0)
        cv.text((bw + 16, bot[1] + 4), fit_text(cv.draw, account_label(row), pixel(sl.txt(8)), room), pixel(sl.txt(8)), GB_DARKEST)
        if len(wins) == 2:  # room for both windows: 5H above WEEK
            body = (12, bot[1] + bh + 6, 227, y + h - 7) if hero else (bw + 16, bot[1] + sl.txt(8) + 10, 227, y + h - 7)
            window_lines(cv, row, wins, body, {
                'label': pixel, 'num': pixel, 'num_max': 24, 'ink': GB_DARKEST, 'dim': GB_DARK, 'old': GB_DARK,
                'gauge': lambda u, o: {'colors': (GB_DARKEST, GB_DARK), 'gap': 2, 'track': GB_LIGHT, 'empty': GB_DARK,
                                       'stale': o}})
            continue
        cv.text((229, bot[1] + 4), note, pixel(sl.txt(8)), GB_DARK, anchor='ra')
        ny = bot[1] + bh + 16 if hero else at(31)
        cv.text((12, ny), number_text(used), pixel(sl.num(20)), GB_DARKEST)  # a dash, never a fake 0
        if used is not None:
            cv.text((12 + cv.draw.textlength(number_text(used), font=pixel(sl.num(20))) + 2, ny + round(8 * sl.big)), '%',
                    pixel(sl.num(10)), GB_DARKEST)
        ry = ny + sl.num(20) + 12 if hero else at(34)
        cv.text((229, ry), 'RESET', pixel(sl.txt(7)), GB_DARK, anchor='ra')
        cv.text((229, ry + sl.txt(11)), reset, pixel(sl.txt(8)), GB_DARKEST, anchor='ra')
        gy = y + h - 17 if hero else at(58)
        gauge(cv, (12, gy, 227, gy + max(6, round(8 * min(sl.k, 1.4)))), used, (GB_DARKEST, GB_DARK), gap=2,
              track=GB_LIGHT, empty=GB_DARK, stale=old)
    return to_four_shades(cv.finish())


RENDERERS = {'digital': render_digital, 'neon': render_neon, 'retro': render_retro, 'hud': render_hud, 'gameboy': render_gameboy,
             'retro-dual': render_retro_dual}
