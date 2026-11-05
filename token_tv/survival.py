"""Survival: a still face in a game HUD's look, as the owner approved it (x7, style A of the drafts w30-w32, 2026-11-05).

One row per account (four at most, the rows overview_rows picks, as on every still face): ten hearts for what is left of
its 5-hour window and ten drumsticks for what is left of its long one (the week; else a month or a budget), a tenth
each, half icons for the last 5% (a little left still shows half an icon); a star and a bar for today's use, full at an
even day's share of the long window (a seventh of a week) and past it a second lap in orange; the pet small beside
them, sweating when nearly out. The numbers are what is LEFT, as the battery's are. An account with one window shows
only its row of that kind. A window with no reading shows a dash, not empty icons; an old reading says OLD; an account
with no reading says why (LOGIN, NO DATA, ...); today's use not known yet is a dash too. Every icon is drawn for
TokenTV (no game's names, pictures or layout). A JPEG like the other still faces: it changes only with the readings.
"""
import functools
import math

from PIL import Image, ImageDraw

from token_tv import arcade
from token_tv import readout
from token_tv.display import MAX_ROWS, STATUS, account_label, fit_pixel, overview_rows, pixel_text, quota_period
from token_tv.pet_moments import sprite
from token_tv.usage import five_hour, long_window, window_minutes

SIZE = 240
PANEL, DIVIDER, TEXT, MUTED = (11, 13, 19), (30, 34, 46), (226, 230, 238), (128, 138, 160)
TRACK = (40, 46, 62)
WARN = arcade.WARN  # OLD, and why an account has no reading

# --- the icons (each drawn for TokenTV, one pixel a cell, doubled on the clock's 2 px grid) ---------------------------

HEART, HEART_SHINE = (255, 92, 136), (255, 200, 214)
MEAT, MEAT_HI, MEAT_LO, BONE = (214, 128, 58), (246, 178, 96), (150, 80, 36), (246, 236, 214)
GOLD, GOLD_HI, OVER = (255, 200, 70), (255, 236, 160), (255, 140, 60)
EMPTY = (44, 50, 66)  # an icon spent: its shape in the track's tone, so the ten places always read

HEART_7 = ('.HH.HH.', 'HSHHHHH', 'HHHHHHH', 'HHHHHHH', '.HHHHH.', '..HHH..', '...H...')
DRUM_7 = ('...MMM.', '..MSMMM', '..MMMMM', '..MMMMm', '..MMmm.', '.BB....', 'B.B....')
STAR_5 = ('..G..', '.GGG.', 'GGGGG', '.GGG.', '.G.G.')
INK_HEART = (('H', HEART), ('S', HEART_SHINE))
INK_DRUM = (('M', MEAT), ('S', MEAT_HI), ('m', MEAT_LO), ('B', BONE))
INK_STAR = (('G', GOLD),)


@functools.lru_cache(maxsize=None)
def icon(rows, ink, part=1.0, scale=2):
    """An icon `part` full (0 to 1), its left part filled and the rest spent, doubled."""
    art = sprite(rows, dict(ink))
    if part < 1:
        px = art.load()
        cut = round(art.width * part) if part > 0 else 0
        for y in range(art.height):
            for x in range(cut, art.width):
                if px[x, y][3]:
                    px[x, y] = EMPTY + (255,)
    return art.resize((art.width * scale, art.height * scale), Image.Resampling.NEAREST)


def put(frame, art, x, y):
    frame.paste(art, (round(x), round(y)), art)


def icon_row(frame, x, y, rows, ink, left, pitch, count=10):
    """`count` icons from x, `left` (0..1) of them full: whole ones, then the one in part (to the nearest half),
    then spent ones."""
    units = math.floor(left * count * 2 + .5) / 2 if left > 0 else 0  # 5% steps; a little left still shows half
    if 0 < left and units == 0:
        units = .5
    for k in range(count):
        put(frame, icon(rows, ink, round(max(0.0, min(1.0, units - k)), 2)), x + k * pitch, y)


# --- the pets, small and still --------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def pet_still(provider, small=False):
    """Each pet's own resting picture at one pixel a cell (Arcade's art): Clawd's Quest's Clawd standing, the cloud, the
    white Grok bot, Copilot's face, Anti; a service with no pet of its own, Arcade's plain one."""
    if provider == 'claude':
        return arcade.clawd('LookingAround', 0, 1)
    if provider == 'codex':
        return arcade.codex_cloud(20, 18) if small else arcade.codex_cloud()
    if provider == 'grok':
        return arcade.grok_pose(14 if small else 16)
    if provider == 'copilot':
        return arcade.copilot_pose(14 if small else 20)
    if provider == 'antigravity':
        return arcade.anti_art()
    return arcade.plain_pet()


