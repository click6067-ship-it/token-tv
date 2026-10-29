"""A three-row desk instrument; the web retains every account's details.

Hallmark · component: LCD overview · genre: instrument · scope: 240×240
Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 (self-review)
"""
import io
import math
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BACKGROUND = '#0b0e12'
# Text and brand inks; usage levels affect gauges only.
# Numeric text stays gray, with OLD/LOGIN carrying data status.
TEXT = '#d9dde1'
MUTED = TEXT
TRACK = '#28313a'
RULE = '#202730'
OLD_INK = '#e0a860'  # an old reading's label, so it never looks fresh
PROVIDER_INK = {'claude': '#d68e68', 'codex': '#a799e5', 'grok': '#cbd1d7', 'copilot': '#3fb6e8', 'antigravity': '#78b6ee'}
# Each service's own colour, the source for every new style (older faces keep their tuned accents):
# Claude orange, Codex navy with a light lavender, Grok white, Copilot a teal-to-blue gradient.
BRAND = {'claude': ('#d97757',), 'codex': ('#2f3aa8', '#9aa0ff'), 'grok': ('#f2f4f8',),
         'copilot': ('#36d8b4', '#1fa7e2', '#2563eb'), 'antigravity': ('#e77345', '#94c45f', '#4f83f2')}
FONT_MAIN = '/usr/share/fonts/truetype/dejavu/DejaVuSans'
FONT_NUMBERS = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono'
STYLES = ('pixel', 'digital', 'neon', 'retro', 'hud', 'space', 'gameboy', 'arcade', 'retro-dual')
# Gauge-only levels; labels/percentages always use TEXT, logos retain provider ink.
GAUGE_LEVELS = ((50, '#76a99a'), (80, '#93c9b9'), (90, '#d1b275'), (101, '#d8877e'))
STATUS = {'loading': 'WAIT', 'auth_required': 'LOGIN', 'identity_mismatch': 'CHECK',
          'quota_unavailable': 'NO DATA', 'error': 'ERROR', 'rate_limited': 'RETRY', 'stale': 'OLD'}
PROVIDERS = ('claude', 'codex', 'grok', 'copilot', 'antigravity')
ASSETS = Path(__file__).with_name('assets')


def font(size, bold=False, mono=False):
    candidates = [os.environ.get('TOKEN_TV_FONT', ''),
                  (FONT_NUMBERS if mono else FONT_MAIN) + ('-Bold' if bold else '') + '.ttf',
                  '~/.local/share/fonts/malgun.ttf']
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if candidate and path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


MAX_ROWS = 4  # four rows still read on a 240 px screen; Arcade takes turns on any number


def has_reading(row):
    return row['status'] in ('ok', 'stale') and bool(row['windows'])


def overview_rows(snapshot):
    """Each account gets its own row, at most four: working ones first, then the fullest, then setup order.

    The chosen rows keep service order (Claude, Codex, Grok) and setup order within a service, so a row
    does not jump about when another account's usage passes it. Accounts without a reading only fill
    rows that are left. With no accounts at all, every service keeps a placeholder row.
    """
    accounts = [dict(row, key=key) for key, row in snapshot['accounts'].items()]
    if not accounts:
        return [{'key': p, 'provider': p, 'alias': p.upper() + ' A', 'status': 'auth_required', 'windows': []}
                for p in PROVIDERS]

    def rank(i):
        row = accounts[i]
        value = primary_window(row) if has_reading(row) else None
        return (not has_reading(row), not row.get('active'), -(value['used_percent'] if value else -1), i)

    def service(i):
        provider = accounts[i]['provider']
        return PROVIDERS.index(provider) if provider in PROVIDERS else len(PROVIDERS)

    chosen = sorted(range(len(accounts)), key=rank)[:MAX_ROWS]
    return [accounts[i] for i in sorted(chosen, key=lambda i: (service(i), i))]


