"""Arcade: the mascots act out whether their account is in use right now, and each picture is a gauge.

An account counts as working while its used % rose within the last ten minutes (`active` in
state.py). Working, Clawd jogs to and fro, the Codex cloud rains digits and code symbols on its garden,
Grok fuels its rocket or works the console, Copilot flies across under its clouds and Anti patrols its
maze; at rest they breathe, look round now and then and stretch, a minute at a time. Each picture also
reads one limit: Claude's moon, the garden, the fuel tank, the clouds, the power pellets.

Clawd's poses are the sprites of Clawd's Quest (claude.dev/game), kept in assets/clawd.json in
the game's own encoding; the others are the bundled pixel mascots. Arcade shows one account at
a time: one character on the screen reads best on the clock. It is a GIF loop of 120 even frames that
depends only on the readings, the working flags, a coarse reset time and the minute of rest,
so equal inputs give identical bytes and the clock is not rewritten.
"""
import base64
import functools
import hashlib
import io
import json
import math
import random
import time

from PIL import Image, ImageDraw, ImageEnhance

from token_tv import gif
from token_tv.readout import draw_readout
from token_tv.display import (ASSETS, MAX_ROWS, PROVIDERS, SHORT_NAME, account_label, fit_pixel, overview_rows, pixel_text, quota_period,
                              reading, shown_windows)
from token_tv.space import sprite as mascot_sprite
from token_tv.themes import bot_sprite

SIZE = 240
FPS = 12  # Clawd's own frame rate
PACE = 1.5  # Clawd's idle moves play half again as fast as in the game
SPEED = 2  # every scene runs at twice its drawn pace; a loop plays twice in the 10 s, a one-off in 5 s
FRAMES = 10 * FPS
FRAME_MS = 70  # each frame on the clock: 120 of them make an 8.4 s loop, a fifth brisker than the drawn 10 s
LOOP_SECONDS = FRAMES * FRAME_MS / 1000
TEXT = (226, 230, 238)
MUTED = (128, 138, 160)
WARN = (255, 96, 110)
TRACK = (40, 46, 62)
PANEL, DIVIDER = (11, 13, 19), (30, 34, 46)
BUDGET = 380_000  # bytes; the clock takes GIFs up to 400 kB
BANDS = ((76, 201, 140), (140, 214, 92), (255, 160, 64), (255, 84, 96))  # below 50, 50–79, 80–89, 90+
# Clawd's Quest night palette: near-black ground with grey dots.
LAND, DOT, DOT_DIM, DOT_BRIGHT = (23, 23, 23), (122, 122, 122), (66, 66, 66), (170, 170, 170)
SKY = {'grok': (6, 9, 22), 'codex': (18, 20, 52)}
STARS = ((52, 60, 92), (112, 122, 166), (228, 234, 255))
DECK, DECK_EDGE, LEG = (54, 58, 70), (112, 118, 134), (150, 158, 176)

# The game's idle flourishes and emotes: (sprite, first frame, last frame), all played at 12 fps.
IDLE_MOVES = {'look': ('LookingAround', 4, 30), 'sway': ('Swaying', 4, 48), 'turn': ('Turning', 2, 26),
              'dance': ('DancingHappy', 4, 38), 'meditate': ('Meditating', 2, 59), 'break': ('BreakDancing', 2, 27),
              'wave': ('Waving', 3, 16), 'think': ('Thinking', 2, 36)}
RUN = ('Running', 5, 16)  # the game's run loop
JUMP_RISE, JUMP_TOP, JUMP_FALL, JUMP_LAND = (5, 6), 7, (10, 11), (13, 14)  # Jumping frames by vertical speed

# Rain glyphs, 3×5: zeros and ones with a few code symbols, in one blue at falling brightness.
RAIN_GLYPHS = {
    '0': '111/101/101/101/111', '1': '010/110/010/010/111', '{': '011/010/110/010/011', '}': '110/010/011/010/110',
    '<': '001/010/100/010/001', '>': '100/010/001/010/100', ';': '000/010/000/010/100', '/': '001/001/010/100/100',
    '=': '000/111/000/111/000', '+': '000/010/111/010/000', '*': '101/010/111/010/101', '#': '101/111/101/111/101',
    '(': '010/100/100/100/010', ')': '010/001/001/001/010', '[': '110/100/100/100/110', ']': '011/001/001/001/011',
}
RAIN_CHARS = '01' * 7 + '{}<>;/=+*#()[]'
# Small capitals for the limit a gauge picture follows (5H, WK, MO, BUD, DAY), in the same 3 x 5 cells.
LABEL_GLYPHS = {'5': '111/100/111/001/110', 'H': '101/101/111/101/101', 'W': '101/101/101/111/101',
                'K': '101/101/110/101/101', 'M': '101/111/101/101/101', 'O': '111/101/101/101/111',
                'B': '110/101/110/101/110', 'U': '101/101/101/101/111', 'D': '110/101/101/101/110',
                'A': '010/101/111/101/101', 'Y': '101/101/010/010/010', 'C': '111/100/100/100/111',
                'T': '111/010/010/010/010', 'I': '111/010/010/010/111', 'N': '101/111/111/111/101',
                'R': '110/101/110/101/101', 'E': '111/100/110/100/111', 'S': '111/100/111/001/111',
                'L': '100/100/100/100/111', 'G': '111/100/101/101/111', 'P': '110/101/110/100/100',
                'X': '101/101/010/101/101', '0': '111/101/101/101/111', '1': '010/110/010/010/111',
                '2': '111/001/111/100/111', '3': '111/001/111/001/111', '4': '101/101/111/001/001',
                '6': '111/100/111/101/111', '7': '111/001/001/001/001', '8': '111/101/111/101/111',
                '9': '111/101/111/001/111'}
LABEL_INK = (104, 112, 140)


