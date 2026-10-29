"""The Arcade face's readout: the used %, the time to reset and the usage bar under the scene.

Four looks share one layout (the number on the left, the reset time on the right, the bar under them): 'lcd',
seven-segment digits drawn on the 2 px grid over their faint unlit strokes, with a bar from LCD_BARS (the owner's
pick, 2026-10-29); 'score', a tall arcade score font with a soft shadow and a rounded bar lit along its top;
'chips', a squared modern font and twenty 5% chips; 'pixel', the 5 x 7 pixel font and ten cells. Text from a font
is drawn without smoothing at half size and doubled, so it sits on the clock's 2 px grid like the rest.
"""
import functools
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from token_tv.display import pixel_text

STYLE = 'lcd'  # the look in use: 'lcd', 'score', 'chips' or 'pixel'
WEB = Path(__file__).with_name('web')
TEXT, MUTED, PANEL, TRACK = (226, 230, 238), (128, 138, 160), (11, 13, 19), (40, 46, 62)
BANDS = ((76, 201, 140), (140, 214, 92), (255, 160, 64), (255, 84, 96))  # below 50, 50–79, 80–89, 90+
LOOKS = {  # font, digits (size of one, of two lines), small text, the bar and its height (one, two lines), shadow, unlit
    'score': dict(font='jersey-10.woff2', big=30, mid=20, small=18, bar='capsule', bar_h=(10, 6), shadow=(44, 50, 70)),
    'chips': dict(font='chakra-petch-700.woff2', big=24, mid=14, small=14, bar='chips', bar_h=(8, 6)),
}


def band(used):
    return BANDS[0 if used < 50 else 1 if used < 80 else 2 if used < 90 else 3]


def shade(colour, k):
    return tuple(max(0, min(255, round(v * k))) for v in colour)


@functools.lru_cache(maxsize=256)
def crisp(text, font_file, size, colour):
    """`text` in a bundled font, unsmoothed at half size and doubled, on a transparent ground."""
    font = ImageFont.truetype(str(WEB / font_file), size)
    left, top, right, bottom = font.getbbox(text)
    mask = Image.new('L', (right - left + 2, bottom - top + 2))
    draw = ImageDraw.Draw(mask)
    draw.fontmode = '1'
    draw.text((1 - left, 1 - top), text, font=font, fill=255)
    mask = mask.crop(mask.getbbox() or (0, 0, 1, 1))
    mask = mask.resize((mask.width * 2, mask.height * 2), Image.Resampling.NEAREST).point(lambda v: 255 if v > 127 else 0)
    art = Image.new('RGBA', mask.size, colour + (0,))
    art.putalpha(mask)
    return art


def put(frame, art, x, y, align='left', shadow=None):
    """Paste `art` with its left (or right) edge at x; returns its right edge."""
    x = x - art.width if align == 'right' else x
    if shadow:
        under = Image.new('RGBA', art.size, shadow + (0,))
        under.putalpha(art.getchannel('A'))
        frame.paste(under, (x + 2, y + 2), under)
    frame.paste(art, (x, y), art)
    return x + art.width


# --- the bars ------------------------------------------------------------------------------------