class Slot:
    """One row's place: its top, its height, and how far its type grows for one to four rows.

    `at(v)` maps an offset drawn for the three-row height to this row; `num` and `txt` scale the big
    numbers and the smaller labels, so three rows look exactly as they always did.
    """
    GROW = {1: (2.0, 1.4, 1.8), 2: (1.4, 1.15, 1.3), 3: (1.0, 1.0, 1.0), 4: (.8, .95, .75)}

    def __init__(self, y, h, count, base):
        self.y, self.h, self.count, self.k = y, h, count, h / base
        self.big, self.small, self.icon = self.GROW[count]

    def at(self, v):
        return self.y + round(v * self.k)

    def num(self, size):
        return max(6, round(size * self.big))

    def txt(self, size):
        return max(6, round(size * self.small))


def slots(count, top=3, pitch=79, height=76):
    """Row places for `count` rows (one to four) over the span three rows of `height` every `pitch` take."""
    count = max(1, min(MAX_ROWS, count))
    gap = pitch - height
    h = (2 * pitch + height - (count - 1) * gap) / count
    return [Slot(round(top + i * (h + gap)), round(h), count, height) for i in range(count)]


def row_shift(count, pitch):
    """Vertical offset that centres `count` rows on a screen laid out for three."""
    return (3 - count) * pitch // 2


def pages(snapshot):
    return [('OVERVIEW', overview_rows(snapshot))]


def primary_window(row):
    return max(row['windows'], key=lambda value: value['used_percent'], default=None)