def put_pet(frame, draw, provider, cx, bottom, scale, used=None, small=False):
    """The pet standing on `bottom`, centred on cx, `scale` screen pixels a cell; sweating when nearly out (Arcade's
    'worried', 90% used or more)."""
    art = pet_still(provider, small)
    art = art.resize((art.width * scale, art.height * scale), Image.Resampling.NEAREST)
    left, top = round(cx - art.width / 2) // 2 * 2, bottom - art.height
    put(frame, art, left, top)
    if used is not None and used >= 90:
        s = max(1, scale // 2) * 2
        for k, side in enumerate((1, -1)):
            arcade.sweat_drop(draw, round(cx + side * (art.width / 2 + 2 + 2 * k)), top + 2 + 6 * k, s // 2 + 1)


# --- what a row shows -----------------------------------------------------------------------------------------------

def windows_of(row):
    """(the 5-hour window, the long one: the week, else a month or a budget), None where missing; whatever order they
    come in."""
    windows = row.get('windows') or []
    return five_hour(windows), long_window(windows)


def left_of(value):
    """What is left of a window (0..1), None without a reading."""
    if not value or value.get('used_percent') is None:
        return None
    return max(0.0, min(1.0, 1 - value['used_percent'] / 100))


def short_left(value):
    left = left_of(value)
    return '--' if left is None else f'{round(left * 100)}%'


def label_of(value):
    """A window's name as the clock writes it (5H, WK, MO, BUD), three letters at most to keep clear of its icons: a
    longer one by its length when known, else its first three."""
    if not value:
        return ''
    name = quota_period(value)
    if len(name) <= 3:
        return name
    minutes = window_minutes(value)
    return {300: '5H', 1440: 'DAY', 10080: 'WK'}.get(minutes) or ('MO' if minutes and minutes >= 28 * 1440 else name[:3])


def worst_used(row):
    used = [w['used_percent'] for w in row.get('windows', []) if w.get('used_percent') is not None]
    return max(used) if used else None


def old(row):
    """Whether the row's reading is an old one (it is shown as it was, marked OLD)."""
    return bool(row.get('windows')) and row.get('status') != 'ok'


def why(row):
    """Why an account shows no window at all ('LOGIN', 'NO DATA', ...), else ''."""
    return '' if row.get('windows') else STATUS.get(row.get('status'), 'NO DATA')


def icons(frame, draw, x, y, value, rows, ink, pitch):
    """A window's ten icons from (x, y), or a dash in their place when it has no reading (never empty icons, which
    would say it is used up)."""
    left = left_of(value)
    if left is None:
        pixel_text(draw, (x, y + 4), '--', color=MUTED)
    else:
        icon_row(frame, x, y, rows, ink, left, pitch)


def xp_bar(draw, x, y, w, h, today, track=TRACK):
    """Today's use: gold up to an even day's share, and past it a second lap in orange over the gold."""
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=track)
    if today is None:
        return
    first = min(1.0, today)
    if first > 0:
        fx = x + max(2, round(w * first / 2) * 2) - 1
        draw.rectangle((x, y, fx, y + h - 1), fill=GOLD)
        draw.rectangle((x, y, fx, y + (1 if h > 4 else 0)), fill=GOLD_HI)
    second = min(1.0, max(0.0, today - 1))
    if second > 0:
        draw.rectangle((x, y, x + max(2, round(w * second / 2) * 2) - 1, y + h - 1), fill=OVER)
    for k in range(1, 4):  # quarter marks, so a glance reads a quarter of a day from a half
        mx = x + round(w * k / 4)
        draw.line((mx, y, mx, y + h - 1), fill=PANEL)


def today_text(today):
    return '--' if today is None else f'{round(today * 100)}%'


def soonest_reset(five, long, now):
    """The reset a row's top line names: the 5-hour window's (the hearts come back first), else the long one's."""
    value = five or long
    return f'{label_of(value)} {readout.reset_clock(value.get("resets_at"), now)}' if value else ''


def width(text, scale=1):
    return readout.text_width(str(text), scale)


ICONS_END = 30 + 9 * 16 + 14  # where a row of ten icons from x 30 ends


def left_number(draw, y, value, row):
    """What is left of a window, big, at the end of its icons: its right edge at 230, or past it when it would touch
    the icons (100%)."""
    text = short_left(value)
    pixel_text(draw, (max(230, ICONS_END + 2 + width(text, 2)), y), text, scale=2, color=MUTED if old(row) else TEXT,
               align='right')


# --- the face: style A, rows of ten small icons -------------------------------------------------------------------

def hero(frame, draw, row, now):
    """One account: its name and its pet's on top, the pet big, a line of icons for each window with what is left
    and its reset, today's bar at the bottom."""
    five, long = windows_of(row)
    name, ink = readout.PETS.get(row['provider'], (row['provider'].upper()[:8], TEXT))
    right, right_ink = ('OLD', WARN) if old(row) else (name, ink)
    pixel_text(draw, (230, 8), right, scale=2, color=right_ink, align='right')
    pixel_text(draw, (10, 8), fit_pixel(account_label(row), 2, 220 - width(right, 2) - 8), scale=2, color=TEXT)
    draw.line((20, 99, 220, 99), fill=DIVIDER)
    put_pet(frame, draw, row['provider'], 120, 98, 4 if row['provider'] in ('claude', 'antigravity', 'grok') else 2,
            worst_used(row))
    y = 110
    if why(row):
        pixel_text(draw, (30, y + 1), why(row), scale=2, color=WARN)
    for value, art, ink_ in ((five, HEART_7, INK_HEART), (long, DRUM_7, INK_DRUM)):
        if value is None:
            continue
        pixel_text(draw, (10, y + 4), label_of(value), color=MUTED)
        icons(frame, draw, 30, y, value, art, ink_, 16)
        left_number(draw, y + 1, value, row)
        pixel_text(draw, (30, y + 20), 'RESET', color=MUTED)
        pixel_text(draw, (230, y + 20), readout.reset_clock(value.get('resets_at'), now), color=MUTED, align='right')
        y += 38
    put(frame, icon(STAR_5, INK_STAR), 10, 198)
    pixel_text(draw, (26, 200), 'TODAY', color=MUTED)
    xp_bar(draw, 62, 200, 112, 8, row.get('today'))
    pixel_text(draw, (230, 198), today_text(row.get('today')), scale=2, color=TEXT if row.get('today') is not None
               else MUTED, align='right')


def pair(frame, draw, row, y0, now):
    """One of two accounts: the pet and the name on top, the rows of icons the whole width under them with what is
    left at their end, today's bar under those."""
    five, long = windows_of(row)
    put_pet(frame, draw, row['provider'], 34, y0 + 42, 2, worst_used(row), small=True)
    pixel_text(draw, (66, y0 + 10), fit_pixel(account_label(row), 2, 164), scale=2, color=TEXT)
    pixel_text(draw, (66, y0 + 30), soonest_reset(five, long, now), color=MUTED)
    if old(row):
        pixel_text(draw, (230, y0 + 30), 'OLD', color=WARN, align='right')
    y = y0 + 50
    if why(row):
        pixel_text(draw, (30, y + 1), why(row), scale=2, color=WARN)
    for value, art, ink_ in ((five, HEART_7, INK_HEART), (long, DRUM_7, INK_DRUM)):
        if value is not None:
            pixel_text(draw, (10, y + 4), label_of(value), color=MUTED)
            icons(frame, draw, 30, y, value, art, ink_, 16)
            left_number(draw, y + 1, value, row)
        y += 20
    put(frame, icon(STAR_5, INK_STAR, scale=1), 12, y + 2)
    xp_bar(draw, 30, y + 3, 158, 4, row.get('today'))
    pixel_text(draw, (230, y + 1), today_text(row.get('today')), color=GOLD if row.get('today') is not None else MUTED,
               align='right')


def compact(frame, draw, row, y0, h, now):
    """One of three or four accounts: the pet small at the left, the name and the soonest reset on top, icons only."""
    five, long = windows_of(row)
    put_pet(frame, draw, row['provider'], 28, y0 + h // 2 + 16, 2, worst_used(row), small=True)
    x = 60
    note = why(row) or soonest_reset(five, long, now)
    pixel_text(draw, (234, y0 + 5), note, color=WARN if why(row) else MUTED, align='right')
    room = 234 - width(note) - (6 if note else 0)
    if old(row):
        pixel_text(draw, (room, y0 + 5), 'OLD', color=WARN, align='right')
        room -= width('OLD') + 6
    pixel_text(draw, (x, y0 + 5), fit_pixel(account_label(row), 1, room - x), color=TEXT)
    y = y0 + 15
    for value, art, ink_ in ((five, HEART_7, INK_HEART), (long, DRUM_7, INK_DRUM)):
        if value is not None:
            icons(frame, draw, x, y, value, art, ink_, 16)
            if value is long and five is not None and window_minutes(long) != 10080:  # not a week: say which it is
                pixel_text(draw, (236, y + 4), label_of(long), color=MUTED, align='right')
        y += 16
    put(frame, icon(STAR_5, INK_STAR, scale=1), x, y + 1)
    if row.get('today') is None:  # not known yet: a dash, not an empty bar
        pixel_text(draw, (x + 10, y), '--', color=MUTED)
    else:
        xp_bar(draw, x + 10, y + 2, 228 - x - 10, 4, row.get('today'))


def render_survival(snapshot, now=None):
    """The Survival face for `snapshot` as the clock shows it (240 x 240, RGB)."""
    frame = Image.new('RGB', (SIZE, SIZE), PANEL)
    draw = ImageDraw.Draw(frame)
    rows = overview_rows(snapshot)[:MAX_ROWS]
    if len(rows) == 1:
        hero(frame, draw, rows[0], now)
        return frame
    h = SIZE // len(rows)
    for i, row in enumerate(rows):
        y0 = i * h
        if i:
            for x in range(8, 233, 4):
                draw.point((x, y0), fill=DIVIDER)
        if len(rows) == 2:
            pair(frame, draw, row, y0, now)
        else:
            compact(frame, draw, row, y0, h, now)
    return frame