def bar_capsule(draw, x, y, w, h, used, old):
    draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=h // 2, fill=TRACK)
    if used:
        fill = max(h, round(w * min(100, used) / 100))
        colour = MUTED if old else band(used)
        draw.rounded_rectangle((x, y, x + fill - 1, y + h - 1), radius=h // 2, fill=colour)
        if fill > h:
            draw.line((x + h // 2, y, x + fill - 1 - h // 2, y), fill=shade(colour, 1.25))
            draw.line((x + h // 2, y + h - 1, x + fill - 1 - h // 2, y + h - 1), fill=shade(colour, .7))
    for q in (.25, .5, .75):
        mx = x + round(w * q)
        draw.line((mx, y + 2, mx, y + h - 3), fill=PANEL)


def bar_chips(draw, x, y, w, h, used, old):
    n, gap = 20, 2
    pitch = (w - gap * (n - 1)) / n
    colour = MUTED if old else band(used or 0)
    for i in range(n):
        left, right = round(x + i * (pitch + gap)), round(x + i * (pitch + gap) + pitch) - 1
        part = 0 if not used else max(0, min(1, used / 5 - i))
        draw.rectangle((left, y, right, y + h - 1), fill=colour if part >= 1 else shade(colour, .55) if part > 0 else TRACK)
        for cx, cy in ((left, y), (right, y), (left, y + h - 1), (right, y + h - 1)):
            draw.point((cx, cy), fill=PANEL)


BARS = {'capsule': bar_capsule, 'chips': bar_chips}


def pixel_bar(draw, x, y, width, height, used, old):
    """The first look's ten cells."""
    step = width / 10
    for cell in range(10):
        left, right = round(x + cell * step), round(x + (cell + 1) * step) - 2
        draw.rectangle((left, y, right, y + height - 1), fill=TRACK)
        if used is not None and used > cell * 10:
            fill = min(1, used / 10 - cell)
            draw.rectangle((left, y, left + max(1, round((right - left + 1) * fill)) - 1, y + height - 1),
                           fill=MUTED if old else band(used))


# --- the readout -------------------------------------------------------------------------------

def number(frame, look, value, x, bottom, size, old):
    """The used % with its digits standing on `bottom` and a smaller % at their top right."""
    ink = MUTED if old else TEXT
    digits = crisp(value, look['font'], size, ink)
    if look.get('unlit') and value != '--':
        unlit = crisp('8' * len(value), look['font'], size, look['unlit'])
        put(frame, unlit, x, bottom - unlit.height)
    right = put(frame, digits, x, bottom - digits.height, shadow=look.get('shadow'))
    if value != '--':
        sign = crisp('%', look.get('words', look['font']), size // 2 + 2, MUTED)
        put(frame, sign, right + 4, bottom - digits.height)


def draw_readout(frame, draw, windows, style=None):
    """Draw the readout for one window [(label, used, left, old)] or two (5H above the week)."""
    style = style or STYLE
    if style == 'lcd':
        draw_lcd(frame, draw, windows)
        return
    if style not in LOOKS:  # the first look: the 5 x 7 pixel font
        if len(windows) == 1:
            _, used, left, old = windows[0]
            pixel_text(draw, (10, 184), '--' if used is None else f'{round(used)}%', scale=5, color=MUTED if old else TEXT)
            pixel_text(draw, (230, 186), 'RESET', scale=1, color=MUTED, align='right')
            pixel_text(draw, (230, 198), left, scale=3, color=TEXT, align='right')
            pixel_bar(draw, 10, 226, 222, 7, used, old)
            return
        for i, (label, used, left, old) in enumerate(windows):
            top = 180 + i * 31
            pixel_text(draw, (10, top + 4), label, color=MUTED)
            pixel_text(draw, (30, top), '--' if used is None else f'{round(used)}%', scale=3, color=MUTED if old else TEXT)
            pixel_text(draw, (230, top + 4), left, scale=2, color=TEXT, align='right')
            pixel_bar(draw, 10, top + 24, 222, 4, used, old)
        return
    look = LOOKS[style]
    words = look.get('words', look['font'])
    bar = BARS[look['bar']]
    if len(windows) == 1:
        _, used, left, old = windows[0]
        base = 216  # the baseline the number and the reset time stand on
        number(frame, look, '--' if used is None else str(round(used)), 10, base, look['big'], old)
        when = crisp(left, words, look['small'], TEXT)
        put(frame, when, 230, base - when.height, align='right')
        pixel_text(draw, (230, base - when.height - 11), 'RESET', scale=1, color=MUTED, align='right')
        bar(draw, 10, 224, 220, look['bar_h'][0], used, old)
        return
    for i, (label, used, left, old) in enumerate(windows):
        base = 194 + i * 33
        pixel_text(draw, (10, base - 7), label, color=MUTED)
        number(frame, look, '--' if used is None else str(round(used)), 30, base, look['mid'], old)
        when = crisp(left, words, look['mid'], TEXT)
        put(frame, when, 230, base - when.height, align='right')
        bar(draw, 10, base + 4, 220, look['bar_h'][1], used, old)


# --- 'lcd': seven-segment digits drawn on the 2 px grid -------------------------------------------
# Each digit is seven strokes on the 2 px grid, the unlit ones faint as on a real LCD, stopping short of the
# corners with the small gaps of a real display. The reset time's unit (D, H, M) stands small beside its digits.
SEGMENTS = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd', '6': 'afgedc',
            '7': 'abc', '8': 'abcdefg', '9': 'abcdfg', '-': 'g'}
UNLIT = (21, 24, 33)  # just above the panel: there if you look, quiet if you glance
SEVEN = {'big': (10, 19, 2), 'mid': (8, 13, 1), 'small': (7, 11, 1)}  # cells wide, high, stroke (cells of 2 px)


def seven(draw, x, y, char, size, ink, unlit=UNLIT):
    """One seven-segment character with its top left at (x, y) in px; returns its width in px."""
    w, h, t = SEVEN[size]
    lit = SEGMENTS.get(char, '')
    mid = (h - t) // 2
    strokes = {'a': (t, 0, w - 2 * t, t), 'g': (t, mid, w - 2 * t, t), 'd': (t, h - t, w - 2 * t, t),
               'f': (0, t, t, mid - t), 'b': (w - t, t, t, mid - t),
               'e': (0, mid + t, t, h - mid - 2 * t), 'c': (w - t, mid + t, t, h - mid - 2 * t)}
    for name, (cx, cy, cw, ch) in strokes.items():  # the strokes stop short of the corners, as on a display
        draw.rectangle((x + 2 * cx, y + 2 * cy, x + 2 * (cx + cw) - 1, y + 2 * (cy + ch) - 1),
                       fill=ink if name in lit else unlit)
    return 2 * w


def seven_text(draw, x, y, text, size, ink, gap=None):
    """A row of seven-segment characters from (x, y); returns the right edge."""
    w, h, t = SEVEN[size]
    gap = 2 * t if gap is None else gap
    for n, char in enumerate(text):
        x += seven(draw, x, y, char, size, ink) + (gap if n < len(text) - 1 else 0)
    return x


def seven_width(text, size, gap=None):
    w, h, t = SEVEN[size]
    gap = 2 * t if gap is None else gap
    return len(text) * 2 * w + (len(text) - 1) * gap


def reset_parts(left):
    """'4D' -> ('4', 'D'); '--' -> ('--', '')."""
    digits = ''.join(c for c in left if c.isdigit() or c == '-')
    return digits or '--', ''.join(c for c in left if c.isalpha())


# --- bars for the lcd look ------------------------------------------------------------------------

def bar_cells(draw, x, y, w, h, used, old):
    """Twenty-two narrow cells, lit to the level and faint beyond, like an LCD's level meter."""
    n, gap = 22, 2
    cell = (w - gap * (n - 1)) / n
    colour = MUTED if old else band(used or 0)
    for i in range(n):
        left, right = round(x + i * (cell + gap)), round(x + i * (cell + gap) + cell) - 1
        on = used is not None and used >= (i + .5) * 100 / n
        draw.rectangle((left, y, right, y + h - 1), fill=colour if on else UNLIT)


def bar_ticks(draw, x, y, w, h, used, old):
    """A solid bar under a scale: a mark every 10%, longer at 50% and 100%, and a pointer at the level."""
    for k in range(11):
        mx = x + round((w - 2) * k / 10)
        draw.rectangle((mx, y, mx + 1, y + (3 if k % 5 == 0 else 1)), fill=(58, 64, 84))
    top = y + 6
    draw.rectangle((x, top, x + w - 1, top + h - 1), fill=TRACK)
    if used:
        fill = round(w * min(100, used) / 100)
        colour = MUTED if old else band(used)
        draw.rectangle((x, top, x + fill - 1, top + h - 1), fill=colour)
        draw.polygon(((x + fill - 4, y), (x + fill + 3, y), (x + fill - 1, y + 4)), fill=colour)


def bar_dots(draw, x, y, w, h, used, old):
    """A row of dots, lit to the level, with a bigger dot where it stands."""
    n = w // 4
    colour = MUTED if old else band(used or 0)
    lit = 0 if used is None else round(n * min(100, used) / 100)
    mid = y + h // 2
    for i in range(n):
        dx = x + i * 4
        draw.rectangle((dx, mid - 1, dx + 1, mid), fill=colour if i < lit else TRACK)
    if lit:
        hx = x + (lit - 1) * 4
        draw.rectangle((hx - 1, mid - 3, hx + 2, mid + 2), fill=colour)


def bar_zones(draw, x, y, w, h, used, old):
    """The track coloured faintly by zone (under 50, to 80, to 90, the last 10%), filled bright in each zone's
    colour up to the level, so the warning thresholds sit where the eye expects them."""
    edges = ((0, 50), (50, 80), (80, 90), (90, 100))
    for k, (a, b) in enumerate(edges):
        left, right = x + round(w * a / 100), x + round(w * b / 100) - 1 - (2 if b < 100 else 0)
        draw.rectangle((left, y, right, y + h - 1), fill=shade(BANDS[k], .22))
        if used and used > a:
            end = min(right, x + round(w * min(used, b) / 100) - 1)
            draw.rectangle((left, y, end, y + h - 1), fill=MUTED if old else BANDS[k])


LCD_BARS = {'cells': bar_cells, 'ticks': bar_ticks, 'dots': bar_dots, 'zones': bar_zones}
LCD_BAR = 'capsule'  # the bar under the lcd digits (the owner's pick: the rounded one from the table)


def draw_lcd(frame, draw, windows, bar_style=None):
    """The 'lcd' look: seven-segment digits with their faint unlit strokes, a small % and the reset time's unit."""
    bar = LCD_BARS[bar_style or LCD_BAR]
    if len(windows) == 1:
        _, used, left, old = windows[0]
        ink = MUTED if old else TEXT
        number = '--' if used is None else str(round(used))
        top = 178
        right = seven_text(draw, 10, top, number, 'big', ink)
        if used is not None:
            pixel_text(draw, (right + 6, top), '%', scale=2, color=MUTED)
        digits, unit = reset_parts(left)
        unit_w = (len(unit) * 6 - 1) * 2 if unit else 0
        dx = 230 - unit_w - (4 if unit else 0) - seven_width(digits, 'small')
        seven_text(draw, dx, 196, digits, 'small', TEXT)
        if unit:
            pixel_text(draw, (230, 202), unit, scale=2, color=MUTED, align='right')
        pixel_text(draw, (230, 183), 'RESET', scale=1, color=MUTED, align='right')
        bar(draw, 10, 224, 220, 4 if bar is bar_ticks else 10 if (bar_style or LCD_BAR).startswith('capsule') else 8, used, old)
        return
    for i, (label, used, left, old) in enumerate(windows):
        top = 172 + i * 33
        pixel_text(draw, (10, top + 15), label, color=MUTED)
        ink = MUTED if old else TEXT
        number = '--' if used is None else str(round(used))
        right = seven_text(draw, 30, top, number, 'mid', ink)
        if used is not None:
            pixel_text(draw, (right + 4, top), '%', scale=1, color=MUTED)
        digits, unit = reset_parts(left)
        unit_w = (len(unit) * 6 - 1) * 2 if unit else 0
        seven_text(draw, 230 - unit_w - (4 if unit else 0) - seven_width(digits, 'mid'), top, digits, 'mid', TEXT)
        if unit:
            pixel_text(draw, (230, top + 8), unit, scale=2, color=MUTED, align='right')
        if bar is bar_ticks:
            bar(draw, 10, top + 23, 220, 3, used, old)
        else:
            bar(draw, 10, top + 25, 220, 6 if (bar_style or LCD_BAR).startswith('capsule') else 5, used, old)


# --- the rounded bar from the table, plain or with a little gradient ---------------------------------

def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def capsule_fill(draw, x, y, w, h, used, old, colour_at):
    """The rounded track and a fill to the level, each column coloured by colour_at(column 0..1, row 0..1),
    with marks at the quarters; corners rounded on the 2 px grid."""
    draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=h // 2, fill=TRACK)
    if used:
        fill = max(h, round(w * min(100, used) / 100))
        mask = Image.new('L', (fill, h))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, fill - 1, h - 1), radius=h // 2, fill=255)
        for cx in range(0, fill, 2):
            for cy in range(0, h, 2):
                if mask.getpixel((cx, cy)):
                    colour = MUTED if old else colour_at(cx / max(1, w - 1), cy / max(1, h - 1), used)
                    draw.rectangle((x + cx, y + cy, x + min(fill - 1, cx + 1), y + min(h - 1, cy + 1)), fill=colour)
    for q in (.25, .5, .75):
        mx = x + round(w * q)
        draw.line((mx, y + 2, mx, y + h - 3), fill=PANEL)


def plain(px, py, used):
    colour = band(used)
    return shade(colour, 1.25) if py == 0 else shade(colour, .72) if py >= .99 else colour


def along(px, py, used):  # a little darker where the bar starts, full colour at its head
    colour = band(used)
    t = min(1, px / max(.01, used / 100))
    step = round(t * 5) / 5  # five steps, as pixel art would
    base = mix(shade(colour, .7), colour, step)
    return shade(base, 1.22) if py == 0 else shade(base, .75) if py >= .99 else base


def lit(px, py, used):  # lit from above: a soft top-to-bottom ramp
    colour = band(used)
    k = (1.3, 1.12, 1.0, 1.0, .9, .78)[min(5, int(py * 6))]
    return shade(colour, k)


def heat(px, py, used):  # the colour of where it is: green, then yellow-green, amber and red along the bar
    stops = ((0, BANDS[0]), (.5, BANDS[0]), (.65, BANDS[1]), (.85, BANDS[2]), (1, BANDS[3]))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if px <= b:
            t = 0 if b == a else (px - a) / (b - a)
            base = mix(ca, cb, round(t * 4) / 4)
            break
    return shade(base, 1.22) if py == 0 else shade(base, .75) if py >= .99 else base


def bar_capsule_plain(draw, x, y, w, h, used, old):
    capsule_fill(draw, x, y, w, h, used, old, plain)


def bar_capsule_along(draw, x, y, w, h, used, old):
    capsule_fill(draw, x, y, w, h, used, old, along)


def bar_capsule_lit(draw, x, y, w, h, used, old):
    capsule_fill(draw, x, y, w, h, used, old, lit)


def bar_capsule_heat(draw, x, y, w, h, used, old):
    capsule_fill(draw, x, y, w, h, used, old, heat)


LCD_BARS.update({'capsule': bar_capsule_plain, 'capsule_along': bar_capsule_along, 'capsule_lit': bar_capsule_lit,
                 'capsule_heat': bar_capsule_heat})
