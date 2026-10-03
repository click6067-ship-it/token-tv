"""Space: the three mascots drift in glass helmets across a dotted night sky.

The face is an animated 240×240 GIF for the clock's photo album (stock firmware plays
GIFs up to 240×240). The drifting is decorative; each bot carries its provider's used %
and a ten-cell gauge. A few events (dash, hop, spin, sparkles, shooting star, huddle) start
at seeded random times. The seed follows the shown values and a 30-minute bucket, so equal
readings give identical bytes (no re-upload) while the choreography still changes over time.
"""
import functools
import hashlib
import io
import math
import random
import time

from PIL import Image, ImageDraw

from token_tv.display import ASSETS, overview_rows, pixel_text, primary_window

SIZE = 240
FPS = 10
FRAMES = 10 * FPS  # one 10-second loop, matching the album's photo interval
BG = (8, 12, 30)
GLASS = (22, 30, 64)
RIM = (150, 182, 232)
SHINE = (236, 244, 255)
TAG = (255, 243, 214)
DIM = (128, 140, 178)
EMPTY = (38, 48, 90)
SPARK = (255, 216, 107)
MOON = (233, 226, 200)
GROK_GLASS = (64, 78, 140)
STARS = ((92, 104, 150), (170, 182, 220), (255, 255, 255))
# Used-quota bands (below 50, 50–79, 80–89, 90–100): start and tip of each cell ramp.
BANDS = (((42, 168, 74), (94, 224, 106)), ((143, 201, 58), (211, 232, 74)),
         ((255, 122, 31), (255, 171, 61)), ((214, 43, 60), (255, 90, 95)))
RADIUS = 20
BOX = (50, 78)  # bubble plus tag footprint used for spacing
EVENTS = ('dash', 'hop', 'spin', 'sparkle', 'shooting_star', 'huddle')