def gauge_label(draw, x, y, text, align='left'):
    """The limit a gauge picture follows, small and dim, at (x, y) on the stage."""
    text = ''.join(c for c in text if c in LABEL_GLYPHS)
    x -= {'left': 0, 'centre': (4 * len(text) - 1) // 2, 'right': 4 * len(text) - 1}[align]
    for n, char in enumerate(text):
        for yy, line in enumerate(LABEL_GLYPHS[char].split('/')):
            for xx, bit in enumerate(line):
                if bit == '1':
                    draw.point((x + 4 * n + xx, y + yy), fill=LABEL_INK)
RAIN_BLUE = (150, 166, 255)
RAIN_SHADES = tuple(tuple(min(255, round(c * k)) for c in RAIN_BLUE) for k in (1.45, 1.15, .9, .65))


def coarse_left(reset, now=None):
    """Time to reset in its largest unit (3D, 5H, 38M); the minute only shows in the last hour."""
    if not reset:
        return '--'
    minutes = max(0, int((reset - (time.time() if now is None else now) + 59) // 60))
    return f'{minutes // 1440}D' if minutes >= 1440 else f'{minutes // 60}H' if minutes >= 60 else f'{minutes}M'


def loop_offset(f, length, cycles):
    """Position along a strip of `length` that wraps `cycles` times per loop, so frame 100 meets frame 0."""
    return (f * length * cycles / FRAMES) % length


def paste(frame, art, x, y):
    frame.paste(art, (round(x), round(y)), art)


def band_color(used):
    return BANDS[0 if used < 50 else 1 if used < 80 else 2 if used < 90 else 3]


def gauge(draw, x, y, width, height, used, old=False):
    """Ten cells across `width`; an old reading keeps its level in a muted colour."""
    step = width / 10
    for cell in range(10):
        left, right = round(x + cell * step), round(x + (cell + 1) * step) - 2
        draw.rectangle((left, y, right, y + height - 1), fill=TRACK)
        if used is not None and used > cell * 10:
            fill = min(1, used / 10 - cell)
            draw.rectangle((left, y, left + max(1, round((right - left + 1) * fill)) - 1, y + height - 1),
                           fill=MUTED if old else band_color(used))


# --- Clawd -----------------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def clawd_data():
    """Clawd's animations; the hidden scenes' own few, where this copy has them, from clawd-eggs.json."""
    data = json.loads((ASSETS / 'clawd.json').read_text())
    extra = ASSETS / 'clawd-eggs.json'
    if extra.exists():
        data.update(json.loads(extra.read_text()))
    return data


@functools.lru_cache(maxsize=None)
def clawd_frames(name):
    """All frames of one animation, decoded as the game does: a base grid plus per-frame changes."""
    sheet = clawd_data()[name]
    current = [255 if c == '.' else int(c, 36) for c in sheet['base']]
    frames = [current[:]]
    for delta in sheet['deltas']:
        for change in filter(None, delta.split(',')):
            current[int(change[:-1], 36)] = 255 if change[-1] == '.' else int(change[-1], 36)
        frames.append(current[:])
    return frames


@functools.lru_cache(maxsize=None)
def clawd(name, index, scale):
    sheet = clawd_data()[name]
    palette = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (255,) for c in sheet['palette']]
    art = Image.new('RGBA', (sheet['w'], sheet['h']))
    art.putdata([(0, 0, 0, 0) if v == 255 else palette[v] for v in clawd_frames(name)[index]])
    return art.resize((art.width * scale, art.height * scale), Image.Resampling.NEAREST)


def place_clawd(frame, name, index, scale, foot_x, foot_y, flip=False):
    """Stand the frame on (foot_x, foot_y): the game anchors every pose at the bottom centre of its body box.
    `flip` faces it left."""
    x, y, w, h = clawd_data()[name]['a0']
    art = clawd(name, index, scale)
    if flip:
        art = art.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        x = art.width / scale - x - w
    paste(frame, art, foot_x - (x + w / 2) * scale, foot_y - (y + h) * scale)


@functools.lru_cache(maxsize=None)
def clawd_spun(name, index, scale, degrees):
    return rotsprite(clawd(name, index, scale), degrees)


def place_clawd_spun(frame, name, index, scale, foot_x, foot_y, degrees):
    """Clawd turned by `degrees` round the middle of its body box, which stays where it would stand."""
    x, y, w, h = clawd_data()[name]['a0']
    art = clawd(name, index, scale)
    spun = clawd_spun(name, index, scale, degrees)
    cx = foot_x - (x + w / 2) * scale + art.width / 2  # where the unturned art's centre would be
    cy = foot_y - (y + h) * scale + art.height / 2
    paste(frame, spun, cx - spun.width / 2, cy - spun.height / 2)


# Rest is one flow, a minute at a time: look round, keep still a while, stretch, keep still, and now and then a
# rarer move in place of a still minute. Between, the pets only breathe.
REST_FLOW = ('look', None, None, 'stretch', None, None)
REST_MOVES = {'look': ('look',), 'stretch': ('sway', 'turn'), 'rare': ('dance', 'break', 'meditate', 'wave', 'think')}
FLOW_MOVES = {'codex': {'look': 'drift', 'stretch': 'yawn', 'rare': 'drift'},
              'grok': {'look': 'gaze', 'stretch': 'wander', 'rare': 'wander'},
              'copilot': {'look': 'look', 'stretch': 'hop', 'rare': 'hop'},
              'antigravity': {'look': 'look', 'stretch': 'bob', 'rare': 'look'}}


def rest_step(provider, now):
    """What a resting pet does this minute ('look', 'stretch', 'rare' or None to keep still), and a random source
    fixed for the minute."""
    minute = int((time.time() if now is None else now) // 60)
    step = REST_FLOW[minute % len(REST_FLOW)]
    rnd = random.Random(f'{provider}|{minute // len(REST_FLOW)}')
    if minute % len(REST_FLOW) == 4 and rnd.random() < .2:
        step = 'rare'
    return step, random.Random(f'{provider}|{minute}')


def idle_plan(row, now, span=FRAMES / FPS):
    """Clawd's move for this minute of rest, if any (REST_FLOW), early in the turn."""
    step, rnd = rest_step(row['provider'], now)
    if not step:
        return []
    name, first, last = IDLE_MOVES[rnd.choice(REST_MOVES[step])]
    t = .4
    return [(t, min(span - .2, t + (last - first + 1) / (12 * PACE)), name, first, last)]


@functools.lru_cache(maxsize=None)
def land_layers(depth, period, pits, pit_w, ridge_h):
    """Dotted ground (with pits) and far hills, each drawn twice over one period so any crop wraps."""
    rnd = random.Random(period * 31 + depth)
    ground = Image.new('RGBA', (period * 2, depth))
    gd = ImageDraw.Draw(ground)
    for u in range(0, period, 2):
        if any(abs(u - p) < pit_w / 2 for p in pits):
            continue
        for v in range(0, depth, 2):
            k = rnd.random()
            color = DOT_BRIGHT if k < .05 else DOT if v == 0 or k < .7 else DOT_DIM
            for dx in (0, period):
                gd.point((u + dx, v), fill=color)
    hills = Image.new('RGBA', (480, ridge_h))
    hd = ImageDraw.Draw(hills)
    for u in range(0, 240, 2):
        ridge = ridge_h * (.55 + .3 * math.sin(2 * math.pi * u / 240 * 2 + 1) + .15 * math.sin(2 * math.pi * u / 240 * 5))
        top = ridge_h - round(ridge)
        for v in range(top - top % 2, ridge_h, 2):
            inside = (v - top) / max(1, ridge_h - top)
            if rnd.random() < (.85 if v - top < 3 else .35 * (1 - inside) + .05):
                for dx in (0, 240):
                    hd.point((u + dx, v), fill=DOT if v - top < 3 else DOT_DIM)
    return ground, hills


def claude_backdrop(frame, draw, box, f, s, active, pit=True):
    """Clawd's Quest at night: stars, the dotted moon and hills, and dotted ground scrolling while Clawd runs."""
    x, y, w, h = box
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=LAND)
    ground_y = y + h - max(10, h // 6)
    rnd = random.Random(w * 7 + h)
    for _ in range(w * h // 900):  # a few stars
        draw.point((x + rnd.randrange(w), y + rnd.randrange(max(1, ground_y - y - 30))), fill=DOT_DIM)
    if w >= 200:  # the game's dotted crescent moon, where there is room for it
        cx, cy, r = x + w - 34, y + 22, 11
        for yy in range(cy - r, cy + r + 1, 2):
            for xx in range(cx - r, cx + r + 1, 2):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r and (xx - cx - 5) ** 2 + (yy - cy + 3) ** 2 > (r - 2) ** 2:
                    draw.point((xx, yy), fill=DOT)
    period = 80 * max(3, round(w * 1.3 / 80))  # one pit per strip, two strips a loop
    pits, pit_w = (period * .6,) if pit else (), 9 * s
    ground, hills = land_layers(y + h - ground_y, period, pits, pit_w, max(12, h // 4))
    shift = loop_offset(f, period, 3) if active else 0
    far = loop_offset(f, 240, 2) if active else 0
    crop = hills.crop((round(far), 0, round(far) + w, hills.height))
    frame.paste(crop, (x, ground_y - hills.height), crop)
    crop = ground.crop((round(shift), 0, round(shift) + w, ground.height))
    frame.paste(crop, (x, ground_y), crop)
    return ground_y, period, pits, pit_w, shift


MOON_LIT, MOON_DARK = (238, 228, 190), (58, 58, 68)


def moon_gauge(draw, cx, cy, r, left):
    """Claude's moon is its 5-hour window: full while there is plenty left, waning through half to a thin
    crescent as it is used, and only a dark ring once it is gone; a reset brings the full moon back."""
    for yy in range(-r, r + 1):
        half = math.sqrt(max(0, r * r - yy * yy))
        terminator = (2 * left - 1) * half  # lit to the left of it
        for xx in range(-r, r + 1):
            if xx * xx + yy * yy <= r * r:
                lit = left > 0 and xx <= terminator  # nothing left: only the dark ring
                edge = xx * xx + yy * yy > (r - 1) * (r - 1)
                if lit or edge:
                    draw.point((cx + xx, cy + yy), fill=MOON_LIT if lit else MOON_DARK)


def claude_scene(frame, draw, box, f, span, active, s, plan):
    x, y, w, h = box
    ground_y, period, pits, pit_w, shift = claude_backdrop(frame, draw, box, f, s, False)  # the world stands still
    if isinstance(plan, dict) and plan.get('moon') is not None:
        moon_gauge(draw, x + w - 12 * s, y + 11 * s, 8 * s, plan['moon'])
        if s == 1:
            gauge_label(draw, x + w - 12, y + 21, '5H', 'centre')
    foot_x, foot_y = x + round(w * .3), ground_y
    if not active and isinstance(plan, dict) and plan.get('mood') == 'worried':
        t = f % 40  # nearly out: pacing to and fro, looking round at each end
        back = t >= 20
        at = foot_x + min(14, t if not back else max(0, 34 - t)) * 2 * s
        if t < 14 or 20 <= t < 34:
            name, first, last = RUN
            place_clawd(frame, name, first + t % (last - first + 1), s, at, foot_y, flip=back)
        else:
            name, first, _ = IDLE_MOVES['look']
            place_clawd(frame, name, first + (t % 20 - 14) * 3, s, at, foot_y, flip=back)
        mood_marks(draw, at + 10 * s, foot_y - 22 * s, s, f, 'worried')
        return
    if not active:
        t = f / FPS
        moves = plan.get('moves', []) if isinstance(plan, dict) else plan
        for start, end, name, first, last in moves:
            if start <= t < end:
                index = min(last, first + int((t - start) * 12 * PACE))
                if name == 'BreakDancing':  # a full spin through the move, so it reads as breaking at a glance
                    turn = round((index - first) / (last - first + 1) * 8) % 8 * 45
                    place_clawd_spun(frame, name, index, s, foot_x, foot_y - 3 * s, turn)
                else:
                    place_clawd(frame, name, index, s, foot_x, foot_y)
                break
        else:  # keeping still: a slow breath, one every two and a half seconds
            breath = s if (f / (FPS * SPEED)) % 2.5 < 1 else 0
            place_clawd(frame, 'LookingAround', 0, s, foot_x, foot_y - breath)
        if isinstance(plan, dict):
            mood_marks(draw, foot_x + 10 * s, foot_y - 22 * s, s, f, plan.get('mood'))
        return
    # At work Clawd jogs to and fro along the ground, a stride a second; nearly out, twice as fast and sweating.
    worried = isinstance(plan, dict) and plan.get('mood') == 'worried'
    pace = 2 if worried else 1
    t = (f / span * pace) % 1  # a lap a loop of the scene, so it meets its start however short the turn
    back = t >= .5
    reach = .54 * min(1, span / FRAMES)  # a shorter turn, a shorter lap: the same easy pace
    at = x + round(w * (.18 + reach * (2 * t if not back else 2 - 2 * t)))
    name, first, last = RUN
    cycle = last - first + 1
    strides = max(1, round(span / (FPS * SPEED))) * pace  # about a stride a second
    place_clawd(frame, name, first + int(f / span * strides * cycle) % cycle, s, at, foot_y, flip=back)
    if worried:
        mood_marks(draw, at + 10 * s, foot_y - 22 * s, s, f, 'worried')


# --- Codex -----------------------------------------------------------------------------------
# The bundled cloud keeps its '>_' face; each frame sets the eye, the mouth and a squash by hand.

CODEX_INK = (34, 40, 120, 255)  # the cloud's '>_', deep indigo on its light body


def is_light(p):
    """A pixel of the '>_' strokes, as opposed to the cloud around them."""
    return p[3] and max(p[:3]) < 140


@functools.lru_cache(maxsize=None)
@functools.lru_cache(maxsize=None)
def codex_cloud(width=28, height=26):
    """The Codex mascot a little smaller than the shared one (it looked big next to the others), same shape:
    the outline resampled to the new size, each pixel the cloud tone of its row, the '>_' moved over stroke
    for stroke."""
    art = mascot_sprite('codex')
    w, h = art.size
    mask = art.getchannel('A').resize((w * 8, h * 8), Image.Resampling.NEAREST).resize((width, height),
                                                                                       Image.Resampling.BOX)
    out = Image.new('RGBA', (width, height))
    for y in range(height):
        sy = min(h - 1, int((y + .5) * h / height))
        tones = [(x, art.getpixel((x, sy))) for x in range(w)]
        tones = [(x, p) for x, p in tones if p[3] and not is_light(p)]
        for x in range(width):
            if mask.getpixel((x, y)) >= 128 and tones:
                sx = (x + .5) * w / width
                out.putpixel((x, y), min(tones, key=lambda t: abs(t[0] - sx))[1])
    face = [(x, y) for y in range(h) for x in range(w) if is_light(art.getpixel((x, y)))]
    fx, fy = sum(x for x, _ in face) / len(face), sum(y for _, y in face) / len(face)
    for x, y in face:
        out.putpixel((round(fx * width / w + x - fx), round(fy * height / h + y - fy)), art.getpixel((x, y)))
    return out


def codex_pose(eye='open', mouth='long', squash=0):
    """The Codex cloud at one pixel per pixel. `squash` > 0 is wider and shorter, < 0 narrower and taller."""
    art = codex_cloud().copy()
    px = art.load()
    w, h = art.size
    light = [(x, y) for y in range(h) for x in range(w) if is_light(px[x, y])]
    eye_px = [(x, y) for x, y in light if x < w // 2 - 1]
    mouth_px = [(x, y) for x, y in light if x >= w // 2 - 1]
    erase = (eye_px if eye != 'open' else []) + (mouth_px if mouth != 'long' else [])
    for x, y in erase:  # paint over with the nearest cloud colour on the row
        for dx in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5):
            if 0 <= x + dx < w and px[x + dx, y][3] and not is_light(px[x + dx, y]):
                px[x, y] = px[x + dx, y]
                break
    white = CODEX_INK  # the face's own ink
    if eye == 'closed' and eye_px:  # a sleepy dash where the '>' was
        ey = round(sum(y for _, y in eye_px) / len(eye_px))
        left = min(x for x, _ in eye_px)
        for x in range(left, left + 5):
            px[x, ey] = white
    if mouth == 'short' and mouth_px:  # the '_' hums: shorter by a pixel at each end
        xs = sorted(x for x, _ in mouth_px)
        for x, y in mouth_px:
            if xs[0] < x < xs[-1]:
                px[x, y] = white
    if eye == 'happy' and eye_px:  # '^', the eye of a grin
        ex = round(sum(x for x, _ in eye_px) / len(eye_px))
        ey = round(sum(y for _, y in eye_px) / len(eye_px)) - 2
        for i in range(4):
            for x in (ex - i, ex - i + 1, ex + i, ex + i + 1):
                px[x, ey + i] = white
    if mouth == 'smile' and mouth_px:  # the '_' bends into a wide open grin
        left, right = min(x for x, _ in mouth_px), max(x for x, _ in mouth_px)
        top = min(y for _, y in mouth_px) - 1
        for i, inset in enumerate((0, 0, 1, 2)):
            for x in range(left + inset, right - inset + 1):
                px[x, top + i] = white
    if mouth == 'open' and mouth_px:  # a little 'o', gasping
        mx = round(sum(x for x, _ in mouth_px) / len(mouth_px))
        my = round(sum(y for _, y in mouth_px) / len(mouth_px))
        for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
            px[mx + dx, my + dy] = white
    if squash:
        art = art.resize((w + 2 * squash, h - 2 * squash), Image.Resampling.NEAREST)
    return art


@functools.lru_cache(maxsize=None)
def codex_art(scale, eye='open', mouth='long', squash=0):
    art = codex_pose(eye, mouth, squash)
    return art.resize((art.width * scale, art.height * scale), Image.Resampling.NEAREST)


def rain_glyph(draw, char, x, y, scale, color):
    x, y = round(x), round(y)
    for yy, line in enumerate(RAIN_GLYPHS[char].split('/')):
        for xx, bit in enumerate(line):
            if bit == '1':
                draw.rectangle((x + xx * scale, y + yy * scale, x + xx * scale + scale - 1, y + yy * scale + scale - 1),
                               fill=color)


def shade(k):
    return tuple(min(255, round(c * k)) for c in RAIN_BLUE)


# One wring every 40 frames: press (wider), release (taller), wobble back; the rain bursts on release.
WRING = (0, 1, 1, 2, 2, 2, -1, -2, -1, 0, 1, 0)


def splash(draw, x, ground, age, s, color):
    """Two droplets hop off and a ripple widens on the puddle, for four frames after a hit."""
    if not 0 <= age < 4:
        return
    rise = (0, 2, 2, 1)[age] * s
    spread = (1, 2, 3, 4)[age] * s
    for side in (-1, 1):
        draw.rectangle((x + side * spread, ground - rise - s, x + side * spread + s - 1, ground - rise - 1), fill=color)
    draw.line((x - spread - s, ground + s, x + spread + s, ground + s), fill=shade(.5))


# Code rain grows bracket flowers: a '|' stem, '<' '>' leaves, a '( )' bud that opens to '{*}'.
# The garden keeps one flower per 20% used; while Codex works, the cloud waters the next one.
SOIL, SOIL_TOP, SOIL_DOT = (31, 27, 58), (58, 52, 96), (44, 40, 78)
PLOT = (86, 78, 138)  # a dug spot waiting for its flower
STEM, LEAF, BUD, PETAL, HEART = (96, 214, 168), (70, 176, 140), (150, 142, 240), (204, 198, 255), (255, 226, 140)
SWEAT_INK = (140, 200, 255)


def sweat_drop(draw, x, y, s):
    """A small cartoon sweat drop, pointed at the top."""
    d = max(1, s)
    draw.rectangle((x, y + d, x + 2 * d - 1, y + 3 * d - 1), fill=SWEAT_INK)
    draw.rectangle((x + d // 2, y, x + d // 2 + max(1, d // 2 + (d > 1)) - 1, y + d - 1), fill=SWEAT_INK)
    draw.point((x, y + d), fill=(220, 240, 255))


def garden_backdrop(draw, box, f, s):
    """Banded dusk over a strip of garden soil; returns the soil's top."""
    x, y, w, h = box
    for k in range(4):
        tone = tuple(min(255, c + k * 5) for c in SKY['codex'])
        draw.rectangle((x, y + k * h // 4, x + w - 1, y + (k + 1) * h // 4 - 1), fill=tone)
    ground = y + h - 4 * s
    draw.rectangle((x, ground, x + w - 1, y + h - 1), fill=SOIL)
    draw.line((x, ground, x + w - 1, ground), fill=SOIL_TOP)
    for i in range(3, w, 7 * s):
        draw.point((x + i, ground + 2 * s + (i // 7) % 2 * s), fill=SOIL_DOT)
    return ground


def flower(draw, cx, ground, g, stage, lean=0):
    """One bracket flower at `stage` 0..1: seed, stem, leaves, bud, bloom. `g` is the glyph pixel size."""
    if stage <= 0:
        return
    if stage < .15:  # a seed in the soil
        draw.rectangle((cx - g, ground - g, cx, ground - 1), fill=BUD)
        return
    stem_h = 9 * g
    grown = round(stem_h * min(1, (stage - .15) / .35))
    top = ground - grown
    if grown > 0:
        draw.rectangle((cx - g // 2, top, cx - g // 2 + g - 1, ground - 1), fill=STEM)
    if stage >= .5:
        rain_glyph(draw, '<', cx - 4 * g, ground - 6 * g, g, LEAF)
    if stage >= .58:
        rain_glyph(draw, '>', cx + g, ground - 7 * g, g, LEAF)
    head = top - 5 * g
    if .65 <= stage < .82:
        rain_glyph(draw, '(', cx - 3 * g + lean, head, g, BUD)
        rain_glyph(draw, ')', cx + lean, head, g, BUD)
    elif stage >= .82:
        rain_glyph(draw, '{', cx - 5 * g + lean, head, g, PETAL)
        rain_glyph(draw, '*', cx - g - g // 2 + lean, head, g, HEART)
        rain_glyph(draw, '}', cx + 2 * g + lean, head, g, PETAL)


def codex_scene(frame, draw, box, f, span, active, s, plan, centre=.5):
    x, y, w, h = box
    ground = garden_backdrop(draw, box, f, s)
    used = plan.get('used') if isinstance(plan, dict) else None
    spots = 5  # one flower per 20%, on every stage size
    xs = [x + round(w * (i + .5) / spots) for i in range(spots)]
    bloomed = 0 if used is None else min(spots, int(used * spots // 100))  # one flower per 20% (25% on 4 spots)
    fg = s + 1 if s >= 2 else s  # flowers a size up on the big stage
    growing = bloomed if used is not None and bloomed < spots else None
    if s == 1 and isinstance(plan, dict) and plan.get('label'):
        gauge_label(draw, x + 1, y + 1, plan['label'])
    for i, fx in enumerate(xs):
        if used is None:
            break  # no reading: no garden to read
        if i < bloomed:
            lean = s * (1 if (f // 30 + i) % 2 else 0)
            flower(draw, fx, ground, fg, 1, lean)
        else:  # an empty spot, still to come (the growing one's sprout stands in it)
            draw.rectangle((fx - 2 * s, ground - s, fx + s - 1, ground - 1), fill=PLOT)
    base = codex_art(s)
    cw, ch = base.size
    cx = xs[growing] if active and growing is not None else x + round(w * centre)
    cx = min(max(cx, x + cw // 2 + 2), x + w - cw // 2 - 2)
    mid = y + max(2, round(h * .05)) + ch // 2
    hurry = isinstance(plan, dict) and plan.get('mood') == 'worried'  # nearly out: rains harder, sweats more
    if active:
        phase = f % (12 if hurry else 24)
        squash = WRING[phase] if phase < len(WRING) else 0
        eye = 'closed' if f % 60 in (30, 31) else 'open'
        mouth = 'short' if f // 4 % 2 else 'long'
        mid += round(math.sin(2 * math.pi * f * 3 / FRAMES) * s)
        shiver = s * (1 if f % 2 else -1) if 1 <= phase <= 5 else 0
    else:
        idle = idle_now(plan, f, span)
        squash = 1 if 26 <= f % 60 <= 33 else 0  # breathing
        eye, mouth, shiver = 'closed', 'long', 0
        mid += round(math.sin(2 * math.pi * f / FRAMES) * 2 * s)
        if idle == 'drift':  # awake, floating two steps one way, two the other, blinking now and then
            eye = 'closed' if f % 30 in (12, 13) else 'open'
            cx += round(math.sin(2 * math.pi * f / 60) * 8 * s)
        elif idle == 'yawn':  # a slow stretch and a big yawn
            t = f % 60
            eye = 'closed' if 20 <= t < 36 else 'open'
            mouth = 'open' if 22 <= t < 34 else 'long'
            squash = -1 if 22 <= t < 34 else squash
        elif idle == 'fret':  # worn out: sunk low, heaving, gasping through an 'o' and puffing
            beat = f % 16
            mouth = 'open' if beat < 6 else 'long'
            squash = (1, 2, 2, 1, 0, -1)[beat] if beat < 6 else 0
            mid += 5 * s
        cx = min(max(cx, x + cw // 2 + 2), x + w - cw // 2 - 2)
    cloud = codex_art(s, eye, mouth, squash)
    if growing is not None:
        # only as far as the reading has come through this fifth (a sprout at 41%, a bud at 58%); it blooms on
        # the next fifth, so a bloom always means a full 20%
        done = (used % 20) / 20 if used is not None else 0
        stage = .15 + .66 * done
        flower(draw, xs[growing], ground, fg, stage)
        if active and done >= .8 and f % 24 < 8:  # nearly there: the bud glints
            for k in range(4):
                a = math.radians(45 + k * 90 + f * 12)
                draw.point((xs[growing] + round(math.cos(a) * 7 * fg), ground - 12 * fg + round(math.sin(a) * 4 * fg)),
                           fill=(255, 255, 255))
    top_rain = mid + ch // 2 - 4 * s
    fall = ground - top_rain
    if active:  # code rain from the cloud onto the garden
        g = s
        for col, gx in enumerate(range(cx - cw // 2 + 2 * s, cx + cw // 2 - 3 * g, 8 * s)):
            c = (9, 10, 12)[col % 3] + (5 if hurry else 0)
            travel = f * c / FRAMES + (col * .61) % 1
            depth = (travel % 1) * (fall + 12 * g)
            pick = (col * 5 + int(travel) % c * 7) % len(RAIN_CHARS)
            for t, tone in enumerate((1.55, 1.05, .6)):
                gy = top_rain + depth - t * 6 * g
                if top_rain - 2 * g <= gy < ground - 5 * g:
                    rain_glyph(draw, RAIN_CHARS[(pick + t * 5) % len(RAIN_CHARS)], gx, gy, g, shade(tone))
            hit = (fall + 7 * g) / (fall + 12 * g)
            if travel % 1 >= hit:
                age = int(((travel % 1) - hit) * FRAMES / c)
                splash(draw, gx + g, ground, age, s, shade(1.2))
    elif idle == 'nap':
        t = f % 40  # sleepy z's drift up from the cloud's shoulder
        if t < 30:
            pixel_text(draw, (round(cx + cw // 2 - 2 * s + t * s / 4), round(max(y + 2, mid - ch // 4 - t * s / 2))), 'z',
                       scale=2 if s > 1 and t >= 12 else 1, color=shade(1.3 if t < 22 else .8))
    if not active and idle == 'fret' and f % 16 < 5:  # each gasp puffs out a little breath
        t = f % 16
        puff(draw, round(cx + cw * .5 + t * 3 * s), round(mid + ch * .1 - t * s), max(1, round((5 - t) * s * .7)))
    paste(frame, cloud, cx - cloud.width / 2 + shiver, mid - cloud.height / 2)
    if not active and isinstance(plan, dict):
        mood_marks(draw, round(cx + cw * .3), round(mid - ch * .55), s, f, plan.get('mood'), idle == 'nap')
    if active:  # straining to rain: sweat drops pop off the top of its head
        drops = 10 if hurry else 20
        for k, side in enumerate((-1, 1, -1)):
            t = (f + k * 7) % drops
            if t < min(11, drops - 1):
                p = t / min(10, drops - 2)
                dx = side * (cw * .25 + p * 7 * s)
                dy = -ch * .45 - 4 * p * (1 - p) * 8 * s + p * p * 4 * s
                sweat_drop(draw, round(cx + dx), round(mid + dy), s)


# --- Grok ------------------------------------------------------------------------------------
# Grok's world is a Falcon Heavy on its pad on the Moon, with the Earth in the sky. The rocket keeps the real
# one's slim proportions, drawn as simply as a pictogram: white cores, a pointed fairing, one black band,
# swept fins; its pieces can fly apart and land on their own pads.

LUNAR, CRATER, LUNAR_LIGHT = (70, 75, 90), (52, 56, 68), (98, 104, 122)
FALCON_INK = {'white': (238, 241, 247), 'shade': (196, 203, 218), 'black': (30, 34, 46), 'line': (14, 17, 26),
              'lit': (255, 226, 140)}
FIRE = ((255, 250, 214), (255, 206, 84), (250, 128, 48), (214, 68, 46))
PUFF = ((244, 246, 250), (204, 209, 220), (150, 156, 172))
GROK_WHITE = (242, 244, 248, 255)
DIZZY = ('.###.', '#...#', '#.#.#', '#..##', '.##..')
# The far, tiny Falcon of the loop-the-loop, too small for parts: W white, K black, G the window.
TINY_FALCON = ('..W..', '..W..', '.WWW.', '.WGW.', '.WWW.', '.WWW.', 'W.W.W', 'WWWWW', 'WWWWW', 'WWWWW',
               'WWWWW', 'WWWWW', 'W.W.W')


def falcon_size(height):
    """(core half-width, distance between core centres) for a Falcon Heavy `height` px tall."""
    half = max(1, round(height * .05))
    return half, 2 * half + 2  # a dark one-pixel gap keeps the cores apart


def falcon_window(height):
    """(drop from the art's top, radius) of the fairing's little window, lit while Grok is aboard."""
    return 3 + max(3, round(height * .16)), 1


def outlined(art, ink):
    """`art` with a one-pixel `ink` outline all round."""
    px = art.load()
    mask = [[px[xx, yy][3] > 0 for xx in range(art.width)] for yy in range(art.height)]
    for yy in range(art.height):
        for xx in range(art.width):
            if not mask[yy][xx] and any(0 <= xx + dx < art.width and 0 <= yy + dy < art.height and mask[yy + dy][xx + dx]
                                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                px[xx, yy] = ink
    return art


def falcon_core(d, ink, x, top, bottom, half, nose, fairing=0):
    """One white core with a pointed nose, its right side in shade; the top `fairing` rows a pixel wider."""
    wide = half + (1 if fairing else 0)
    rows = [(top + i, round(wide * (1 - (1 - i / (nose - 1)) ** 2))) for i in range(nose)]
    rows += [(yy, wide) for yy in range(top + nose, top + max(nose, fairing))]
    rows += [(yy, half) for yy in range(top + max(nose, fairing), bottom + 1)]
    for yy, hw in rows:
        d.line((x - hw, yy, x + hw, yy), fill=ink['white'])
        if hw >= 2:
            d.line((x + (hw + 1) // 2, yy, x + hw, yy), fill=ink['shade'])


@functools.lru_cache(maxsize=None)
def rocket_art(height, glass='empty', squash=0, parts=('left', 'centre', 'right')):
    """A slim Falcon Heavy `height` px tall: three cores, the fairing's window lit when `glass` is 'grok'.

    `parts` draws the stack or a single core (for the side boosters' twin landing); it is the stack's
    full width either way, so the cores stay where they were.
    """
    ink = {k: v + (255,) for k, v in FALCON_INK.items()}
    if height < 20:  # the far, tiny one
        art = Image.new('RGBA', (len(TINY_FALCON[0]) + 2, len(TINY_FALCON) + 2))
        colours = {'W': ink['white'], 'K': ink['black'], 'G': ink['lit'] if glass == 'grok' else ink['black']}
        for yy, row in enumerate(TINY_FALCON):
            for xx, key in enumerate(row):
                if key in colours:
                    art.putpixel((xx + 1, yy + 1), colours[key])
        return outlined(art, ink['line'])
    half, step = falcon_size(height)
    flare = max(1, round(height * .05))
    width = 3 * step + 2 * flare + 6
    art = Image.new('RGBA', (width, height + 2))
    d = ImageDraw.Draw(art)
    cx, top, bottom = width // 2, 1, height
    booster_top, booster_nose = top + round(height * .36), max(2, round(height * .1))
    band = booster_top + booster_nose  # one black interstage line across all three cores
    for part in parts:
        side = {'left': -1, 'centre': 0, 'right': 1}[part]
        x = cx + side * step
        if side:
            falcon_core(d, ink, x, booster_top, bottom, half, booster_nose)
            fin = max(3, round(height * .14))
            for i in range(fin):  # a swept fin on the outer side
                reach = round(flare * (i + 1) / fin)
                d.line((x + side * half, bottom - fin + 1 + i, x + side * (half + reach), bottom - fin + 1 + i),
                       fill=ink['white'] if side < 0 else ink['shade'])
        else:
            falcon_core(d, ink, x, top, bottom, half, max(3, round(height * .16)), round(height * .26))
            wy, _ = falcon_window(height)
            d.rectangle((x - 1, wy - 1, x + 1, wy + 1), fill=ink['black'])
            d.point((x, wy), fill=ink['lit'] if glass == 'grok' else ink['black'])
        d.line((x - half, band, x + half, band), fill=ink['black'])
    art = outlined(art, ink['line'])
    if squash:
        art = art.resize((art.width + 2 * squash, art.height - 2 * squash), Image.Resampling.NEAREST)
    return art


def scale2x(art):
    """EPX pixel-art doubling, the first step of RotSprite."""
    w, h = art.size
    src = art.load()
    out = Image.new('RGBA', (w * 2, h * 2))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            p = src[x, y]
            a, b = src[x, max(0, y - 1)], src[min(w - 1, x + 1), y]
            c, d = src[max(0, x - 1), y], src[x, min(h - 1, y + 1)]
            dst[2 * x, 2 * y] = a if c == a and c != d and a != b else p
            dst[2 * x + 1, 2 * y] = b if a == b and a != c and b != d else p
            dst[2 * x, 2 * y + 1] = c if d == c and d != b and c != a else p
            dst[2 * x + 1, 2 * y + 1] = d if b == d and b != a and d != c else p
    return out


def rotsprite(art, degrees):
    """`art` turned clockwise by `degrees`, RotSprite style (EPX ×8, turn, back down) so edges stay clean."""
    big = scale2x(scale2x(scale2x(art)))
    big = big.rotate(-degrees, resample=Image.Resampling.NEAREST, expand=True)
    return big.resize((max(1, big.width // 8), max(1, big.height // 8)), Image.Resampling.NEAREST)


@functools.lru_cache(maxsize=None)
def grok_pose(size, eyes='open', squash=0):
    """The bundled Grok bot in white with dark eyes, `size` px tall; eyes 'open', 'shut' or 'dizzy'."""
    with Image.open(ASSETS / 'grok-pixel.png') as source:
        box = source.convert('RGBA').getbbox()
    art = bot_sprite('grok', box[2] - box[0], box[3] - box[1], '#f2f4f8', (12, 14, 20)).copy()
    px = art.load()
    if eyes != 'open':
        dark = [(x, y) for y in range(art.height) for x in range(art.width) if px[x, y][3] and sum(px[x, y][:3]) < 200]
        for p in dark:
            px[p] = GROK_WHITE
        middle = sum(x for x, _ in dark) / len(dark)
        for group in ([p for p in dark if p[0] < middle], [p for p in dark if p[0] >= middle]):
            ex = round(sum(x for x, _ in group) / len(group))
            ey = round(sum(y for _, y in group) / len(group))
            if eyes == 'shut':  # a sleepy 'u'
                for x, yy in ((ex - 2, ey), (ex + 1, ey), (ex - 1, ey + 1), (ex, ey + 1)):
                    px[x, yy] = (12, 14, 20, 255)
            else:
                for dy, line in enumerate(DIZZY):
                    for dx, bit in enumerate(line):
                        if bit == '#':
                            px[ex - 2 + dx, ey - 2 + dy] = (12, 14, 20, 255)
    scale = size / art.height
    art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.Resampling.NEAREST)
    if squash:
        art = art.resize((art.width + 2 * squash, art.height - 2 * squash), Image.Resampling.NEAREST)
    return art


def stars(w, h, count):
    rnd = random.Random(w * 1000 + h)
    return [(rnd.randrange(w), rnd.randrange(h), rnd.randrange(3)) for _ in range(count)]


def plume(draw, cx, top, width, length, f):
    """A cartoon exhaust: a white-hot core inside yellow, orange and red, with a ragged, flickering edge."""
    rnd = random.Random(f % 4)
    for r in range(length):
        p = r / max(1, length)
        half = max(1, round(width / 2 * (1 - p * .75) + rnd.choice((-1, 0, 0, 1)) * (p > .3)))
        for ring, color in enumerate(FIRE):
            inner = max(0, round(half * (1 - ring * .28)) - (ring > 0) * round(p * 2))
            if ring and p < .15 * ring:
                continue
            if inner > 0:
                draw.line((cx - inner, top + r, cx + inner - 1, top + r), fill=color if ring == 0 else FIRE[min(3, ring)])
        if p > .55:
            draw.line((cx - half, top + r, cx + half - 1, top + r), fill=FIRE[3 if p > .8 else 2])
            core = max(0, round(half * .4))
            if core:
                draw.line((cx - core, top + r, cx + core - 1, top + r), fill=FIRE[1])


def puff(draw, cx, cy, r):
    """A round cartoon smoke puff: grey body, white crown."""
    if r < 1:
        return
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=PUFF[1])
    draw.ellipse((cx - r, cy + r // 3, cx + r, cy + r), fill=PUFF[2])
    draw.ellipse((cx - r * 2 // 3, cy - r, cx + r // 3, cy), fill=PUFF[0])


def ease_out(p):
    return 1 - (1 - p) ** 3


def grok_backdrop(draw, box, f, s):
    """Stars, a small Earth, the Moon's surface, the main deck and two side pads; returns the scene's layout."""
    x, y, w, h = box
    u = s / 2  # ½ on Arcade's 2 px grid
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=SKY['grok'])
    for i, (sx, sy, layer) in enumerate(stars(w, h, w * h // 500)):
        draw.point((x + sx, y + sy), fill=STARS[layer])  # still: the background does not move
    ex, ey, er = x + w - round(26 * u), y + round(20 * u), max(3, round(8 * u))  # a small Earth
    draw.ellipse((ex - er, ey - er, ex + er, ey + er), fill=(64, 124, 214))
    draw.ellipse((ex - er // 2, ey - er // 2, ex + er // 3, ey + er // 4), fill=(86, 172, 104))
    draw.point((ex - er // 2, ey - er + 1), fill=(220, 236, 255))
    ground = y + h - max(6, round(14 * u))
    draw.rectangle((x, ground, x + w - 1, y + h - 1), fill=LUNAR)
    draw.line((x, ground, x + w - 1, ground), fill=LUNAR_LIGHT)
    for cxr, wr in ((.1, 10), (.42, 6), (.86, 12)):  # craters
        ccx, cw2 = x + round(w * cxr), max(2, round(wr * u))
        draw.ellipse((ccx - cw2, ground + 3 * u, ccx + cw2, ground + 3 * u + max(2, cw2 // 2)), fill=CRATER)
    hr = max(29, round(86 * u))
    rx = x + round(w * .64)
    deck = ground - max(2, round(3 * u))
    rest_art = rocket_art(hr)
    _, step = falcon_size(hr)
    sep = round(3.2 * step)  # the side boosters' own landing pads
    for cx, half in ((rx, rest_art.width // 2 + round(4 * u)), (rx - sep, step // 2 + round(3 * u)),
                     (rx + sep, step // 2 + round(3 * u))):
        draw.rectangle((cx - half, deck, cx + half - 1, ground - 1), fill=DECK)
        draw.line((cx - half, deck, cx + half - 1, deck), fill=DECK_EDGE)
    return u, ground, deck, hr, rx, rest_art, max(12, round(31 * u)), x + round(w * .2), sep


def draw_stage(frame, draw, rx, deck, hr, u, parts, dx, lift, glass, squash, burn, legs, shiver, f):
    """One flying piece of the Falcon Heavy (the whole stack or one core), its plume and landing legs."""
    art = rocket_art(hr, glass, squash, parts)
    half, step = falcon_size(hr)
    top = deck - art.height + 1 - lift
    centres = [rx + dx + {'left': -step, 'centre': 0, 'right': step}[p] for p in parts]
    if burn:
        if len(parts) == 3:
            plume(draw, rx + dx, round(top + art.height - 1), max(4, round(art.width * .55)), burn, f)
        else:
            plume(draw, centres[0], round(top + art.height - 1), max(3, 2 * half + 2), burn, f)
    if legs:
        left, right = min(centres) - half, max(centres) + half
        for root_x, side in ((left + 1, -1), (right - 1, 1)):
            root = (root_x, top + art.height - round(hr * .16))
            foot = (root_x + side * round(4 * u * legs), top + art.height + round(2 * u * legs))
            draw.line((*root, *foot), fill=LEG, width=max(1, round(u)))
    paste(frame, art, rx + dx - art.width / 2 + shiver, top)


TANK, TANK_DARK = (150, 160, 176), (30, 34, 46)
FUEL, FUEL_TOP, FUEL_LOW = (240, 150, 50), (255, 204, 110), (236, 72, 64)


def fuel_tank(draw, x, ground, s, left, label=''):
    """Grok's fuel: a tank by the pad, full while there is plenty left and draining as the limit is used (red in
    the last 10%), with marks at a quarter, a half and three quarters; `left` None draws it empty and unread."""
    tw, th = 9 * s, 24 * s
    top = ground - th
    draw.rounded_rectangle((x, top, x + tw - 1, ground - 1), radius=2 * s, fill=TANK_DARK, outline=TANK)
    inner = th - 2 * s
    if left is not None:
        level = round(inner * max(0, min(1, left)))
        if level:
            colour = FUEL_LOW if left < .1 else FUEL
            draw.rectangle((x + s, ground - s - level, x + tw - 1 - s, ground - s - 1), fill=colour)
            draw.line((x + s, ground - s - level, x + tw - 1 - s, ground - s - level), fill=FUEL_LOW if left < .1 else FUEL_TOP)
    for q in (.25, .5, .75):
        my = ground - s - round(inner * q)
        draw.line((x + tw, my, x + tw + s, my), fill=TANK)
    draw.line((x + tw, ground - 3 * s, x + tw + 3 * s, ground - 3 * s), fill=TANK)  # the pipe toward the pad
    if s == 1 and label:
        gauge_label(draw, x + tw // 2, ground + 2, label, 'centre')


HOSE, CONSOLE, CONSOLE_GLASS, CODE_GREEN = (44, 46, 56), (120, 128, 144), (16, 24, 30), (110, 220, 160)


def grok_fuelling(draw, x, ground, k, s, size, rocket_left, worried):
    """Grok's first job at work: it walks the hose from the tank to the rocket, fills it (the fuel running along the
    hose), taps it twice with a wrench and walks back, a step a second; nearly out, it hurries to and fro twice.
    Returns where Grok stands (centre x, bottom, eyes, squash, size) and whether it faces left."""
    home, far = x + 2 * s + 9 * s + size // 2 + 2 * s, rocket_left - size // 2 - 3 * s
    t = (k * (2 if worried else 1)) % FRAMES
    if t < 24:
        gx, flip, sq = home + (far - home) * t / 24, False, 0
    elif t < 84:
        gx, flip, sq = far, False, 1 if t % 12 == 0 else 0
    elif t < 96:
        gx, flip, sq = far, False, 1 if (t - 84) % 6 < 3 else 0  # two taps with the wrench
    else:
        gx, flip, sq = far + (home - far) * (t - 96) / 24, True, 0
    bob = s if t % 12 < 6 and (t < 24 or t >= 96) else 0
    nozzle, hand = (x + 11 * s, ground - 20 * s), (round(gx) + (-size // 3 if flip else size // 3), ground - size // 2 - bob)
    sag = (round((nozzle[0] + hand[0]) / 2), max(nozzle[1], hand[1]) + 4 * s)
    draw.line((*nozzle, *sag), fill=HOSE, width=max(1, s))
    draw.line((*sag, *hand), fill=HOSE, width=max(1, s))
    if 24 <= t < 84:  # fuel running down the hose into the rocket
        for n in range(3):
            p = ((t * 2 + n * 8) % 24) / 24
            a, b = (nozzle, sag) if p < .5 else (sag, hand)
            q = p * 2 if p < .5 else p * 2 - 1
            draw.point((round(a[0] + (b[0] - a[0]) * q), round(a[1] + (b[1] - a[1]) * q)), fill=FUEL_TOP)
    if worried and t % 24 < 12:
        pixel_text(draw, (round(gx) - 2, ground - size - 12 * s), '!', color=(255, 226, 120))
    return (gx, ground - bob, 'open', sq, size), flip


def grok_at_console(draw, x, w, ground, k, s, size, worried):
    """Grok's other job: at the console by the pad, typing (a beat a second), lines of code going up the screen;
    now and then a hand to its headset, a look over at the rocket and back. Nearly out, the screen is red and it
    types twice as fast, hopping and looking from screen to rocket. Returns where Grok stands and whether it faces left."""
    cx0, top = x + w - 16 * s, ground - 12 * s
    draw.rectangle((cx0, top, cx0 + 12 * s, ground - 1), fill=CONSOLE)
    draw.rectangle((cx0 + 2 * s, top + 2 * s, cx0 + 10 * s, top + 7 * s), fill=(150, 24, 36) if worried else CONSOLE_GLASS)
    for n in range(3):  # the lines scroll up a row each half second
        ly = top + 3 * s + ((n * 2 - k // 6) % 5) * s
        if top + 2 * s <= ly <= top + 6 * s:
            draw.line((cx0 + 3 * s, ly, cx0 + (6 + 2 * ((n + k // 6) % 2)) * s, ly),
                      fill=(255, 220, 220) if worried else CODE_GREEN)
    gx = cx0 - size // 2 - 2 * s
    # a hand to the headset, a glance at the rocket; nearly out, hopping from foot to foot and glancing from screen
    # to rocket twice a second
    look = (k // 6) % 2 == 1 if worried else 40 <= k % 60 < 48
    beat = 3 if worried else 6
    sq = 1 if (k % (2 * beat) < beat and not look) else 0
    lift = 2 * s if worried and k % 6 < 3 else 0
    if worried and k % 24 < 12:
        pixel_text(draw, (round(gx) - 2, ground - size - 12 * s), '!', color=(255, 226, 120))
    return (gx, ground - lift, 'open', sq, size), look


def grok_scene(frame, draw, box, f, span, active, s, plan, centre=.5):
    x, y, w, h = box
    u, ground, deck, hr, rx, rest_art, gsize, gx0, sep = grok_backdrop(draw, box, f, s)
    if isinstance(plan, dict):
        used = plan.get('used')
        if used is not None:  # no reading, no tank: an empty one would say it ran dry
            fuel_tank(draw, x + 2 * s, ground, s, 1 - used / 100, plan.get('label', ''))
    _, step = falcon_size(hr)
    k = (f * FRAMES // span) % FRAMES if active else f  # one whole flight a turn (it runs at its own pace)
    glass, squash, shiver = 'empty', 0, 0
    whole = {'lift': 0.0, 'burn': 0, 'legs': 1.0}  # the stack in one piece, unless split below
    split = None  # [(parts, dx, lift, squash, burn, legs)] while the cores fly apart
    grok = None  # (centre x, bottom y, eyes, squash, size)
    lamp = active  # the pad's light is on, steady, while the rocket is being readied
    win_y = deck - rest_art.height + 1 + falcon_window(hr)[0]
    flip = False
    if not active:
        idle = idle_now(plan, f, span)
        breath = 1 if 20 <= f % 48 < 28 else 0
        blink = 'shut' if f % 40 in (20, 21) else 'open'
        if idle == 'wander':  # two steps out, two steps back, a little bob on each
            t = f % 48
            reach = (0, 1, 2, 2, 1, 0, 0, 0)[t // 6]
            flip = 18 <= t < 36
            bob = round(2 * u) if t % 6 < 3 and t < 36 else 0
            grok = (gx0 + reach * round(7 * u), ground - bob, blink, 0, gsize)
        elif idle == 'fret':  # pacing up and down by the rocket in quick little steps, '!' now and then
            t = f % 24
            flip = t >= 12
            p = t / 12 if t < 12 else 2 - t / 12
            bob = round(abs(math.sin(f * math.pi / 3)) * 3 * u)
            grok = (gx0 + p * 26 * u, ground - bob, blink, 1 if f % 3 == 0 else 0, gsize)
            if (f // 12) % 2 == 0:
                pixel_text(draw, (round(grok[0] - 2), round(ground - gsize - 14 * u)), '!', color=(255, 226, 120))
        elif idle == 'gaze':  # up at the Earth, with a hop now and then
            lift = round(4 * (f % 24) / 6 * (1 - (f % 24) / 6) * 5 * u) if f % 24 < 6 else 0
            grok = (gx0, ground - lift, blink, 1 if f % 24 == 6 else 0, gsize)
        else:
            grok = (gx0, ground, 'shut', breath, gsize)
            t = f % 40
            if t < 30:
                pixel_text(draw, (round(gx0 + gsize // 2 + t * u * .8), round(ground - gsize - 4 - t * u * 1.2)), 'z',
                           scale=2 if u >= 1 and t >= 12 else 1, color=PUFF[1] if t < 22 else PUFF[2])
        if isinstance(plan, dict):
            mood_marks(draw, round(grok[0] + gsize * .3), ground - gsize - round(4 * u), max(1, s // 2 + (s > 2)), f,
                       plan.get('mood'), idle == 'nap')
    else:  # at work, outside: fuelling the rocket from the tank, or at the console running the checks
        worried = isinstance(plan, dict) and plan.get('mood') == 'worried'
        role = plan.get('role', 'crew') if isinstance(plan, dict) else 'crew'
        for start in (0, 30, 60, 90):  # the Falcon vents steam from both sides
            age = k - start
            if 0 <= age < 12:
                for side in (-1, 1):
                    puff(draw, rx + side * (rest_art.width // 2 + age * u * 1.5), deck - age * u * .6, round((2 + age / 3) * u))
        if role == 'control':
            grok, flip = grok_at_console(draw, x, w, ground, k, s, gsize, worried)
            if 64 <= k < 80 and not worried:  # the console fires a short test burn: a rumble, a lift, a flame
                t = k - 64
                whole = {'lift': round(min(t, 16 - t) * u * .5), 'burn': round((4 + min(t, 6)) * u), 'legs': 1.0}
                shiver = 1 if t % 2 else -1
            elif worried:  # nearly dry: the rocket rattles on the pad
                shiver = 1 if (k // 3) % 2 else -1
        else:
            grok, flip = grok_fuelling(draw, x, ground, k, s, gsize, rx - rest_art.width // 2, worried)
    if whole is not None:
        draw_stage(frame, draw, rx, deck, hr, u, ('left', 'centre', 'right'), 0, whole['lift'], glass, squash,
                   whole['burn'], whole['legs'], shiver, f)
    for parts, dx, lift, sq, burn, legs in split or ():
        draw_stage(frame, draw, rx, deck, hr, u, parts, dx, lift, glass, sq, burn, legs, 0, f)
    if not active or k < 37:
        draw.rectangle((rx - rest_art.width // 2 - round(4 * u), deck - 1, rx - rest_art.width // 2 - round(4 * u) + max(1, round(u)), deck - 1),
                       fill=(255, 90, 90) if lamp else DECK_EDGE)
    if grok:
        gx, bottom, eyes, sq, size = grok
        if active and isinstance(plan, dict) and plan.get('mood') == 'worried':
            mood_marks(draw, round(gx + size * .3), round(bottom - size - 4 * u), max(1, s // 2 + (s > 2)), f, 'worried')
        art = grok_pose(size, eyes, sq)
        if flip:
            art = art.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        paste(frame, art, gx - art.width / 2, bottom - art.height)


# --- Copilot ---------------------------------------------------------------------------------
# Copilot flies a little propeller plane through the clouds, a teal-to-blue trail behind it;
# idle, it dozes on a cloud.

COPILOT_SKY = ((9, 26, 66), (11, 38, 84), (12, 52, 98), (14, 68, 112))  # night blue to teal, top to bottom
CLOUD_TOP, CLOUD_BASE = (232, 244, 255), (176, 204, 232)
PLANE = {'body': (242, 246, 251), 'shade': (190, 204, 222), 'wing': (46, 196, 206), 'trim': (37, 99, 235),
         'dark': (30, 40, 62), 'prop': (170, 180, 200)}
TRAIL = ((54, 216, 180), (38, 194, 204), (31, 167, 226), (37, 99, 235))


# Copilot's mascot (assets/copilot-pixel.png, after the owner's pixel reference) scales down cleanly to the
# head Arcade draws on its cloud (COPILOT_HEAD px tall); on the plane it is only 8 px, so that one is placed by
# hand in the same colours: N navy (visor, goggle glass), C cyan dome, B blue ear pods, E the eyes.
COPILOT_HEAD = 20
COPILOT_INK = {'N': (25, 29, 57), 'C': (168, 247, 248), 'B': (112, 173, 239), 'E': (224, 252, 250)}
COPILOT_SMALL = {8: ('..CCCC..', '.CNCCNC.', 'BCCCCCCB', 'BNNNNNNB', 'BNENNENB', 'BNENNENB', '.CCCCCC.')}


@functools.lru_cache(maxsize=None)
def copilot_pose(size, eyes='open'):
    """Copilot's face `size` px tall; with eyes 'shut' the glowing pills close to their bottom row."""
    small = COPILOT_SMALL.get(size)
    if small:
        rows = small
        if eyes == 'shut':  # every eye row but the last turns to visor
            last = max(y for y, line in enumerate(rows) if 'E' in line)
            rows = [line.replace('E', 'N') if y < last else line for y, line in enumerate(rows)]
        art = Image.new('RGBA', (len(rows[0]), len(rows)))
        for y, line in enumerate(rows):
            for x, key in enumerate(line):
                if key in COPILOT_INK:
                    art.putpixel((x, y), COPILOT_INK[key] + (255,))
        return art
    with Image.open(ASSETS / 'copilot-pixel.png') as source:
        art = source.convert('RGBA')
    art = art.crop(art.getbbox())
    scale = size / art.height
    art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.Resampling.NEAREST)
    if eyes == 'shut':  # the eyes are the light pixels with dark visor on both sides, low on the face
        px = art.load()
        dark = lambda p: p[3] and sum(p[:3]) < 200
        light = lambda p: p[3] and sum(p[:3]) > 450
        eye = [(x, y) for y in range(art.height // 2, art.height) for x in range(1, art.width - 1)
               if light(px[x, y]) and dark(px[x - 1, y]) and (dark(px[x + 1, y]) or (light(px[x + 1, y]) and dark(px[min(x + 2, art.width - 1), y])))]
        if eye:
            bottom = max(y for _, y in eye)
            for x, y in eye:
                if y < bottom:
                    px[x, y] = COPILOT_INK['N'] + (255,)
    return art


def cloud(draw, cx, cy, r, top=CLOUD_TOP, base=CLOUD_BASE):
    """A puffy pixel cloud of radius r: three bumps on a flat base, lit from above."""
    for dx, dy, k in ((-r, r // 3, .75), (0, 0, 1), (r, r // 3, .7)):
        rr = round(r * k)
        draw.ellipse((cx + dx - rr, cy + dy - rr, cx + dx + rr, cy + dy + rr), fill=top)
    draw.rectangle((cx - r - round(r * .7), cy + r // 3, cx + r + round(r * .7), cy + r // 3 + max(2, r // 2)), fill=base)


# The plane, 30 × 15 at u = ½: W body, S belly, B blue (fin, cheat line), T teal (wing, tailplane), K spinner.
PLANE_ROWS = (
    '.BB...........................',
    '.BBB..........................',
    '..BBB.........................',
    '..BBBB........................',
    '...BBBB.......................',
    '...BBBBB......................',
    '...BBBBWWWWWWWWWWWWWWWWWWW....',
    '...WWWWWWWWWWWWWWWWWWWWWWWWW..',
    'TTTTTWBBBBBBBBBBBBBBBBBBBBBWW.',
    '...WWWWWWWWWWWWWWWWWWWWWWWWWWK',
    '....SSSSSSSSSSSSSSSSSSSSSSSSSK',
    '......SSSSSSTTTTTTTTSSSSSSSS..',
    '...........TTTTTTTT...........',
    '..........TTTTTTT.............',
    '.........TTTTTT...............',
)


@functools.lru_cache(maxsize=None)
def plane(u, blade):
    """Copilot's plane facing right, `u` units big: a tall fin, a swept wing, a cheat line; `blade` 0/1 spins the prop."""
    ink = {'W': PLANE['body'], 'S': PLANE['shade'], 'B': PLANE['trim'], 'T': PLANE['wing'], 'K': PLANE['dark']}
    art = Image.new('RGBA', (len(PLANE_ROWS[0]) + 2, len(PLANE_ROWS)))
    for y, row in enumerate(PLANE_ROWS):
        for x, key in enumerate(row):
            if key in ink:
                art.putpixel((x, y), ink[key] + (255,))
    for y in (range(3, 15) if blade else range(8, 12)):  # the blade end-on, or edge-on and short
        art.putpixel((art.width - 1, y), PLANE['prop'] + (255,))
    k = max(1, round(2 * u))
    return art.resize((art.width * k, art.height * k), Image.Resampling.NEAREST) if k > 1 else art


def copilot_backdrop(draw, box, f, s, far=0, clouds=True):
    """Night blue to teal, a few stars and (unless the scene counts its own) the far clouds, `far` px along."""
    x, y, w, h = box
    u = s / 2
    for k, tone in enumerate(COPILOT_SKY):
        draw.rectangle((x, y + k * h // 4, x + w - 1, y + (k + 1) * h // 4 - 1), fill=tone)
    for i, (sx, sy, layer) in enumerate(stars(w, h // 2, w * h // 900)):
        draw.point((x + sx, y + sy), fill=STARS[layer])
    period = w + round(80 * u)
    for i, (fx, fy, r) in enumerate(((.15, .3, 7), (.6, .22, 6), (.95, .36, 8)) if clouds else ()):  # far, drifting
        cx = x + (round(fx * period) - far) % period - round(40 * u)
        cloud(draw, cx, y + round(fy * h), max(3, round(r * u)))
    return period


CLOUD_SPOT = (24, 48, 86)  # a patch of sky still waiting for its cloud


def cloud_count(draw, box, s, used, label=''):
    """Copilot's gauge: five clouds across the sky, one for each 20% used, the next one growing with the
    reading through its fifth; the patches still clear show faintly, so the five places always read."""
    x, y, w, h = box
    done = 0 if used is None else min(5, int(used // 20))
    part = 0 if used is None or done == 5 else (used % 20) / 20
    for i in range(5):
        cx, cy = x + round(w * (i + .5) / 5), y + round(h * (.2 if i % 2 else .16))
        if i < done:
            cloud(draw, cx, cy, 5 * s)
        else:
            cloud(draw, cx, cy, 5 * s, CLOUD_SPOT, CLOUD_SPOT)
            if i == done and part:
                cloud(draw, cx, cy, max(1, round((1 + 3 * part) * s)))  # never full until the fifth is done
    if s == 1 and label:
        gauge_label(draw, x + 1, y + 1, label)


def copilot_scene(frame, draw, box, f, span, active, s, plan, centre=.5):
    x, y, w, h = box
    u = s / 2
    period = copilot_backdrop(draw, box, f, s, clouds=False)  # the sky stands still; the plane crosses it
    used = plan.get('used') if isinstance(plan, dict) else None
    level = y + round(h * .52)  # where it flies, under the clouds that count its use
    if isinstance(plan, dict) and used is not None:
        cloud_count(draw, box, s, used, plan.get('label', ''))
    if active:
        # One crossing a loop of the scene, in from the left and out on the right with its trail; it bobs about
        # once a second, and twice as fast, shaking, its trail sputtering, when nearly out.
        worried = isinstance(plan, dict) and plan.get('mood') == 'worried'
        bobs = max(1, round(span / (FPS * SPEED))) * (2 if worried else 1)
        art = plane(u, (f // 2) % 2)  # f is even at twice the pace, so f % 2 would freeze the prop
        pace = plan.get('pace', 3) if isinstance(plan, dict) else 3
        segments = 4 + min(6, round(pace))  # the trail, teal to blue: longer the harder it works
        reach = w + art.width + segments * round(5 * u)
        bob = round(math.sin(2 * math.pi * f / span * bobs) * (3 if worried else 2) * u)
        px_ = x - art.width + round(reach * (f / span))
        py_ = level - art.height // 2 + bob
        for k in range(segments):
            if worried and (k + f // 4) % 3 == 0:
                continue  # sputtering
            tx = px_ + round(4 * u) - k * round(5 * u)
            ty = py_ + round(18 * u) - bob + round(math.sin(k / 2) * u)
            if x <= tx < x + w:
                c = TRAIL[min(len(TRAIL) - 1, k * len(TRAIL) // 10)]
                d = max(1, round(2 * u))
                draw.rectangle((tx, ty, tx + d - 1, ty + d - 1), fill=c)
        head = copilot_pose(max(8, round(17 * u)))
        paste(frame, head, px_ + round(30 * u) - head.width / 2, py_ + round(17 * u) - head.height)
        paste(frame, art, px_, py_)
        if isinstance(plan, dict) and plan.get('mood') == 'worried':  # nearly out, still flying: sweating
            mood_marks(draw, round(px_ + 30 * u), round(py_ + 17 * u - head.height - 3 * u), max(1, s // 2 + (s > 2)),
                       f, 'worried')
    else:
        base_y = y + round(h * .78)  # resting on its cloud, low in the sky
        idle = idle_now(plan, f, span)
        if idle == 'fret':  # nearly out: the plane parked on the next cloud, its warning light on
            centre = .3
            px_ = x + round(w * .72)
            cloud(draw, px_, base_y, max(5, round(14 * u)))
            art = plane(u, 0)
            paste(frame, art, px_ - art.width / 2, base_y - art.height + round(3 * u))
            lamp = (round(px_ - art.width / 2 + 2 * u), round(base_y - art.height + round(3 * u) - 2 * u))
            draw.rectangle((*lamp, lamp[0] + max(2, round(4 * u)) - 1, lamp[1] + max(2, round(4 * u)) - 1),
                           fill=(255, 84, 84))  # the warning light, on and steady
        cloud(draw, x + round(w * centre), base_y, max(5, round(14 * u)))
        eyes = 'shut' if idle == 'nap' or f % 40 in (14, 15) else 'open'
        head = copilot_pose(max(10, round(COPILOT_HEAD * s)), eyes)
        if idle == 'look' and (f // 20) % 2:  # looking about, one side then the other
            head = head.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if idle == 'fret' and (f // 6) % 2:  # glancing at the plane and back, quickly
            head = head.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        breath = 1 if idle == 'nap' and 20 <= f % 48 < 28 else 0
        lift = round(4 * (f % 16) / 8 * (1 - (f % 16) / 8) * 6 * u) if idle == 'hop' and f % 16 < 8 else 0
        if idle == 'fret':  # fidgeting on its cloud, twice a second
            lift = round(2 * u) if f % 12 < 4 else 0
        hy = base_y - head.height - round(4 * u) + breath - lift
        paste(frame, head, x + round(w * centre - head.width / 2), hy)
        if idle == 'nap':
            t = f % 40
            if t < 30:
                pixel_text(draw, (round(x + w * centre + head.width / 2 + t * u * .8), round(base_y - head.height - 6 * u - t * u)),
                           'z', scale=2 if u >= 1 and t >= 12 else 1, color=CLOUD_BASE if t < 22 else (120, 150, 190))
        if isinstance(plan, dict):
            mood_marks(draw, round(x + w * centre + head.width * .25), hy - round(3 * u), max(1, s // 2 + (s > 2)), f,
                       plan.get('mood'), idle == 'nap')


# --- Anti (Antigravity) -------------------------------------------------------------------------
# Antigravity is Anti, a ghost made of its logo: the logo's 12 x 10 blocks (assets/antigravity-logo.png) at
# 2 x 2, one chin row under the mouth, a ghost's hem along its feet, bean eyes and a cat's mouth. It lives in a
# maze after the old arcade halls (none of their characters, only the maze, the dots and the pellets): at work it
# patrols the loop round the centre wall, eyes on the next turn; at rest it waits in the house behind the pink
# door; the four power pellets are what is left of its 5 hours. Near the limit it turns blue, like a frightened
# ghost: slow and backing off at work, hiding its face at rest.

ANTI_NAVY, ANTI_PEACH, ANTI_RED = (14, 16, 30), (255, 184, 174), (255, 0, 0)
ANTI_SCARED, ANTI_FLASH = (33, 33, 222), (222, 222, 255)
MAZE_WALL, MAZE_DOT, MAZE_BG, MAZE_DOOR = (33, 33, 222), (255, 184, 174), (2, 2, 8), (255, 184, 255)
ANTI_CHIN = ((10, (88, 149, 216)), (11, (88, 149, 216)), (12, (86, 125, 221)), (13, (86, 125, 221)))
ANTI_FEET = frozenset((x, 19) for x in (0, 1, 2, 3, 20, 21, 22, 23))
BEAN, BEAN_SHUT, CAT_MOUTH = ('XX', 'XX', 'XX'), ('XX',), ('X.X.X', '.X.X.')
DOT_EYE, SMILE_EYE, ZED = ('XX', 'XX'), ('.X.', 'X.X'), ('XXX', '..X', '.X.', 'X..', 'XXX')
# The patrol: the sprite's corner round the centre wall, and the pellets, used from the top left round to the
# bottom left (what is left sits in the last corners).
ANTI_LOOP = ((3, 9), (93, 9), (93, 41), (3, 41))
ANTI_PELLETS = ((15, 19), (105, 19), (105, 51), (15, 51))
ANTI_HOME = (48, 36)  # Anti in the house


def grid_stamp(draw, x, y, rows, ink):
    for yy, line in enumerate(rows):
        for xx, key in enumerate(line):
            if key != '.':
                draw.point((x + xx, y + yy), fill=ink)


def wavy(draw, x0, x1, y, ink):
    for i, xx in enumerate(range(x0, x1 + 1)):
        draw.point((xx, y + (i // 2) % 2), fill=ink)


def anti_face(draw, face, dx=0, dy=0):
    """Anti's faces on its 24 x 20 sprite, eyes looking (dx, dy): 'normal' (beans and the cat's mouth), 'blink' or
    'sleep', 'happy' (^ ^), 'curious' (dots), 'roll' (dots rolled up), 'scared', 'wide_scared' and 'low_scared'
    (hiding) with their 'flash' versions, and 'eaten' (the eyes alone)."""
    if face in ('normal', 'curious'):
        eye = BEAN if face == 'normal' else DOT_EYE
        grid_stamp(draw, 9 + dx, 4 + dy, eye, ANTI_NAVY)
        grid_stamp(draw, 13 + dx, 4 + dy, eye, ANTI_NAVY)
        grid_stamp(draw, 10, 8, CAT_MOUTH, ANTI_NAVY)
    elif face in ('blink', 'sleep'):
        grid_stamp(draw, 9 + dx, 5, BEAN_SHUT, ANTI_NAVY)
        grid_stamp(draw, 13 + dx, 5, BEAN_SHUT, ANTI_NAVY)
        grid_stamp(draw, 10, 8, CAT_MOUTH, ANTI_NAVY)
    elif face == 'roll':
        grid_stamp(draw, 9, 3, DOT_EYE, ANTI_NAVY)
        grid_stamp(draw, 13, 3, DOT_EYE, ANTI_NAVY)
        grid_stamp(draw, 10, 8, CAT_MOUTH, ANTI_NAVY)
    elif face == 'happy':
        grid_stamp(draw, 8, 4, SMILE_EYE, ANTI_NAVY)
        grid_stamp(draw, 13, 4, SMILE_EYE, ANTI_NAVY)
    elif face == 'eaten':
        grid_stamp(draw, 9 + dx, 4 + dy, BEAN, ANTI_PEACH)
        grid_stamp(draw, 13 + dx, 4 + dy, BEAN, ANTI_PEACH)
    else:
        ink = ANTI_RED if face.endswith('flash') else ANTI_PEACH
        if face.startswith('wide'):
            eyes, mouth = ((8, 5), (14, 5)), (6, 17, 8)
        elif face.startswith('low'):
            eyes, mouth = ((9, 14), (13, 14)), (7, 16, 17)
        else:
            eyes, mouth = ((9, 5), (13, 5)), (8, 15, 8)
        for ex, ey in eyes:
            draw.rectangle((ex, ey, ex + 1, ey + 1), fill=ink)
        wavy(draw, *mouth, ink)


@functools.lru_cache(maxsize=None)
def anti_logo():
    return Image.open(ASSETS / 'antigravity-logo.png').convert('RGBA')


@functools.lru_cache(maxsize=1024)
def anti_art(face='normal', body='logo', step=0, dx=0, dy=0, flip=False, scale=1):
    """Anti, 24 x 20 at scale 1: its logo body ('logo', 'scared' blue, 'flash' pale, or 'none' for the eyes alone),
    the hem stepping with `step`, the face looking (dx, dy), upside down with `flip`."""
    art = Image.new('RGBA', (24, 20))
    draw = ImageDraw.Draw(art)
    if body != 'none':
        logo = anti_logo()
        tone = {'scared': ANTI_SCARED, 'flash': ANTI_FLASH}.get(body)
        for by in range(logo.height):
            for bx in range(logo.width):
                colour = logo.getpixel((bx, by))
                if not colour[3]:
                    continue
                for px_ in (2 * bx, 2 * bx + 1):
                    for py_ in (2 * by, 2 * by + 1):
                        if (px_, py_) not in ANTI_FEET or (px_ + step) % 2 == 0:  # the hem, alternate pixels
                            draw.point((px_, py_), fill=tone or colour[:3])
        for cx, colour in ANTI_CHIN:
            draw.point((cx, 10), fill=tone or colour)
    anti_face(draw, face, dx, dy)
    if flip:
        art = art.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return art.resize((24 * scale, 20 * scale), Image.Resampling.NEAREST) if scale != 1 else art


def anti_pellets(draw, box, left, label=''):
    """The gauge: a power pellet in each corner for every 25% left of the 5 hours, the last one smaller as it
    runs down; used ones leave a faint mark, so the four places always read. They never blink."""
    x, y, w, h = box
    count = 0 if left is None else max(0.0, min(1.0, left)) * 4
    full, part = int(count), count - int(count)
    for i in range(4):
        px_, py_ = ANTI_PELLETS[3 - i]
        px_, py_ = x + px_, y + py_
        if i < full:
            draw.ellipse((px_ - 3, py_ - 3, px_ + 3, py_ + 3), fill=MAZE_DOT)
        elif i == full and part > .05:
            r = 2 if part >= .5 else 1
            draw.ellipse((px_ - r, py_ - r, px_ + r, py_ + r), fill=MAZE_DOT)
        else:
            draw.point((px_, py_), fill=(90, 70, 80))
    if label:
        gauge_label(draw, x + 1, y + 1, label)


def anti_maze(draw, box, f, s, left, house=False, label='', wall=MAZE_WALL, door=True, pellets=True):
    """The still maze: an outer wall, rows of dots, and in the middle the centre wall (work) or the house with
    its pink door (rest), with the pellets (left out where the scene cannot know the reading: a gauge may go
    missing for a scene, never show a wrong value)."""
    x, y, w, h = box
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=MAZE_BG)
    draw.rounded_rectangle((x + 1, y + 7, x + 118, y + 63), radius=4, outline=wall)
    if house:
        draw.rectangle((x + 44, y + 31, x + 76, y + 59), outline=wall)
        draw.rectangle((x + 45, y + 32, x + 75, y + 58), outline=wall)
        draw.rectangle((x + 54, y + 31, x + 66, y + 32), fill=MAZE_DOOR if door else MAZE_BG)
    else:
        draw.rounded_rectangle((x + 29, y + 31, x + 91, y + 39), radius=3, outline=wall)
    for dx in range(30, 92, 6):
        for dy in (19, 51):
            draw.rectangle((x + dx, y + dy, x + dx + 1, y + dy + 1), fill=MAZE_DOT)
    for dy in (31, 37):
        for dx in (15, 105):
            draw.rectangle((x + dx, y + dy, x + dx + 1, y + dy + 1), fill=MAZE_DOT)
    if pellets:
        anti_pellets(draw, box, left, label)


def anti_on_loop(s_):
    """Where the patrol is at distance `s_` round the loop, and which way the eyes look: along the way, and toward
    the next turn just before each corner."""
    corners = ANTI_LOOP
    lengths = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(corners, corners[1:] + corners[:1])]
    s_ %= sum(lengths)
    for i, length in enumerate(lengths):
        a, b = corners[i], corners[(i + 1) % 4]
        if s_ <= length:
            p = s_ / length
            ux, uy = (b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1])
            if length - s_ < 8:
                c = corners[(i + 2) % 4]
                ux, uy = (c[0] > b[0]) - (c[0] < b[0]), (c[1] > b[1]) - (c[1] < b[1])
            return a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p, ux, uy
        s_ -= length
    return corners[0][0], corners[0][1], 1, 0


def anti_left(plan, row=None):
    """What is left of the window the pellets follow: the 5 hours where there is one, else the scene's own."""
    if isinstance(plan, dict) and plan.get('anti') is not None:
        return plan['anti']
    used = plan.get('used') if isinstance(plan, dict) else None
    return None if used is None else 1 - used / 100


def anti_scene(frame, draw, box, f, span, active, s, plan, centre=.5):
    x, y, w, h = box
    worried = isinstance(plan, dict) and plan.get('mood') == 'worried'
    happy = isinstance(plan, dict) and plan.get('mood') == 'happy'
    label = plan.get('anti_label', '') if isinstance(plan, dict) and s == 1 else ''
    anti_maze(draw, box, f, s, anti_left(plan), house=not active, label=label, pellets=anti_left(plan) is not None)
    if active and worried:  # frightened: blue, backing and forth along the top, slowly
        t = f / span
        px_ = x + 20 + 50 * (1 - math.cos(2 * math.pi * t)) / 2
        paste(frame, anti_art('scared', 'scared', (f // 3) % 2), px_, y + 9)
        return
    if active:  # the patrol: one round of the loop a turn, eyes on the way ahead
        lengths = 2 * (abs(ANTI_LOOP[1][0] - ANTI_LOOP[0][0]) + abs(ANTI_LOOP[2][1] - ANTI_LOOP[1][1]))
        px_, py_, ux, uy = anti_on_loop(f / span * lengths)
        face = 'happy' if happy else 'blink' if f % 36 in (30, 31) else 'normal'
        paste(frame, anti_art(face, 'logo', (f // 6) % 2, ux if face == 'normal' else 0, uy if face == 'normal' else 0),
              x + px_, y + py_)
        return
    hx, hy = x + ANTI_HOME[0], y + ANTI_HOME[1]
    idle = idle_now(plan, f, span)
    if idle == 'fret':  # frightened at rest: blue in the house, bobbing fast, hiding its face
        paste(frame, anti_art('low_scared', 'scared', (f // 3) % 2), hx, hy + round(math.sin(2 * math.pi * f / 6)))
    elif idle == 'look':  # looking round: one side, the other, up at the door, down
        dx, dy = ((-1, 0), (1, 0), (0, -1), (0, 1))[min(3, int(f / max(1, span / 2) * 4)) % 4]
        paste(frame, anti_art('happy' if happy else 'curious', 'logo', 0, dx, dy), hx, hy - (1 if dy < 0 else 0))
    elif idle == 'bob':  # awake, bobbing gently, a blink every three seconds
        face = 'happy' if happy else 'blink' if f % 36 in (30, 31) else 'normal'
        paste(frame, anti_art(face, 'logo', 0), hx, hy + round(2 * math.sin(2 * math.pi * f / 24)))
    else:  # asleep: a slow breath and the z's
        paste(frame, anti_art('sleep', 'logo', 0), hx, hy + 2 + round(math.sin(2 * math.pi * f / 36)))
        t = f % 36
        if t < 30:
            grid_stamp(draw, hx + 22 + t // 9, hy - 6 - t // 3, ZED, (230, 230, 240))


SCENES = {'claude': claude_scene, 'codex': codex_scene, 'grok': grok_scene, 'copilot': copilot_scene,
          'antigravity': anti_scene}


# --- Layouts ---------------------------------------------------------------------------------

def label_of(row):
    return account_label(row)


def info(row, now, value=None):
    """(used, window name, old?, coarse time left) for one window; by default the row's weekly one."""
    if value is None:
        wins = shown_windows(row, 3)
        value = wins[0] if wins else None
    used, period, old, _ = reading(row, value)
    left = coarse_left(value.get('resets_at'), now) if value else '--'
    return used, period, old, left


IDLE_SETS = {'codex': ('nap', 'drift', 'yawn'), 'grok': ('nap', 'wander', 'gaze'), 'copilot': ('nap', 'look', 'hop'),
             'antigravity': ('nap', 'look', 'bob')}


def mood(used):
    """How the reading feels: 'worried' near the limit, 'happy' with plenty left (the store keeps 'worried' on until
    the reading drops below 85%, so it does not flicker at the edge)."""
    if used is None:
        return 'calm'
    return 'worried' if used >= 90 else 'happy' if used < 20 else 'calm'


def scene_plan(row, now, span=FRAMES / FPS):
    """What a scene needs beyond the frame: the used % (Codex's garden, everyone's mood), the limit its picture
    follows, the pace of work, and this minute of rest (REST_FLOW): Clawd's move, or the others' two behaviours."""
    used = info(row, now)[0]
    wins = shown_windows(row, 3)
    plan = {'used': used, 'mood': 'worried' if row.get('worry') and used is not None else mood(used), 'moves': [],
            'idle': ('nap', 'nap'),
            'label': quota_period(wins[0]) if wins else ''}
    stamp = now if now is not None else time.time()
    plan['pace'] = max([item['value'] for item in row.get('news') or () if item.get('kind') == 'jump'
                        and stamp - item.get('at', 0) < 600] or [0]) if 'news' in row else 3  # % per ten minutes
    five = next((w for w in row.get('windows', []) if w.get('label') == '5H'), None)
    if row['provider'] == 'claude' and five and five.get('used_percent') is not None:
        plan['moon'] = max(0, 100 - five['used_percent']) / 100  # what is left of the 5-hour window
    if row['provider'] == 'grok':  # its job at work, fuelling or at the console, picked at random ten minutes at a time
        plan['role'] = row.get('role') or random.Random(f"{row.get('key')}|{int(stamp // 600)}").choice(('crew', 'control'))
    if row['provider'] == 'antigravity':  # Anti's pellets: the 5 hours where there is such a window
        follow = five if five and five.get('used_percent') is not None else (wins[0] if wins else None)
        if follow and follow.get('used_percent') is not None:
            plan['anti'] = max(0, 100 - follow['used_percent']) / 100
            plan['anti_label'] = quota_period(follow)
    if row.get('showcase'):  # a preview can ask for particular moves, to show each one
        named = row['showcase']
        if row['provider'] == 'claude':
            t = .5
            for move in named:
                name, first, last = IDLE_MOVES[move]
                length = (last - first + 1) / (12 * PACE)
                plan['moves'].append((t, t + length, name, first, last))
                t += length + .4
        else:
            plan['idle'] = (named[0], named[-1])
    elif row['provider'] == 'claude':
        plan['moves'] = idle_plan(row, now, span)
    elif row['provider'] in FLOW_MOVES:
        step, _ = rest_step(row['provider'], now)
        plan['idle'] = (FLOW_MOVES[row['provider']][step], 'nap') if step else ('nap', 'nap')
    if plan['mood'] == 'worried' and row['provider'] in IDLE_SETS:  # nearly out: each frets its own way
        plan['idle'] = ('fret', 'fret')  # (Clawd paces, in its own scene)
    return plan


def idle_now(plan, f, span):
    """Which idle behaviour plays at frame `f`: the first half of the turn, then the second."""
    idle = plan.get('idle', ('nap', 'nap')) if isinstance(plan, dict) else ('nap', 'nap')
    return idle[0] if f < span / 2 else idle[1]


NOTE_ROWS = ('..##', '..#.', '..#.', '###.', '##..')


def mood_marks(draw, x, y, s, f, feeling, asleep=False):
    """Over a head at (x, y): sweat when the quota is nearly gone, a note now and then when it is fresh
    (not in its sleep: a napper shows only its z's)."""
    if feeling == 'worried':
        for k, side in enumerate((1, -1)):
            t = (f + k * 9) % 18
            if t < 10:
                sweat_drop(draw, round(x + side * (3 + t // 3) * s), round(y + t * s // 2), s)
    elif feeling == 'happy' and not asleep and f % 40 < 16:
        t = f % 40
        for yy, line in enumerate(NOTE_ROWS):
            for xx, key in enumerate(line):
                if key == '#':
                    draw.rectangle((x + (xx + t // 4) * s, y - t * s // 2 + yy * s, x + (xx + t // 4) * s + s - 1,
                                    y - t * s // 2 + yy * s + s - 1), fill=(255, 226, 140))


def shown_rows(snapshot, now=None):
    """The accounts Arcade takes turns on: the working ones, or every one while all are idle. Four at most share
    a loop; with more, the four move on with each round of the rest flow (six minutes), so every account gets its
    turns and each four rest through one look round and one stretch. A new four is a new picture for the clock,
    and the clock's animation holds while it takes one."""
    if not snapshot.get('accounts'):
        return overview_rows(snapshot)  # placeholders
    order = list(PROVIDERS)
    every = [dict(row, key=key) for key, row in snapshot['accounts'].items()]
    every.sort(key=lambda row: order.index(row['provider']) if row['provider'] in order else len(order))
    pool = [row for row in every if row.get('active')] or every
    if len(pool) <= MAX_ROWS:
        return pool
    start = int((time.time() if now is None else now) // (60 * len(REST_FLOW))) * MAX_ROWS % len(pool)
    return [pool[(start + k) % len(pool)] for k in range(MAX_ROWS)]


def egg_scene(egg, row):
    """The one-off that replaces `row`'s usual scene, as (scene, tier): an event ('reset@key' or
    'full@key', common: every pet has them, often) or an opened hidden box (`lockbox.Box`) for this very
    account; else None."""
    if not egg or not row:
        return None
    if hasattr(egg, 'frames'):  # a box from lockbox: its frames are already drawn, one per clock frame
        if row.get('key') != egg.key:
            return None
        play = lambda frame, draw, box, f, span, active, s, plan, **_: frame.paste(
            egg.frames[min(f // SPEED, len(egg.frames) - 1)], box[:2])
        return play, egg.tier
    kind, _, key = egg.partition('@')
    if row.get('key') != key or kind not in ('reset', 'full'):
        return None
    from token_tv import events
    scene = events.event_scene(kind, row['provider'], row.get('full_streak', 1))
    return (lambda frame, draw, box, f, span, active, s, plan, **_: scene(frame, draw, box, f, s, plan)), 'common'


# A saved limit reset (Codex has them): a golden ticket in the header with how many are left; when the
# first one expires within three days it blinks and counts the days down instead.
TICKET = ('###########', '#######.###', '.#########.', '.######.##.', '.#########.', '#######.###', '###########')
GOLD, GOLD_DIM = (255, 200, 70), (110, 88, 40)
EXPIRING_DAYS = 3


def reset_ticket(row, now):
    """(count, days left) for the saved resets `row` holds, days only when the first expires soon; or None."""
    credits = row.get('reset_credits') or {}
    if not credits.get('count'):
        return None
    at = credits.get('expires_at')
    left = (at - now) / 86400 if at else None
    return credits['count'], max(0, math.ceil(left)) if left is not None and left <= EXPIRING_DAYS else None


def draw_ticket(draw, right, y, count, days, f):
    """The ticket and its count (or 'D-n', blinking) ending at `right`; returns the width it took."""
    text = str(count) if days is None else f'D-{days}'
    width = 2 * len(TICKET[0]) + 4 + (len(text) * 6 - 1) * 2
    on = True  # steady: something that blinks all day wears on the eye
    for yy, line in enumerate(TICKET):
        for xx, key in enumerate(line):
            if key == '#':
                x0 = right - width + 2 * xx
                draw.rectangle((x0, y + 2 * yy, x0 + 1, y + 2 * yy + 1), fill=GOLD if on else GOLD_DIM)
    pixel_text(draw, (right, y), text, scale=2, color=GOLD if days is None else WARN, align='right')
    return width


# A one-off's tier shows before the account name: rare a blue diamond, unique a purple one, legend a gold
# star, and a legend runs a rainbow round the stage as well.
BADGES = {'rare': ('...#...', '..###..', '.#####.', '#######', '.#####.', '..###..', '...#...'),
          'unique': ('...#...', '..###..', '.#####.', '#######', '.#####.', '..###..', '...#...'),
          'legend': ('...#...', '...#...', '#######', '.#####.', '..###..', '.##.##.', '#.....#')}
BADGE_INK = {'rare': (74, 163, 255), 'unique': (176, 124, 255), 'legend': (255, 197, 74)}
RAINBOW = ((255, 90, 82), (255, 167, 38), (255, 213, 79), (102, 187, 106), (66, 165, 245), (171, 71, 188))


# A cut-in at the start of a unique or legend one-off: the whole screen bursts into light, rays shooting out
# from a point, brightest along the diagonal, then they thin away and the scene shows through. Meant to
# catch the eye of someone working next to the clock.
BURST = {'unique': ((176, 124, 255), (214, 166, 255), (242, 228, 255), (236, 226, 255)),
         'legend': ((255, 170, 60), (255, 214, 107), (255, 244, 200), (255, 248, 230))}  # rays..., the flash
BURST_FRAMES = {'unique': 14, 'legend': 20}


def light_burst(draw, f, tier, night=False):
    """The cut-in: rays from the middle, a flash and a white core; at night only the coloured rays."""
    rays, flash = BURST[tier][:3], BURST[tier][3]
    n, cx, cy = BURST_FRAMES[tier], SIZE * .42, SIZE * .58
    grow = min(1, (f + 1) / 4)  # the rays reach the edges in four frames
    thin = 1 if f < n * .55 else max(0, (n - f) / (n * .45))  # then thin away
    if 2 <= f < n * .5 and not night:
        draw.rectangle((0, 0, SIZE - 1, SIZE - 1), fill=flash)
    for i in range(18):
        angle = math.radians(i * 20 + f * 1.5 + (7 if i % 2 else 0))
        diagonal = abs(math.cos(angle - math.radians(-40)))  # longer and wider toward the upper right and lower left
        length = SIZE * 1.6 * grow * (.45 + .55 * diagonal)
        width = math.radians((2 + 6 * diagonal) * thin)
        if width <= 0:
            continue
        tip = [(cx + math.cos(angle + side * width) * length, cy + math.sin(angle + side * width) * length) for side in (-1, 1)]
        draw.polygon([(cx, cy), *tip], fill=rays[i % len(rays)])
    core = round((10 + 26 * grow) * thin)
    if core > 0:
        draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=rays[2] if night else (255, 255, 255))


def draw_badge(draw, x, y, tier, f):
    """The tier mark at (x, y), 14 px square; it twinkles now and then. Returns its width and a gap."""
    for yy, line in enumerate(BADGES[tier]):
        for xx, key in enumerate(line):
            if key == '#':
                tone = (255, 255, 255) if f % 24 < 2 and (xx + yy) % 3 == 0 else BADGE_INK[tier]
                draw.rectangle((x + 2 * xx, y + 2 * yy, x + 2 * xx + 1, y + 2 * yy + 1), fill=tone)
    return 18


def rainbow_border(draw, top, bottom, f):
    """Coloured beads running round the stage edge."""
    edge = [(x, top) for x in range(0, 240, 4)] + [(236, y) for y in range(top, bottom, 4)] + \
           [(x, bottom - 4) for x in range(236, -1, -4)] + [(0, y) for y in range(bottom - 4, top - 1, -4)]
    for k, (x, y) in enumerate(edge):
        draw.rectangle((x, y, x + 3, y + 3), fill=RAINBOW[(k // 3 + f) % len(RAINBOW)])


READOUT_TOP = 171  # the numbers and the bar, under the stage
NIGHT_HOURS, NIGHT_GLOW = (23, 0, 1, 2, 3, 4, 5), .7  # the stage dims to 70% from 11 pm to 6 am

# Where a one-off's prop is left, on the stage: (centre x, bottom), clear of each pet's usual ground.
PROP_SPOT = {'claude': (108, 60), 'codex': (96, 67), 'grok': (58, 62), 'copilot': (26, 68), 'antigravity': (92, 60)}


@functools.lru_cache(maxsize=8)
def prop_art(png):
    return Image.open(io.BytesIO(base64.b64decode(png))).convert('RGBA')


def leave_prop(stage, row):
    """The prop a unique or legend one-off left behind (row['trace_prop'], from live.py), standing in the scene."""
    try:
        art = prop_art(row['trace_prop'])
    except (OSError, ValueError):
        return
    cx, bottom = PROP_SPOT.get(row['provider'], (108, 66))
    stage.paste(art, (cx - art.width // 2, bottom - art.height), art)


def scene_speed(row, eggy):
    """Scenes run at twice their pace, except Grok's jobs at work and Anti, which take the whole loop for one
    round."""
    if eggy:
        return SPEED
    if row['provider'] == 'antigravity':
        return 1  # Anti keeps the old arcade's own pace: a round of the maze in the whole loop
    return 1 if row['provider'] == 'grok' and row.get('active') else SPEED


def arcade_frames(snapshot, now, egg=None):
    shown = shown_rows(snapshot, now)
    # a one-off plays for its own account even when that account is not among the rows the clock cycles through
    every = [dict(row, key=key) for key, row in snapshot.get('accounts', {}).items()]
    eggy = [row for row in every if egg_scene(egg, row)]
    if eggy:  # an egg takes the whole loop
        shown = eggy[:1]
    starts = [k * FRAMES // len(shown) for k in range(len(shown))] + [FRAMES]
    plans = [scene_plan(row, now, (starts[k + 1] - starts[k]) / FPS) for k, row in enumerate(shown)]
    night = time.localtime(time.time() if now is None else now).tm_hour in NIGHT_HOURS
    frames, readouts = [], {}
    for f in range(FRAMES):
        index = max(k for k in range(len(shown)) if starts[k] <= f)
        row = shown[index]
        frame = Image.new('RGB', (SIZE, SIZE), PANEL)
        draw = ImageDraw.Draw(frame)
        used, period, old, left = info(row, now)
        oneoff = egg_scene(egg, row)
        scene, tier = oneoff if oneoff else (SCENES[row['provider']], None)
        # Every scene draws on its own half-size stage, then doubles: one 2 px grid for every sprite,
        # glyph and spark, and nothing spills over the header.
        stage = Image.new('RGB', (SIZE // 2, 71), PANEL)
        span = starts[index + 1] - starts[index]
        local = (f - starts[index]) * scene_speed(row, eggy)
        scene(stage, ImageDraw.Draw(stage), (0, 0, SIZE // 2, 71), local if eggy else local % span, span,
              bool(row.get('active')), 1, plans[index])
        if not oneoff and row.get('trace_prop'):
            leave_prop(stage, row)
        if night:  # late at night the stage glows lower, so nothing flares in a dark room
            stage = ImageEnhance.Brightness(stage).enhance(NIGHT_GLOW)
        frame.paste(stage.resize((SIZE, 142), Image.Resampling.NEAREST), (0, 28))
        if tier == 'legend':
            rainbow_border(draw, 28, 170, f)
        both = len(shown_windows(row, 1)) == 2
        note = ('OLD' if old else '') if both else period + (' OLD' if old else '')
        room = 220 - ((len(note) * 6 - 1) * 2 + 8 if note else 0)
        pixel_text(draw, (230, 8), note, scale=2, color=WARN if old else MUTED, align='right')
        ticket = reset_ticket(row, time.time() if now is None else now)
        if ticket:
            room -= draw_ticket(draw, 230 - (220 - room), 8, *ticket, f) + 8
        label_x = 10 + (draw_badge(draw, 10, 8, tier, f) if tier in BADGES else 0)  # while a one-off plays
        pixel_text(draw, (label_x, 8), fit_pixel(label_of(row), 2, room - (label_x - 10)), scale=2, color=TEXT)
        if index not in readouts:  # the readout does not move: drawn once per account, pasted on every frame
            wins = shown_windows(row, 1)
            canvas = Image.new('RGB', (SIZE, SIZE), PANEL)
            if len(wins) == 2:  # one account at a time has room for both windows: 5H above WEEK
                draw_readout(canvas, ImageDraw.Draw(canvas),
                             [(p, u, l, o) for u, p, o, l in (info(row, now, value) for value in wins)])
            else:
                draw_readout(canvas, ImageDraw.Draw(canvas), [(period, used, left, old)])
            readouts[index] = canvas.crop((0, READOUT_TOP, SIZE, SIZE))
        frame.paste(readouts[index], (0, READOUT_TOP))
        if len(shown) > 1:
            for k in range(len(shown)):
                bx = 120 - len(shown) * 4 + k * 8
                draw.rectangle((bx, 175, bx + 3, 178), fill=TEXT if k == index else TRACK)
        if tier in BURST and getattr(egg, 'intro', True) and f < BURST_FRAMES[tier]:
            light_burst(draw, f, tier, night)  # the cut-in over the whole screen
        frames.append(frame)
    return frames


def encode(frames, scale=1):
    if scale != 1:
        frames = [f.resize((SIZE * scale, SIZE * scale), Image.Resampling.NEAREST) for f in frames]
    indexed = gif.indexed(frames, 'Arcade')
    # Every frame the same length: a mix of 80 and 90 ms read as a stutter on the clock.
    data = gif.encode(indexed, [FRAME_MS] * len(indexed))
    if len(data) > BUDGET and scale == 1:  # a rare busy loop: every other frame, the same loop, still uploads
        data = gif.encode(indexed[::2], [2 * FRAME_MS] * len(indexed[::2]))
    return data


def gif_seconds(image):
    """How long one loop of a GIF lasts."""
    loop = Image.open(io.BytesIO(image))
    total = 0
    for n in range(getattr(loop, 'n_frames', 1)):
        loop.seek(n)
        total += loop.info.get('duration', 0)
    return total / 1000


def render_arcade(snapshot, now=None, scale=1, egg=None):
    return encode(arcade_frames(snapshot, now, egg), scale)