def time_left(reset):
    if not reset:
        return '--'
    minutes = max(0, int((reset - time.time() + 59) // 60))
    if minutes >= 1440:
        return str(minutes // 1440) + 'd ' + str(minutes % 1440 // 60) + 'h'
    return str(minutes // 60) + 'h ' + str(minutes % 60) + 'm'


def mascot(image, provider, xy, pixel=False, size=40, box=48):
    path = ASSETS / (provider + '-pixel.png')
    if path.is_file():
        with Image.open(path) as original:
            icon = original.convert('RGBA')
            bounds = icon.getbbox()
            if bounds:
                icon = icon.crop(bounds)
            scale = (size / 2 if pixel else size) / max(icon.size)
            icon = icon.resize((round(icon.width * scale), round(icon.height * scale)), Image.Resampling.NEAREST)
            if pixel:
                icon = icon.resize((icon.width * 2, icon.height * 2), Image.Resampling.NEAREST)
            x, y = xy
            image.paste(icon, (x + (box - icon.width) // 2, y + (box - icon.height) // 2), icon)
    else:
        ImageDraw.Draw(image).text((xy[0]+16, xy[1]+12), provider[0].upper(), font=font(22, True), fill=PROVIDER_INK[provider])


def gauge_color(used, segment=9):
    base = next(color for upper, color in GAUGE_LEVELS if used < upper)
    # A short ramp within one hue: the last filled cell is the brightest.
    last = max(1, math.ceil(used / 10) - 1)
    strength = .78 + .22 * min(1, segment / last)
    return tuple(round(int(base[i:i + 2], 16) * strength) for i in (1, 3, 5))


def horizontal_gauge(draw, xy, used, step=16, width=14, height=4, rounded=False, track=TRACK):
    for segment in range(10):
        x, y = xy[0] + segment * step, xy[1]
        box = (x, y, x + width - 1, y + height - 1)
        if rounded:
            draw.rounded_rectangle(box, radius=1, fill=track)
        else:
            draw.rectangle(box, fill=track)
        filled = round(max(0, min(1, used / 10 - segment)) * width) if used is not None else 0
        if filled:
            box = (x, y, x + filled - 1, y + height - 1)
            color = gauge_color(used, segment)
            if rounded:
                draw.rounded_rectangle(box, radius=1, fill=color)
            else:
                draw.rectangle(box, fill=color)


SHORT_NAME = {'antigravity': 'ANTI'}  # names too long for a clock's header
OLD_NAMES = {'antigravity': ('ANTIGRAVITY ', 'GEMINI ')}  # aliases from before Google's pet was Anti


def account_label(row):
    """The account's name on the clock: its service's name and its own letter ('CLAUDE B'), whatever the alias."""
    name = SHORT_NAME.get(row['provider'], row['provider'].upper())
    alias = row['alias']
    for old in OLD_NAMES.get(row['provider'], ()):
        if alias.startswith(old):
            alias = name + ' ' + alias[len(old):]
    return alias if alias.startswith(name + ' ') else name + ' A'


def quota_period(value):
    return {'WEEK': 'WK', 'BUDGET': 'BUD', 'MONTH': 'MO', 'DAY': 'DAY'}.get(value['label'], value['label'])


def shown_windows(row, count):
    """The windows a row shows: 5H and WEEK together while there is room (one or two rows), else WEEK.

    An account without a weekly window shows its fullest one; with no windows the list is empty.
    """
    by_label = {w['label']: w for w in row['windows']}
    if count <= 2 and '5H' in by_label and 'WEEK' in by_label:
        return [by_label['5H'], by_label['WEEK']]
    if 'WEEK' in by_label:
        return [by_label['WEEK']]
    value = primary_window(row)
    return [value] if value else []


FULLEST = object()


def reading(row, value=FULLEST):
    """(used %, window label, old?, time left) for one window (the fullest by default); used is None when
    nothing was reported."""
    if value is FULLEST:
        value = primary_window(row)
    used = max(0, min(100, value['used_percent'])) if value else None
    period = quota_period(value) if value else STATUS.get(row['status'], 'NO DATA')
    old = bool(value) and row['status'] != 'ok'
    reset = time_left(value.get('resets_at')) if value else '--'
    return used, period, old, reset


def watch_payload(snapshot):
    """Flat JSON for Apple Watch complication apps that read one value by path, e.g. accounts.claude_a.used_percent.

    Accounts are keyed by the label the clock shows (CLAUDE A -> claude_a), not by config keys, which can say
    whose account it is."""
    accounts, parts = {}, []
    for row in snapshot['accounts'].values():
        key = base = account_label(row).lower().replace(' ', '_')
        number = 1
        while key in accounts:
            number += 1
            key = f'{base}_{number}'
        used, period, old, reset = reading(row)
        used = None if used is None else round(used)
        value = primary_window(row)
        text = period if used is None else f'{used}% {period}' + (' OLD' if old else '')
        accounts[key] = {'label': account_label(row), 'used_percent': used,
                         'used': None if used is None else used / 100, 'window': None if used is None else period,
                         'resets_in': reset, 'resets_at': round(value['resets_at']) if value and value.get('resets_at') else None,
                         'text': text, 'state': 'missing' if used is None else 'old' if old else 'ok'}
        parts.append(f'{account_label(row)} {text}')
    return {'updated_at': snapshot['updated_at'], 'summary': ' · '.join(parts) or 'NO ACCOUNTS', 'accounts': accounts}


# A code-native 5×7 alphabet keeps LCD text on a visible pixel grid.
PIXEL_GLYPHS = {
    'A': '01110/10001/10001/11111/10001/10001/10001',
    'B': '11110/10001/10001/11110/10001/10001/11110',
    'C': '01111/10000/10000/10000/10000/10000/01111',
    'D': '11110/10001/10001/10001/10001/10001/11110',
    'E': '11111/10000/10000/11110/10000/10000/11111',
    'F': '11111/10000/10000/11110/10000/10000/10000',
    'G': '01111/10000/10000/10111/10001/10001/01111',
    'H': '10001/10001/10001/11111/10001/10001/10001',
    'I': '11111/00100/00100/00100/00100/00100/11111',
    'J': '00111/00010/00010/00010/00010/10010/01100',
    'K': '10001/10010/10100/11000/10100/10010/10001',
    'L': '10000/10000/10000/10000/10000/10000/11111',
    'M': '10001/11011/10101/10101/10001/10001/10001',
    'N': '10001/11001/10101/10011/10001/10001/10001',
    'O': '01110/10001/10001/10001/10001/10001/01110',
    'P': '11110/10001/10001/11110/10000/10000/10000',
    'Q': '01110/10001/10001/10001/10101/10010/01101',
    'R': '11110/10001/10001/11110/10100/10010/10001',
    'S': '01111/10000/10000/01110/00001/00001/11110',
    'T': '11111/00100/00100/00100/00100/00100/00100',
    'U': '10001/10001/10001/10001/10001/10001/01110',
    'V': '10001/10001/10001/10001/10001/01010/00100',
    'W': '10001/10001/10001/10101/10101/10101/01010',
    'X': '10001/10001/01010/00100/01010/10001/10001',
    'Y': '10001/10001/01010/00100/00100/00100/00100',
    'Z': '11111/00001/00010/00100/01000/10000/11111',
    '0': '01110/10001/10011/10101/11001/10001/01110',
    '1': '00100/01100/00100/00100/00100/00100/01110',
    '2': '01110/10001/00001/00010/00100/01000/11111',
    '3': '11110/00001/00001/01110/00001/00001/11110',
    '4': '00010/00110/01010/10010/11111/00010/00010',
    '5': '11111/10000/10000/11110/00001/00001/11110',
    '6': '01110/10000/10000/11110/10001/10001/01110',
    '7': '11111/00001/00010/00100/01000/01000/01000',
    '8': '01110/10001/10001/01110/10001/10001/01110',
    '9': '01110/10001/10001/01111/00001/00001/01110',
    '%': '11001/11010/00010/00100/01000/01011/10011',
    '-': '00000/00000/00000/11111/00000/00000/00000',
    '?': '01110/10001/00001/00010/00100/00000/00100',
    '.': '00000/00000/00000/00000/00000/01100/01100',
    '!': '00100/00100/00100/00100/00100/00000/00100',
    ':': '00000/01100/01100/00000/01100/01100/00000',
    ' ': '00000/00000/00000/00000/00000/00000/00000',
}


def without_service(text):
    """An account name without its leading service word ('COPILOT TEAM' → 'TEAM'): the mascot already
    says which service it is, so this is what to keep when space runs out."""
    first, _, rest = str(text).partition(' ')
    return rest if rest and first.lower() in PROVIDERS else text


def fit_pixel(text, scale, width):
    """`text` in the 5×7 font, cut to `width` px: first without its service word, then with '..'."""
    text = str(text).upper()
    for option in (text, without_service(text)):
        if (len(option) * 6 - 1) * scale <= width:
            return option
    text = without_service(text)
    keep = max(1, (width // scale + 1) // 6 - 2)
    return text[:keep].rstrip() + '..'


def fit_text(draw, text, font, width):
    """`text` in a TrueType `font`, cut to `width` px: first without its service word, then with '..'."""
    for option in (text, without_service(text)):
        if draw.textlength(option, font=font) <= width:
            return option
    text = without_service(text)
    while text and draw.textlength(text.rstrip() + '..', font=font) > width:
        text = text[:-1]
    return text.rstrip() + '..'


def pixel_text(draw, xy, text, scale=1, color=TEXT, align='left'):
    text = str(text).upper()
    width = max(0, len(text) * 6 - 1) * scale
    x, y = xy
    if align == 'right':
        x -= width
    elif align == 'center':
        x -= width // 2
    for index, character in enumerate(text):
        pattern = PIXEL_GLYPHS.get(character, PIXEL_GLYPHS['?']).split('/')
        for yy, line in enumerate(pattern):
            for xx, bit in enumerate(line):
                if bit == '1':
                    px = x + (index * 6 + xx) * scale
                    py = y + yy * scale
                    draw.rectangle((px, py, px + scale - 1, py + scale - 1), fill=color)


def pixel_window_lines(draw, row, wins, box, scale):
    """Both windows (5H above WEEK) in a roomy Pixel row: name, number, reset and a gauge each."""
    x0, y0, x1, y1 = box
    line = (y1 - y0) / len(wins)
    for i, value in enumerate(wins):
        used, period, old, reset = reading(row, value)
        top = round(y0 + i * line)
        small = 2 if scale >= 4 else 1
        mid = top + (line - 10) / 2 - 7 * scale / 2
        name = period + (' OLD' if old else '')
        pixel_text(draw, (x0, round(mid + 7 * (scale - small) / 2)), name, scale=small, color=OLD_INK if old else MUTED)
        nx = x0 + (len(name) * 6 + 2) * small
        number = '--' if used is None else f'{round(used)}%'
        pixel_text(draw, (nx, round(mid)), number, scale=scale, color=MUTED if old else TEXT)
        pixel_text(draw, (x1, round(mid + 7 * (scale - small) / 2)), reset.replace(' ', ''), scale=small, color=MUTED,
                   align='right')
        step = (x1 - x0) // 10
        horizontal_gauge(draw, (x0, round(top + line - 8)), used, step=step, width=step - 2, height=4 if scale >= 4 else 3)


def render_pixel(snapshot):
    image = Image.new('RGB', (240, 240), BACKGROUND)
    draw = ImageDraw.Draw(image)
    rows = overview_rows(snapshot)
    for index, (sl, row) in enumerate(zip(slots(len(rows), top=8, pitch=78, height=72), rows)):
        y, at, hero = sl.y, sl.at, sl.count == 1
        if index:
            for x in range(14, 227, 4):
                draw.point((x, y - 6), fill=RULE)
        box = round(48 * sl.icon)
        mx, my = 14, (y + 6 if hero else at(10))
        if row['provider'] == 'grok':  # white with dark eyes, as on every full-colour face
            from token_tv.themes import bot_sprite
            half = round(20 * sl.icon)
            art = bot_sprite('grok', half, half, '#f2f4f8', (12, 14, 20))
            art = art.resize((art.width * 2, art.height * 2), Image.Resampling.NEAREST)
            image.paste(art, (mx + (box - art.width) // 2, my + (box - art.height) // 2), art)
        else:
            mascot(image, row['provider'], (mx, my), pixel=True, size=round(40 * sl.icon), box=box)
        label = row['alias']
        if not label.startswith(row['provider'].upper() + ' '):
            label = row['provider'].upper() + ' A'
        wins = shown_windows(row, sl.count)  # 5H and WEEK on roomy rows, else the weekly one
        value = wins[0] if wins else None
        used = max(0, min(100, value['used_percent'])) if value else None
        old = bool(value) and row['status'] != 'ok'
        number = '--' if used is None else str(round(used)) + '%'
        tx = mx + box + 6
        n = max(2, round(3 * sl.big))
        r = 3 if hero else 2
        period = quota_period(value) if value else ''
        reset = time_left(value.get('resets_at')).replace(' ', '') if value else STATUS.get(row['status'], 'NO DATA')
        if len(wins) == 2:  # room for both windows: 5H above WEEK
            pixel_text(draw, (tx, y + 14 if hero else at(3)), fit_pixel(label, 2, 226 - tx), scale=2)
            body = (14, my + box + 10, 226, y + sl.h - 4) if hero else (tx, at(3) + 20, 226, y + sl.h - 4)
            pixel_window_lines(draw, row, wins, body, 4 if hero else 3)
            continue
        if hero:  # one account: the bot and its name on top, a big number below, the reset under it
            pixel_text(draw, (tx, y + 14), fit_pixel(label, 2, 226 - tx), scale=2)
            if value:
                pixel_text(draw, (tx, y + 40), period + (' OLD' if old else ' USED'), color=MUTED)
            top = my + box + 14
            pixel_text(draw, (14, top), number, scale=n, color=TEXT)
            pixel_text(draw, (226, top + 7 * n + 12), reset, scale=r, color=MUTED, align='right')
            horizontal_gauge(draw, (14, y + sl.h - 16), used, step=21, width=19, height=8)
            continue
        note = ('OLD' if old else '') if sl.count == 4 else period + (' OLD' if old else ' USED') if value else ''
        size = 2 if sl.count == 2 else 1
        room = 226 - tx - ((len(note) * 6 - 1) + 6 if note else 0)
        pixel_text(draw, (tx, at(3)), fit_pixel(label, size, room), scale=size)
        pixel_text(draw, (tx, at(21)), number, scale=n, color=TEXT)
        if note:
            pixel_text(draw, (226, at(3)), note, color=OLD_INK if old else MUTED, align='right')
        pixel_text(draw, (226, at(25)), reset, scale=r if value else 1, color=MUTED, align='right')
        step = (226 - tx) // 10
        horizontal_gauge(draw, (tx, at(52)), used, step=step, width=step - 2,
                         height=max(3, round(4 * sl.small)))
    return image


def render_page(snapshot, page=0, style='pixel', egg=None):
    # Keep the former second-frame URL usable while publishing only one LCD image.
    if page not in (0, 1):
        raise IndexError('Unknown frame')
    if style not in STYLES:
        raise ValueError('Unknown display style')
    if style == 'space':  # animated: returns GIF bytes
        from token_tv.space import render_space
        return render_space(snapshot)
    if style == 'arcade':  # animated: the mascots act while their account is in use
        from token_tv.arcade import render_arcade
        return render_arcade(snapshot, egg=egg)
    from token_tv.themes import RENDERERS
    renderer = {'pixel': render_pixel, **RENDERERS}[style]
    image = renderer(snapshot)
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=92, subsampling=0)
    return buffer.getvalue()


HTML = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TokenTV · Account usage</title>
<style>
:root{--color-text:#d9dde1;--color-claude:#d68e68;--color-codex:#a799e5;--color-grok:#cbd1d7;--color-level-low:#76a99a;--color-level-medium:#93c9b9;--color-level-high:#d1b275;--color-level-critical:#d8877e;color-scheme:dark;font-family:system-ui,sans-serif;background:#0d1115;color:var(--color-text)}
*{box-sizing:border-box}html,body{overflow-x:clip}body{margin:0}main{max-width:1060px;margin:auto;padding:32px}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #303b46;padding-bottom:18px}
.brand{letter-spacing:.18em;font-weight:700;font-size:13px}.muted{color:var(--color-text);opacity:.75;font-size:13px}
h1{font-size:32px;letter-spacing:-.035em;margin:28px 0;overflow-wrap:anywhere;min-width:0}.layout{display:grid;grid-template-columns:290px minmax(0,1fr);gap:42px}
.screen{background:#07090b;padding:24px;border-radius:16px;border:1px solid #303b46;width:290px}
.screen img{display:block;width:240px;height:240px;image-rendering:pixelated}
:root{--color-control:#172028;--color-control-hover:#24313d;--color-control-ink:var(--color-text);--color-control-border:#455363;--color-focus:var(--color-text);--color-control-selected:var(--color-text);--color-control-selected-ink:#10151b;--color-control-muted:var(--color-text);--color-control-error:var(--color-text)}
.style-picker{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;width:290px;margin-top:14px}
.style-button{font:inherit;font-size:13px;line-height:1.2;white-space:nowrap;padding:11px 14px;border:1px solid var(--color-control-border);border-radius:5px;background:var(--color-control);color:var(--color-control-ink);cursor:pointer}
.style-button:hover,.style-button.is-hover{background:var(--color-control-hover)}
.style-button:focus-visible,.style-button.is-focus{outline:2px solid var(--color-focus);outline-offset:3px}
.style-button:active,.style-button.is-active{background:var(--color-control-border)}
.style-button[aria-pressed=true]{background:var(--color-control-selected);color:var(--color-control-selected-ink);font-weight:650}
.style-button:disabled{opacity:.5;cursor:default}
.style-button[data-state=loading]{color:var(--color-control-muted)}
.style-button[data-state=error]{border-color:var(--color-control-error);border-style:dashed}
.style-button[data-state=success]{border-color:var(--color-control-selected)}
.more-styles{margin-top:12px}.more-styles summary{font-size:12px;cursor:pointer}.apply-style{grid-column:1/-1}.display-state{min-height:16px;width:290px;font-size:12px;color:var(--color-control-muted)}
.display-state[data-state=error]{color:var(--color-control-error)}
.group{margin-bottom:24px;--provider-ink:var(--color-text)}.group[data-provider=claude]{--provider-ink:var(--color-claude)}.group[data-provider=codex]{--provider-ink:var(--color-codex)}.group[data-provider=grok]{--provider-ink:var(--color-grok)}.group h2{font-size:12px;letter-spacing:.1em;color:var(--color-text);opacity:.75;margin:0 0 6px}
.card{padding:12px 0;border-bottom:1px solid #26313c}.cardhead{display:flex;justify-content:space-between;align-items:center}
.name{font-size:16px;font-weight:600}.status{font-size:12px;color:var(--color-text);opacity:.75}
.window{display:grid;grid-template-columns:58px minmax(0,1fr) 44px 74px;align-items:center;gap:10px;margin-top:9px;font-variant-numeric:tabular-nums;font-size:12px}
.usage-meter{width:100%;height:6px;background:#28313a;--gauge-ink:var(--color-level-low)}.usage-meter[data-level=medium]{--gauge-ink:var(--color-level-medium)}.usage-meter[data-level=high]{--gauge-ink:var(--color-level-high)}.usage-meter[data-level=critical]{--gauge-ink:var(--color-level-critical)}.usage-fill{display:block;height:100%;background:linear-gradient(90deg,rgba(0,0,0,.22),transparent),var(--gauge-ink)}.note{font-size:11px;color:var(--color-text);opacity:.75;margin-top:7px}
.gauge-legend{display:flex;flex-wrap:wrap;gap:8px;font-size:10px;color:var(--color-text);margin-top:12px;max-width:290px}.gauge-legend span{display:flex;align-items:center;gap:4px}.gauge-legend i{width:6px;height:6px;background:var(--color-level-low)}.gauge-legend .medium{background:var(--color-level-medium)}.gauge-legend .high{background:var(--color-level-high)}.gauge-legend .critical{background:var(--color-level-critical)}
footer{margin-top:24px;border-top:1px solid #303b46;padding-top:16px;color:var(--color-text);opacity:.75;font-size:12px;line-height:1.8}
@media(max-width:740px){main{padding:24px 18px}.layout{grid-template-columns:minmax(0,1fr);gap:24px}.screen{width:282px;padding:20px}.style-picker,.display-state{width:282px}.window{grid-template-columns:52px minmax(0,1fr) 42px 65px}}
</style>
<main><header><span class="brand">TOKENTV</span><span class="muted" id="updated">Connecting</span></header>
<h1>Account usage</h1><div class="layout">
<section><div class="screen"><img id="frame" width="240" height="240" alt="Live three-provider clock overview" src="/frame/0.jpg"></div>
<div class="style-picker" role="group" aria-label="Clock style">
<button type="button" class="style-button" id="digital" aria-pressed="false">Digital</button>
<button type="button" class="style-button" id="neon" aria-pressed="false">Neon</button>
<button type="button" class="style-button" id="retro" aria-pressed="false">Pixel Retro</button>
<button type="button" class="style-button" id="modern" aria-pressed="false">Modern</button>
<button type="button" class="style-button" id="sakura" aria-pressed="false">Sakura</button>
</div><details class="more-styles"><summary>More styles</summary>
<div class="style-picker" role="group" aria-label="Earlier clock styles">
<button type="button" class="style-button" id="pixel" aria-pressed="true">Pixel</button>
<button type="button" class="style-button" id="clean" aria-pressed="false">Clean</button>
<button type="button" class="style-button" id="arcade" aria-pressed="false">Arcade</button>
<button type="button" class="style-button" id="columns" aria-pressed="false">Columns</button>
<button type="button" class="style-button" id="orbit" aria-pressed="false">Orbit</button>
</div></details><div class="style-picker">
<button type="button" class="style-button apply-style" id="apply" disabled aria-describedby="display-state">Apply to clock</button></div>
<p class="display-state" id="display-state" role="status" aria-live="polite">Loading clock style</p>
<p class="muted">240 × 240 · Live clock view</p><div class="gauge-legend" aria-label="Used quota levels"><span><i></i>0–49%</span><span><i class="medium"></i>50–79%</span><span><i class="high"></i>80–89%</span><span><i class="critical"></i>90–100%</span></div></section><section id="accounts"></section></div>
<footer>Percentages and bars show <strong>used</strong> quota. Times show when that quota resets.<br>
The clock shows the highest reported usage window for one account per provider. All account windows appear here.<br>
Grok BUDGET measures the CLI billing budget, not web conversation limits.<br>
Laptop-linked accounts update while the laptop is online. Missing quotas are shown as unknown.</footer></main>
<script>
const labels={ok:'Connected',loading:'Loading',auth_required:'Login needed',identity_mismatch:'Check account',quota_unavailable:'Quota unavailable',stale:'Previous value',rate_limited:'Retry later',error:'Fetch failed'};
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function reset(value){if(!value)return '--';let m=Math.max(0,Math.ceil((value-Date.now()/1000)/60));return m>=1440?Math.floor(m/1440)+'d '+Math.floor(m%1440/60)+'h':Math.floor(m/60)+'h '+m%60+'m'}
let selectedStyle=null,displayInfo=null,busy=false,localError=false;
const styles=['pixel','clean','arcade','columns','orbit','digital','neon','retro','modern','sakura'];
const styleName=s=>s==='retro'?'Pixel Retro':s==='retro-dual'?'Pixel Retro Dual':s?s.charAt(0).toUpperCase()+s.slice(1):'Pixel';
function paintStyle(){
const choice=selectedStyle||'pixel';
for(const s of styles){const b=document.querySelector('#'+s);b.setAttribute('aria-pressed',String(s===choice));b.disabled=busy}
const apply=document.querySelector('#apply');apply.disabled=busy||!displayInfo||(choice===displayInfo.style&&displayInfo.status!=='error'&&!localError);
apply.textContent=busy?'Applying...':'Apply to clock';apply.dataset.state=busy?'loading':localError||displayInfo?.status==='error'?'error':displayInfo?.status==='ok'?'success':'default';
const note=document.querySelector('#display-state');note.dataset.state=localError||displayInfo?.status==='error'?'error':'default';
note.textContent=localError?'Could not apply style. Retry.':!displayInfo?'Loading clock style':displayInfo.status==='queued'?'Sending '+styleName(displayInfo.style)+' image...':displayInfo.status==='error'?'Clock upload failed. Retry.':displayInfo.status==='preview_only'?'Preview only': 'Image sent: '+styleName(displayInfo.applied_style);
if(displayInfo&&choice!==displayInfo.style&&!busy&&!localError&&displayInfo.status!=='error')note.textContent='Preview: '+styleName(choice)+' · Apply to use';
document.querySelector('#frame').alt=styleName(choice)+' clock preview';
document.querySelector('#frame').src='/frame/0.jpg?style='+choice+'&t='+Date.now();
}
async function refreshDisplay(){try{const r=await fetch('/display',{cache:'no-store'});if(!r.ok)throw Error();const data=await r.json();const dirty=displayInfo&&selectedStyle!==displayInfo.style;displayInfo=data;if(!selectedStyle||!dirty)selectedStyle=data.style;paintStyle()}catch(e){document.querySelector('#display-state').textContent='Clock status unavailable'}}
for(const s of styles)document.querySelector('#'+s).onclick=()=>{selectedStyle=s;localError=false;paintStyle()};
document.querySelector('#apply').onclick=async()=>{busy=true;localError=false;paintStyle();try{const r=await fetch('/display/style',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({style:selectedStyle})});if(!r.ok)throw Error();displayInfo=await r.json()}catch(e){localError=true}finally{busy=false;paintStyle()}};
async function update(){try{
const response=await fetch('/snapshot',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();
const container=document.querySelector('#accounts');container.replaceChildren();
for(const provider of ['claude','codex','grok']){const group=el('section',undefined,'group');group.dataset.provider=provider;group.append(el('h2',provider.toUpperCase()));
Object.values(data.accounts).filter(a=>a.provider===provider).forEach(a=>{const c=el('article',undefined,'card');const head=el('div',undefined,'cardhead');head.append(el('span',a.alias,'name'),el('span',labels[a.status]||a.status,'status'));c.append(head);
a.windows.forEach(w=>{const row=el('div',undefined,'window');const bar=el('div',undefined,'usage-meter');const used=Math.max(0,Math.min(100,w.used_percent));bar.dataset.level=used<50?'low':used<80?'medium':used<90?'high':'critical';bar.setAttribute('role','meter');bar.setAttribute('aria-label','Used quota');bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');bar.setAttribute('aria-valuenow',String(used));const fill=el('span',undefined,'usage-fill');fill.style.width=used+'%';bar.append(fill);row.append(el('span',w.label),bar,el('span',Math.round(w.used_percent)+'%'),el('span',reset(w.resets_at)));c.append(row)});
if(a.source==='laptop')c.append(el('div','Laptop link · 1 min refresh','note'));
if(a.fetched_at)c.append(el('div','Checked '+new Date(a.fetched_at*1000).toLocaleTimeString('en-GB'),'note'));
if(a.status==='stale'&&a.last_success_at)c.append(el('div','Last success: '+new Date(a.last_success_at*1000).toLocaleString('en-US'),'note'));
group.append(c)});container.append(group)}
document.querySelector('#updated').textContent=data.updated_at?'Updated '+new Date(data.updated_at*1000).toLocaleTimeString('en-GB'):'Loading';
paintStyle();
}catch(e){document.querySelector('#updated').textContent='Server unavailable'}}
update();refreshDisplay();setInterval(update,30000);setInterval(refreshDisplay,2000);
</script></html>
'''