@functools.lru_cache(maxsize=None)
def sprite(provider):
    """Project mascot with hard alpha and at most eight colours, for a compact GIF."""
    image = Image.open(ASSETS / f'{provider}-pixel.png').convert('RGBA')
    image = image.crop(image.getbbox())
    alpha = image.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
    flat = Image.new('RGB', image.size)
    flat.paste(image.convert('RGB'), mask=alpha)
    flat = flat.quantize(colors=8, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert('RGB')
    out = Image.new('RGBA', image.size, (0, 0, 0, 0))
    out.paste(flat, mask=alpha)
    return out


@functools.lru_cache(maxsize=1)
def backdrop():
    """Static sky: dotted stars and a dotted crescent moon; returns (image, twinkling stars)."""
    rnd = random.Random(7)
    image = Image.new('RGB', (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(image)
    for _ in range(46):
        x, y = rnd.randrange(SIZE), rnd.randrange(SIZE)
        draw.point((x, y), fill=rnd.choice(STARS[:2]))
    for x, y in ((34, 22), (206, 128), (58, 168), (150, 206)):
        draw.point([(x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)], fill=STARS[1])
    cx, cy, r = 196, 34, 15
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= r * r
            cut = (x - cx - 7) ** 2 + (y - cy + 3) ** 2 <= (r - 2) ** 2
            if inside and not cut and (x + y) % 2 == 0:
                draw.point((x, y), fill=MOON)
    twinkles = [(rnd.randrange(SIZE), rnd.randrange(SIZE), rnd.choice((10, 20, 25, 50)), rnd.randrange(50))
                for _ in range(6)]
    return image, twinkles


def readings(snapshot):
    rows = []
    for row in overview_rows(snapshot):
        value = primary_window(row)
        used = max(0, min(100, value['used_percent'])) if value else None
        rows.append((row['provider'], used, bool(value) and row['status'] != 'ok'))
    return rows


def seed_for(rows, now=None):
    bucket = int((time.time() if now is None else now) // 1800)
    key = repr([(p, None if u is None else round(u), old) for p, u, old in rows]) + f'|{bucket}'
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)


def ease(p):
    return p * p * (3 - 2 * p)


def schedule(rnd):
    """Two or three events at irregular, non-overlapping times inside the loop."""
    events, start = [], rnd.uniform(0.6, 2.5)
    for kind in rnd.sample(EVENTS, rnd.choice((2, 3))):
        duration = {'dash': 1.6, 'hop': 0.9, 'spin': 0.9, 'sparkle': 1.3, 'shooting_star': 1.0, 'huddle': 2.2}[kind]
        if start + duration > 9.6:
            break
        events.append({'kind': kind, 'start': start, 'end': start + duration, 'bot': rnd.randrange(3),
                       'y': rnd.uniform(20, 120), 'angles': [rnd.uniform(0, 2 * math.pi) for _ in range(6)]})
        start += duration + rnd.uniform(0.9, 3.2)
    return events


def positions(t, paths, events):
    """Bubble centres at loop time t (seconds): periodic drift, events, soft separation."""
    points = []
    for i, (ax, ay, fx, fy, px, py, cx, cy) in enumerate(paths):
        x = cx + ax * math.sin(2 * math.pi * fx * t / 10 + px)
        y = cy + ay * math.sin(2 * math.pi * fy * t / 10 + py) + 2 * math.sin(2 * math.pi * 3 * t / 10 + i)
        points.append([x, y])
    for event in events:
        if not event['start'] <= t < event['end']:
            continue
        p = (t - event['start']) / (event['end'] - event['start'])
        if event['kind'] == 'huddle':
            pull = math.sin(math.pi * ease(p)) * 0.8
            for point in points:
                point[0] += (120 - point[0]) * pull
                point[1] += (106 - point[1]) * pull
        elif event['kind'] == 'hop':
            points[event['bot']][1] -= 15 * abs(math.sin(2 * math.pi * p))
    for _ in range(10):  # a bubble and its tag form one box; resolve box overlaps
        for a in range(3):
            for b in range(a + 1, 3):
                dx, dy = points[b][0] - points[a][0], points[b][1] - points[a][1]
                ox, oy = BOX[0] - abs(dx), BOX[1] - abs(dy)
                if ox > 0 and oy > 0:
                    axis, overlap, d = (0, ox, dx) if ox < oy else (1, oy, dy)
                    shift = overlap / 2 * (1 if d >= 0 else -1)
                    points[a][axis] -= shift
                    points[b][axis] += shift
        for point in points:
            point[0] = min(max(point[0], 26), 214)
            point[1] = min(max(point[1], 24), 182)
    for event in events:  # the dash wraps around the screen and lands back on its path
        if event['kind'] == 'dash' and event['start'] <= t < event['end']:
            p = (t - event['start']) / (event['end'] - event['start'])
            point = points[event['bot']]
            point[0] = (point[0] + 300 * ease(p) + 30) % 300 - 30
    return points


def bubble(frame, draw, provider, x, y, mirrored):
    # The black Grok bot needs lighter glass to stay visible on the night sky.
    draw.ellipse((x - RADIUS, y - RADIUS, x + RADIUS, y + RADIUS), fill=GROK_GLASS if provider == 'grok' else GLASS, outline=RIM)
    art = sprite(provider)
    if mirrored:
        art = art.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    frame.paste(art, (x - art.width // 2, y - art.height // 2), art)
    draw.arc((x - RADIUS + 4, y - RADIUS + 4, x + RADIUS - 4, y + RADIUS - 4), 200, 250, fill=SHINE)


def tag(draw, x, y, used, old):
    text = '--' if used is None else f'{round(used)}%'
    width = (len(text) * 6 - 1) * 2
    pixel_text(draw, (x - width // 2, y + RADIUS + 5), text, scale=2, color=DIM if old else TAG)
    left, top = x - 19, y + RADIUS + 23
    band = BANDS[0 if (used or 0) < 50 else 1 if used < 80 else 2 if used < 90 else 3]
    lit = 0 if used is None else max(1, math.ceil(used / 10)) if used > 0 else 0
    for cell in range(10):
        start, tip = band
        k = cell / 9
        color = tuple(round(start[i] + (tip[i] - start[i]) * k) for i in range(3)) if cell < lit else EMPTY
        draw.rectangle((left + cell * 4, top, left + cell * 4 + 2, top + 2), fill=color)
    if old:
        pixel_text(draw, (x - 8, top + 5), 'OLD', color=DIM)


def render_frames(snapshot, now=None):
    rows = readings(snapshot)
    rnd = random.Random(seed_for(rows, now))
    paths = [(rnd.uniform(60, 82), rnd.uniform(24, 40), rnd.choice((1, 2)), 1,
              rnd.uniform(0, 6.3), rnd.uniform(0, 6.3), 120, cy) for cy in (54, 110, 160)]
    events = schedule(rnd)
    sky, twinkles = backdrop()
    frames = []
    for f in range(FRAMES):
        t = f / FPS
        frame = sky.copy()
        draw = ImageDraw.Draw(frame)
        for x, y, period, offset in twinkles:
            lit = ((f + offset) // (period // 2)) % 2 == 0
            draw.point((x, y), fill=STARS[2] if lit else STARS[0])
        for event in events:
            if event['kind'] == 'shooting_star' and event['start'] <= t < event['end']:
                p = (t - event['start']) / (event['end'] - event['start'])
                hx, hy = -20 + 290 * p, event['y'] + 70 * p
                for k, color in enumerate((STARS[2], STARS[1], STARS[0])):
                    draw.line((hx - 7 * k, hy - 1.7 * k, hx - 7 * (k + 1), hy - 1.7 * (k + 1)), fill=color)
        points = positions(t, paths, events)
        order = sorted(range(3), key=lambda i: points[i][1])
        for i in order:
            provider, used, old = rows[i]
            x, y = round(points[i][0]), round(points[i][1])
            mirrored = any(e['kind'] == 'spin' and e['bot'] == i and e['start'] <= t < e['end']
                           and int((t - e['start']) / (e['end'] - e['start']) * 6) % 2 == 1 for e in events)
            bubble(frame, draw, provider, x, y, mirrored)
            tag(draw, x, y, used, old)
            for event in events:
                if event['kind'] == 'sparkle' and event['bot'] == i and event['start'] <= t < event['end']:
                    p = (t - event['start']) / (event['end'] - event['start'])
                    for k, angle in enumerate(event['angles']):
                        phase = p * 3 - k * 0.3
                        if 0 < phase < 1:
                            size = 2 if 0.3 < phase < 0.7 else 1
                            sx = round(x + math.cos(angle) * (RADIUS + 6 + 6 * phase))
                            sy = round(y + math.sin(angle) * (RADIUS + 6 + 6 * phase))
                            draw.line((sx - size, sy, sx + size, sy), fill=SPARK)
                            draw.line((sx, sy - size, sx, sy + size), fill=SPARK)
        frames.append(frame)
    return frames


def render_space(snapshot, now=None, scale=1):
    frames = render_frames(snapshot, now)
    if scale != 1:  # crisp enlargements for README and posts
        frames = [f.resize((SIZE * scale, SIZE * scale), Image.Resampling.NEAREST) for f in frames]
    colours = set()
    for frame in frames:
        colours.update(c for _, c in frame.getcolors(maxcolors=frame.width * frame.height))
    palette = sorted(colours)
    if len(palette) > 256:
        raise ValueError('Space face needs at most 256 colours')
    reference = Image.new('P', (1, 1))
    reference.putpalette([v for c in palette for v in c] + [0] * (768 - 3 * len(palette)))
    indexed = [f.quantize(palette=reference, dither=Image.Dither.NONE) for f in frames]
    buffer = io.BytesIO()
    indexed[0].save(buffer, format='GIF', save_all=True, append_images=indexed[1:],
                    duration=1000 // FPS, loop=0, disposal=1, optimize=False)
    return buffer.getvalue()
