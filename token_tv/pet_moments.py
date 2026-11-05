"""The pets' phase-2 moments on the Arcade stage, as the owner approved them (drafts w1-w12, 2026-11-01): the break
after an hour of work (e6: drinking water or stretching) for all five pets, and Clawd petted or given a snack (e5:
/tokentv pet, /tokentv snack).

Each plays once through its pet's turn, one scene frame a frame (a lone pet's loop: 60 pictures, about 8.5 s on an
SD_PRO), and the next loop is the pet's usual one. Everything is drawn on the scene's 120 x 71 stage, which Arcade
doubles. The props look the same for every pet (one glass of water, one sparkle); each pet drinks and stretches its own
way: Clawd tips the glass with its hand, the Codex cloud draws the water up like rain falling backwards, Grok and
Copilot sip through a straw, and Anti floats over its glass with the straw up through its arch. A stretch is the same
steps for all five (up tall with eyes shut, a lean each way, a squash, a sparkle); the leans are shears, which keep the
pixel art crisp where a turn blurred it. Clawd's poses are its own frames from Clawd's Quest; only the props, a few
shut-eye pixels and the leans are new.

arcade.py draws them: claude_moment for Clawd (CLAWD_MOMENTS), and in place of the other pets' scenes while the break
plays (SCENE_MOMENTS).
"""
import functools
import math

from PIL import Image

from token_tv import arcade
from token_tv.arcade import paste


# --- helpers ----------------------------------------------------------------------------------------------------------

def sprite(rows, ink):
    """A small sprite from rows of keys; each key in `ink` is a colour, any other key is clear."""
    art = Image.new('RGBA', (max(map(len, rows)), len(rows)))
    for y, line in enumerate(rows):
        for x, key in enumerate(line):
            if key in ink:
                art.putpixel((x, y), tuple(ink[key]) + (255,))
    return art


def step_of(p, marks):
    """The step of a moment at progress `p` (0..1) and how far through it (0..1); `marks` are (name, end)."""
    start = 0.0
    for name, end in marks:
        if p < end:
            return name, (p - start) / (end - start)
        start = end
    return marks[-1][0], 1.0


def ease(q):
    return q * q * (3 - 2 * q)


@functools.lru_cache(maxsize=None)
def leaning(build, args, pivot, dx):
    """build(*args) leaning `dx` pixels at its top: its feet (the pivot's row) stay and each row above moves in
    proportion to its height, a shear that keeps pixel art crisp where a turn would blur it. Returns the art and
    where the pivot is in it."""
    art = build(*args)
    if not dx:
        return art, pivot
    top, bottom = art.getbbox()[1], pivot[1]
    out = Image.new('RGBA', (art.width + abs(dx), art.height))
    for y in range(art.height):
        k = max(0.0, min(1.0, (bottom - 1 - y) / max(1, bottom - 1 - top)))
        row = art.crop((0, y, art.width, y + 1))
        out.paste(row, (round(dx * k) + (abs(dx) if dx < 0 else 0), y), row)
    if art.info.get('pet'):  # a leaning pet is still the pet (its season's hat: seasons.py)
        out.info['pet'] = art.info['pet']
    return out, (pivot[0] + (abs(dx) if dx < 0 else 0), pivot[1])


def put_leaning(frame, build, args, pivot, dx, x, y):
    """Paste build(*args), leaning `dx` at its top, with its pivot at (x, y)."""
    art, (px, py) = leaning(build, args, pivot, dx)
    paste(frame, art, x - px, y - py)


@functools.lru_cache(maxsize=None)
def taller(build, args, rows):
    """build(*args) drawn `rows` pixels taller (rows repeated evenly, the width kept, so eyes keep their shape);
    fewer rows and a column more each side for rows < 0: a squash."""
    art = build(*args)
    if rows > 0:
        return art.resize((art.width, art.height + rows), Image.Resampling.NEAREST)
    if rows < 0:
        return art.resize((art.width - rows, art.height + rows), Image.Resampling.NEAREST)
    return art


def sway(step, q):
    """How far the top leans in a stretch's lean steps: two pixels, then three, then two, each way."""
    if step not in ('left', 'right'):
        return 0
    return (2 if q < .2 or q >= .8 else 3) * (-1 if step == 'left' else 1)


STRETCH_MARK = (236, 240, 255)


def stretch_marks(draw, cx, top, half, q):
    """Two short strokes either side of a stretching pet's top, flickering: the effort of a good stretch."""
    if int(q * 6) % 2:
        return
    for side in (-1, 1):
        x = cx + side * (half + 2)
        draw.line((x, top + 1, x + side, top - 1), fill=STRETCH_MARK)


# --- the props, the same for every pet --------------------------------------------------------------------------------

GLASS_EDGE, GLASS_SHINE, GLASS_AIR = (196, 214, 238), (255, 255, 255), (66, 84, 110)
WATER, WATER_TOP = (52, 140, 255), (150, 204, 255)
GLASS = ('E.....E', 'ES....E', 'ES....E', 'E.....E', 'E.....E', 'E.....E', 'E.....E', '.EEEEE.')  # 7 x 8 tumbler
GLASS_LEVELS = 5  # water fills rows 2-6
LAST_SIP = 1  # a row of water is left at the end: an empty glass read as a letter U


@functools.lru_cache(maxsize=None)
def glass_art(level):
    """The glass upright with `level` rows of water (0 to 5), the top row lighter (the surface), a glint down its
    side, and the air above the water a faint glass tint."""
    rows = [list(r) for r in GLASS]
    for v in range(7):
        for u in range(1, 6):
            if rows[v][u] == '.':
                k = 6 - v  # rows of water from the bottom
                rows[v][u] = 'T' if k == level - 1 else 'W' if k < level else 'A'
    return sprite([''.join(r) for r in rows], {'E': GLASS_EDGE, 'S': GLASS_SHINE, 'W': WATER, 'T': WATER_TOP,
                                               'A': GLASS_AIR})


@functools.lru_cache(maxsize=None)
def glass_tipped(degrees, water):
    """The glass turned `degrees` anticlockwise (RotSprite for its outline), with `water` (0..1) of a full glass lying
    level at its lowest side, as water does: past 90 degrees it sits against the rim. Returns the art and where the
    middle of its rim is in it."""
    edge = sprite(GLASS, {'E': GLASS_EDGE})
    art = arcade.rotsprite(edge, -degrees)
    w, h = art.size
    a = math.radians(degrees)
    inside = []  # the turned interior: pixels whose middle maps back inside the glass (u 1-5, v 0-6)
    for y in range(h):
        for x in range(w):
            dx, dy = x + .5 - w / 2, y + .5 - h / 2
            u = dx * math.cos(a) - dy * math.sin(a) + 3.5  # undo an anticlockwise turn on screen (y down)
            v = dx * math.sin(a) + dy * math.cos(a) + 4
            if 1 <= u < 6 and 0 <= v < 7 and not art.getpixel((x, y))[3]:
                inside.append((x, y))
    wet = round(water * 25 * len(inside) / 35)  # a full glass holds 5 of its 7 rows
    inside.sort(key=lambda p: -p[1])
    surface = inside[wet - 1][1] if wet else None
    for n, (x, y) in enumerate(inside):
        art.putpixel((x, y), (WATER_TOP if y == surface else WATER) + (255,) if n < wet else GLASS_AIR + (255,))
    rim = (3.5 - 3.5, -4.0)  # the rim's middle from the glass's middle, turned
    rx = rim[0] * math.cos(a) + rim[1] * math.sin(a)
    ry = -rim[0] * math.sin(a) + rim[1] * math.cos(a)
    return art, (round(w / 2 + rx), round(h / 2 + ry))


def glass(frame, x, bottom, level):
    """The glass standing with its left edge at x and its base on the row above `bottom`."""
    paste(frame, glass_art(level), x, bottom - len(GLASS))


def sip_level(q):
    """The water left at `q` (0..1) through sipping with a straw: full, then a row less at a time, down to the last."""
    return max(LAST_SIP, GLASS_LEVELS - int(q * (GLASS_LEVELS - LAST_SIP + 1)))


STRAW, STRAW_STRIPE = (250, 250, 252), (240, 84, 100)


def straw(draw, points):
    """A bendy straw along `points`, white with red stripes, one pixel wide."""
    n = 0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = max(abs(x1 - x0), abs(y1 - y0), 1)
        for k in range(length + (1 if (x1, y1) == points[-1] else 0)):
            px_, py_ = round(x0 + (x1 - x0) * k / length), round(y0 + (y1 - y0) * k / length)
            draw.point((px_, py_), fill=STRAW_STRIPE if (n // 2) % 2 else STRAW)
            n += 1


SPARK, SPARK_CORE = (255, 232, 140), (255, 255, 255)


def sparkle(draw, cx, cy, size):
    """A twinkle: a small plus (size 1) or a long one (size 2) with a white heart."""
    if size <= 0:
        return
    for k in range(1, size + 1):
        for dx, dy in ((k, 0), (-k, 0), (0, k), (0, -k)):
            draw.point((cx + dx, cy + dy), fill=SPARK)
    draw.point((cx, cy), fill=SPARK_CORE)


def twinkle(q):
    """Two twinkles over the last step: 1, 2, 2, 1, gone, 1, 2, 1, gone."""
    return (1, 2, 2, 1, 0, 1, 2, 1, 0)[min(8, int(q * 9))]


HEART_INK, HEART_SHINE = (255, 92, 136), (255, 200, 214)
HEART_BIG = sprite(('.H.H.', 'HSHHH', 'HHHHH', '.HHH.', '..H..'), {'H': HEART_INK, 'S': HEART_SHINE})
HEART_SMALL = sprite(('H.H', 'HHH', '.H.'), {'H': HEART_INK})

COOKIE_INK = {'C': (226, 172, 102), 'K': (112, 66, 40)}
COOKIE = ('..CCC..', '.CCKCC.', 'CKCCCCC', 'CCCCKCC', 'CCKCCCC', '.CCCCK.', '..CCC..')  # 7 x 7, chips in it
BITES = (((-1.5, 2.0), 2.6), ((-1.0, 5.0), 2.6), ((2.0, 3.0), 3.3))  # each bite's middle and size, from its left


@functools.lru_cache(maxsize=None)
def cookie_art(bites):
    """The cookie after `bites` bites taken from its left, the side its eater is on (0: whole; 4: gone)."""
    rows = [list(r) for r in COOKIE]
    for (bx, by), r in BITES[:bites]:
        for y, row in enumerate(rows):
            for x in range(len(row)):
                if (x + .5 - bx) ** 2 + (y + .5 - by) ** 2 < r * r:
                    row[x] = '.'
    if bites >= 4:
        rows = [['.'] * 7 for _ in rows]
    return sprite([''.join(r) for r in rows], COOKIE_INK)


# --- Clawd ------------------------------------------------------------------------------------------------------------

BODY, DARK, THOUGHT = '#d97757', '#141413', '#699acb'


@functools.lru_cache(maxsize=None)
def clawd_art(name, index, eyes=None):
    """One of Clawd's own frames at one pixel a pixel, without Thinking's thought bubble; eyes='shut' closes each
    open eye the game's way (a line three pixels long on the eye's lowest row, reaching a pixel toward the middle).
    Those eye pixels are the only ones redrawn."""
    sheet = arcade.clawd_data()[name]
    w, h = sheet['w'], sheet['h']
    keys = [c.lower() for c in sheet['palette']]
    palette = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in keys]
    values = [255 if v != 255 and keys[v] == THOUGHT else v for v in arcade.clawd_frames(name)[index]]
    if eyes == 'shut' and DARK in keys and BODY in keys:
        dark, body = keys.index(DARK), keys.index(BODY)
        spots = [(i % w, i // w) for i, v in enumerate(values) if v == dark]
        for left_eye in (True, False):
            eye = [(x, y) for x, y in spots if (x < w / 2) == left_eye]
            if not eye:
                continue
            for x, y in eye:
                values[y * w + x] = body
            low, xs = max(y for _, y in eye), [x for x, _ in eye]
            for x in range(min(xs) - (not left_eye), max(xs) + 1 + left_eye):
                values[low * w + x] = dark
    art = Image.new('RGBA', (w, h))
    art.putdata([(0, 0, 0, 0) if v == 255 else palette[v] + (255,) for v in values])
    return arcade.tag(art, 'claude')


def clawd_pivot(name, index, eyes=None, grounded=False):
    """Where Clawd's frame stands: the bottom middle of its body box, as place_clawd stands it; `grounded` stands
    the frame's lowest pixel on the ground instead (a frame from mid-jump, set down)."""
    x, y, w, h = arcade.clawd_data()[name]['a0']
    bottom = clawd_art(name, index, eyes).getbbox()[3] if grounded else y + h
    return round(x + w / 2), bottom


def put_clawd(frame, name, index, foot_x, foot_y, eyes=None, grounded=False, lean=0, lift=0):
    pivot = clawd_pivot(name, index, eyes, grounded)
    put_leaning(frame, clawd_art, (name, index, eyes), pivot, lean, foot_x, foot_y - lift)


DRINK = (('stand', .07), ('lift', .15), ('sip', .66), ('lower', .73), ('ahh', 1.0))
STRETCH = (('stand', .07), ('rise', .13), ('up', .24), ('left', .40), ('right', .56), ('back', .63), ('settle', .73),
           ('ahh', 1.0))
HAND = (10, -14)  # Thinking's hand by its face, from where Clawd stands (the frames themselves are Clawd's own)


def clawd_ahh(frame, draw, foot_x, foot_y, q):
    """Refreshed: the bow's proud pose (eyes ^ ^), a squash first, and a sparkle twinkling twice by its head."""
    put_clawd(frame, 'Excited', 3 if q < .08 else 6, foot_x, foot_y)
    sparkle(draw, foot_x + 12, foot_y - 19, twinkle(q))


def clawd_drink(frame, draw, foot_x, foot_y, f, span):
    """The glass on the ground by Clawd, then held up by its face (Thinking's hand, its own frame); it drinks with its
    eyes shut, tipping the glass further as it empties, as one does; it sets the glass down and is refreshed."""
    step, q = step_of(f / span, DRINK)
    hx, hy = foot_x + HAND[0], foot_y + HAND[1]
    if step == 'stand':
        glass(frame, foot_x + 15, foot_y, GLASS_LEVELS)
        put_clawd(frame, 'LookingAround', 0, foot_x, foot_y)
    elif step in ('lift', 'lower'):  # held up by its face: full on the way up, nearly empty on the way down
        glass(frame, hx - 1, hy + 3, GLASS_LEVELS if step == 'lift' else LAST_SIP)
        put_clawd(frame, 'Thinking', 4, foot_x, foot_y)
    elif step == 'sip':  # the rim at its face, the glass's bottom rising as the water goes
        put_clawd(frame, 'Thinking', 4, foot_x, foot_y)
        art, (rx, ry) = glass_tipped(round(60 + 60 * q, -1), round(1 - .8 * q, 1))
        paste(frame, art, hx - 1 - rx, hy - 1 - ry)
    else:
        glass(frame, foot_x + 15, foot_y, LAST_SIP)  # set down
        clawd_ahh(frame, draw, foot_x, foot_y, q)


def clawd_stretch(frame, draw, foot_x, foot_y, f, span):
    """Arms up (the game's own jump frames, set down on the ground), eyes shut, a lean each way, then the landing
    squash and a sparkle. Distinct from the rest flow's sway, which Clawd does every few minutes anyway."""
    step, q = step_of(f / span, STRETCH)
    if step == 'stand':
        put_clawd(frame, 'LookingAround', 0, foot_x, foot_y)
    elif step == 'rise':
        put_clawd(frame, 'Jumping', 5, foot_x, foot_y, grounded=True)
    elif step in ('up', 'back'):
        put_clawd(frame, 'Jumping', 7, foot_x, foot_y, 'shut', grounded=True, lift=1 if step == 'up' and q > .4 else 0)
    elif step in ('left', 'right'):
        put_clawd(frame, 'Jumping', 7, foot_x, foot_y, 'shut', grounded=True, lean=sway(step, q))
    elif step == 'settle':
        put_clawd(frame, 'Jumping', 13 if q < .3 else 14 if q < .6 else 15, foot_x, foot_y, grounded=True)
    else:
        clawd_ahh(frame, draw, foot_x, foot_y, q)


PET = (('stand', .06), ('squash', .12), ('happy', .92), ('back', 1.0))
HEARTS = ((.12, -3), (.30, 4), (.48, -1), (.62, 5))  # when each heart sets off (progress), and its drift


def hearts(frame, foot_x, foot_y, p, life=.32, rise=18):
    """Hearts floating up from Clawd's head, each big at first, small near the top, then gone."""
    for start, drift in HEARTS:
        a = (p - start) / life
        if 0 <= a < 1:
            art = HEART_BIG if a < .6 else HEART_SMALL
            x = foot_x + 2 + drift + round(math.sin(a * math.pi * 2) * 1.5)
            y = foot_y - 22 - round(rise * a)
            paste(frame, art, x - art.width // 2, y - art.height)


def clawd_pet(frame, draw, foot_x, foot_y, f, span):
    """Petted: a squash (the game's Excited), eyes ^ ^ and a happy wiggle, hearts floating up."""
    p = f / span
    step, q = step_of(p, PET)
    if step == 'stand':
        put_clawd(frame, 'LookingAround', 0, foot_x, foot_y)
    elif step == 'squash':
        put_clawd(frame, 'Excited', 3 if q < .5 else 4, foot_x, foot_y)
    elif step == 'happy':
        put_clawd(frame, 'Excited', 5 + int(q * 32) % 16, foot_x, foot_y)
    else:
        put_clawd(frame, 'Excited', 21 if q < .5 else 22, foot_x, foot_y)
    hearts(frame, foot_x, foot_y, p)


SNACK = (('drop', .12), ('catch', .2), ('munch', .74), ('ahh', 1.0))
CRUMB = (190, 140, 84)


def clawd_snack(frame, draw, foot_x, foot_y, f, span):
    """A cookie drops in from above (the treat from /tokentv snack), Clawd catches it by its face (Thinking's hand,
    its own frame), takes it in four bites with a chew each and crumbs falling, then ^ ^."""
    step, q = step_of(f / span, SNACK)
    hx, hy = foot_x + HAND[0], foot_y + HAND[1]
    cookie_at = (hx - 1, hy - 5)  # its top left, held by the face
    if step == 'drop':
        put_clawd(frame, 'LookingAround', 0, foot_x, foot_y)
        paste(frame, cookie_art(0), cookie_at[0], round(-8 + (cookie_at[1] + 8) * q * q))
    elif step == 'catch':
        put_clawd(frame, 'Thinking', 4, foot_x, foot_y)
        paste(frame, cookie_art(0), *cookie_at)
    elif step == 'munch':
        bites = min(4, int(q * 4.4))
        chew = (q * 4.4) % 1  # within a bite: to the face, a bite, back with a chew
        near = 1 if chew < .3 else 0
        put_clawd(frame, 'Thinking', 4, foot_x, foot_y, lift=1 if .4 <= chew < .6 else 0)
        paste(frame, cookie_art(bites), cookie_at[0] - near, cookie_at[1])
        if bites and chew >= .3:  # crumbs from the bite, falling to the ground
            fall = (chew - .3) / .7
            for k, dx in enumerate((0, 2, -1)):
                cy = hy + round((foot_y - hy) * min(1, fall * (1 + .35 * k)))
                if cy < foot_y:
                    draw.point((hx + dx, cy), fill=CRUMB)
    else:
        clawd_ahh(frame, draw, foot_x, foot_y, q)


CLAWD_MOMENTS = {'drink': clawd_drink, 'stretch': clawd_stretch, 'pet': clawd_pet, 'snack': clawd_snack}


# --- Codex ------------------------------------------------------------------------------------------------------------

def codex_garden(frame, draw, box, f, s, plan):
    """The garden as codex_scene draws it at rest: the flowers are its gauge, so they stay."""
    x, y, w, h = box
    ground = arcade.garden_backdrop(draw, box, f, s)
    used = plan.get('used') if isinstance(plan, dict) else None
    xs = [x + round(w * (i + .5) / 5) for i in range(5)]
    bloomed = 0 if used is None else min(5, int(used * 5 // 100))
    if s == 1 and isinstance(plan, dict) and plan.get('label'):
        arcade.gauge_label(draw, x + 1, y + 1, plan['label'])
    if used is not None:
        for i, fx in enumerate(xs):
            if i < bloomed:
                arcade.flower(draw, fx, ground, s, 1, s * (1 if (f // 30 + i) % 2 else 0))
            else:
                draw.rectangle((fx - 2 * s, ground - s, fx + s - 1, ground - 1), fill=arcade.PLOT)
        if bloomed < 5:
            arcade.flower(draw, xs[bloomed], ground, s, .15 + .66 * (used % 20) / 20)
    return ground


def codex_drink(frame, draw, box, f, span, s, plan):
    """The cloud drifts over its glass and draws the water up like rain falling backwards, eyes shut, plumping up a
    little as it fills; then it floats home grinning."""
    x, y, w, h = box
    ground = codex_garden(frame, draw, box, f, s, plan)
    step, q = step_of(f / span, DRINK)
    cw, ch = arcade.codex_art(s).size
    home = (x + round(w * .5), y + max(2, round(h * .05)) + ch // 2)
    gx = x + 72  # between the third and fourth flowers
    over = (gx, home[1] + 13)
    level, eye, mouth, squash = GLASS_LEVELS, 'open', 'long', 0
    if step == 'stand':
        cx, mid = home
    elif step == 'lift':
        cx, mid = (round(a + (b - a) * ease(q)) for a, b in zip(home, over))
    elif step == 'sip':
        cx, mid = over
        level, eye, mouth = sip_level(q), 'closed', 'short' if (f // 8) % 2 else 'long'
        squash = 1 if q > .55 else 0
    elif step == 'lower':
        cx, mid = (round(b + (a - b) * ease(q)) for a, b in zip(home, over))
        level, squash = LAST_SIP, 1
    else:
        cx, mid = home
        level, eye, mouth = LAST_SIP, 'happy', 'smile'
    glass(frame, gx - 3, ground, level)
    cloud = arcade.codex_art(s, eye, mouth, squash)
    if step == 'sip':  # drops rising from the glass into the cloud's underside
        top, bottom = mid + cloud.height // 2 - 3, ground - len(GLASS) + 3
        for k, dx in enumerate((-2, 1, -1, 2)):
            t = ((f / 2 + k * 2.6) % 10) / 10
            dy = bottom - round((bottom - top) * t)
            if top < dy <= bottom:
                draw.rectangle((gx + dx, dy - 1, gx + dx, dy), fill=WATER_TOP if k % 2 else WATER)
    paste(frame, cloud, cx - cloud.width / 2, mid - cloud.height / 2)
    if step == 'ahh':
        sparkle(draw, cx + cw // 2 + 2, mid - ch // 2 + 1, twinkle(q))


def codex_stretch(frame, draw, box, f, span, s, plan):
    """Drawn up tall with a yawn, a lean each way, a wide wobble back, and a grin."""
    x, y, w, h = box
    codex_garden(frame, draw, box, f, s, plan)
    step, q = step_of(f / span, STRETCH)
    cw, ch = arcade.codex_art(s).size
    cx, mid = x + round(w * .5), y + max(2, round(h * .05)) + ch // 2
    face, rows = (s, 'open', 'long', 0), 0
    if step == 'rise':
        face, rows = (s, 'closed', 'open', 0), 2
    elif step in ('up', 'back', 'left', 'right'):
        face, rows = (s, 'closed', 'open', 0), 4
    elif step == 'settle':
        face = (s, 'open', 'long', (2, 2, 1, 0, 0, 0)[min(5, int(q * 6))])
    elif step == 'ahh':
        face = (s, 'happy', 'smile', 0)
    art = taller(arcade.codex_art, face, rows)
    bottom = mid + ch // 2 + rows // 2  # it grows up and down about its middle, as a cloud would
    put_leaning(frame, taller, (arcade.codex_art, face, rows), (art.width // 2, art.height), sway(step, q), cx, bottom)
    if step in ('up', 'back'):
        stretch_marks(draw, cx, bottom - art.height, art.width // 2, q)
    if step == 'ahh':
        sparkle(draw, cx + cw // 2 + 2, mid - ch // 2 + 1, twinkle(q))


# --- Grok -------------------------------------------------------------------------------------------------------------

def grok_pad(frame, draw, box, f, s, plan):
    """Grok's Moon at rest: the fuel tank (its gauge), the Falcon on its pad, the pad's lamp off."""
    x, y, w, h = box
    u, ground, deck, hr, rx, rest_art, gsize, gx0, sep = arcade.grok_backdrop(draw, box, f, s)
    used = plan.get('used') if isinstance(plan, dict) else None
    if used is not None:
        arcade.fuel_tank(draw, x + 2 * s, ground, s, 1 - used / 100, plan.get('label', ''))
    arcade.draw_stage(frame, draw, rx, deck, hr, u, ('left', 'centre', 'right'), 0, 0, 'empty', 0, 0, 1.0, 0, f)
    lamp = rx - rest_art.width // 2 - round(4 * u)
    draw.rectangle((lamp, deck - 1, lamp + max(1, round(u)), deck - 1), fill=arcade.DECK_EDGE)
    return ground, gsize, gx0


def grok_drink(frame, draw, box, f, span, s, plan):
    """A glass at Grok's side and a straw to its face; eyes shut as it sips, a hop and a sparkle after."""
    ground, gsize, gx = grok_pad(frame, draw, box, f, s, plan)
    step, q = step_of(f / span, DRINK)
    level, eyes, lift, squash = GLASS_LEVELS, 'open', 0, 0
    if step == 'lift':
        squash = 1 if q < .5 else 0  # a little bob as it bends to the straw
    elif step == 'sip':
        level, eyes = sip_level(q), 'shut'
    elif step == 'lower':
        level = LAST_SIP
    elif step == 'ahh':
        level, eyes = LAST_SIP, 'shut'
        lift = (0, 2, 3, 2, 0, 0, 0, 0, 0)[min(8, int(q * 9))]
    art = arcade.grok_pose(gsize, eyes, squash)
    left = round(gx - art.width / 2)
    gl = left + art.width + 2
    glass(frame, gl, ground, level)
    if step in ('lift', 'sip', 'lower'):
        straw(draw, [(gl + 4, ground - 3), (gl + 4, ground - len(GLASS) - 3), (left + art.width - 2, ground - 7)])
    paste(frame, art, left, ground - art.height - lift)
    if step == 'ahh':
        sparkle(draw, left + art.width + 1, ground - art.height - 2, twinkle(q))


def grok_stretch(frame, draw, box, f, span, s, plan):
    """Drawn up tall, eyes shut, a lean each way, a squash on settling, a sparkle."""
    ground, gsize, gx = grok_pad(frame, draw, box, f, s, plan)
    step, q = step_of(f / span, STRETCH)
    pose, rows = (gsize, 'open', 0), 0
    if step == 'rise':
        pose, rows = (gsize, 'shut', 0), 2
    elif step in ('up', 'back', 'left', 'right'):
        pose, rows = (gsize, 'shut', 0), 5
    elif step == 'settle':
        pose = (gsize, 'open', (2, 2, 1, 0, 0, 0)[min(5, int(q * 6))])
    elif step == 'ahh':
        pose = (gsize, 'shut', 0)
    art = taller(arcade.grok_pose, pose, rows)
    put_leaning(frame, taller, (arcade.grok_pose, pose, rows), (art.width // 2, art.height), sway(step, q), gx, ground)
    if step in ('up', 'back'):
        stretch_marks(draw, gx, ground - art.height, art.width // 2, q)
    if step == 'ahh':
        sparkle(draw, gx + art.width // 2 + 2, ground - art.height - 1, twinkle(q))


# --- Copilot ----------------------------------------------------------------------------------------------------------

def copilot_sky(frame, draw, box, f, s, plan, centre=.5):
    """Copilot's sky at rest: the clouds that count its use, and its own cloud; returns where the head stands."""
    x, y, w, h = box
    u = s / 2
    arcade.copilot_backdrop(draw, box, f, s, clouds=False)
    used = plan.get('used') if isinstance(plan, dict) else None
    if used is not None:
        arcade.cloud_count(draw, box, s, used, plan.get('label', ''))
    base_y = y + round(h * .78)
    arcade.cloud(draw, x + round(w * centre), base_y, max(5, round(14 * u)))
    return x + round(w * centre), base_y - round(4 * u)


def copilot_drink(frame, draw, box, f, span, s, plan):
    """The glass on a small cloud of its own beside Copilot, a straw up to the bottom of its visor; eyes shut as it
    sips, a hop and a sparkle after."""
    cx, stand = copilot_sky(frame, draw, box, f, s, plan)  # where it always sits, so the loop meets the next one
    step, q = step_of(f / span, DRINK)
    level, eyes, lift = GLASS_LEVELS, 'open', 0
    if step == 'sip':
        level, eyes = sip_level(q), 'shut'
    elif step == 'lower':
        level = LAST_SIP
    elif step == 'ahh':
        level = LAST_SIP
        lift = (0, 2, 3, 2, 0, 0, 0, 0, 0)[min(8, int(q * 9))]
    head = arcade.copilot_pose(arcade.COPILOT_HEAD * s, eyes)
    hx, hy = cx - head.width // 2, stand - head.height - lift
    side = (hx + head.width + 8, stand + 1)  # the little cloud the glass stands on
    arcade.cloud(draw, side[0], side[1], 4)
    glass(frame, side[0] - 3, side[1] - 2, level)
    if step in ('lift', 'sip', 'lower'):
        top = side[1] - 2 - len(GLASS)
        straw(draw, [(side[0], top + 4), (side[0], top - 3), (hx + 19, hy + 16)])
    paste(frame, head, hx, hy)
    if step == 'ahh':
        sparkle(draw, hx + head.width, hy - 1, twinkle(q))


def copilot_stretch(frame, draw, box, f, span, s, plan):
    """Up off its cloud and drawn up tall, eyes shut, a lean each way, a squash back onto the cloud, a sparkle."""
    cx, stand = copilot_sky(frame, draw, box, f, s, plan)
    step, q = step_of(f / span, STRETCH)
    size = arcade.COPILOT_HEAD * s
    pose, rows, lift = (size, 'open'), 0, 0
    if step == 'rise':
        pose, rows, lift = (size, 'shut'), 2, 1
    elif step in ('up', 'back', 'left', 'right'):
        pose, rows, lift = (size, 'shut'), 3, 2
    elif step == 'settle':
        rows = (-2, -2, -1, 0, 0, 0)[min(5, int(q * 6))]
    elif step == 'ahh':
        pose = (size, 'shut')
    art = taller(arcade.copilot_pose, pose, rows)
    put_leaning(frame, taller, (arcade.copilot_pose, pose, rows), (art.width // 2, art.height), sway(step, q), cx,
                stand - lift)
    if step in ('up', 'back'):
        stretch_marks(draw, cx, stand - lift - art.height, art.width // 2, q)
    if step == 'ahh':
        sparkle(draw, cx + art.width // 2 + 1, stand - art.height - 1, twinkle(q))


# --- Anti -------------------------------------------------------------------------------------------------------------

ANTI_HOVER = 7  # how high Anti floats over its glass (its float rest goes as high as 6)


def anti_drink(frame, draw, box, f, span, s, plan):
    """Anti floats up and over its glass, the antigravity way, and sips through a straw that comes up through its
    arch to its cat's mouth, eyes shut; it settles back down beside the glass, ^ ^."""
    x, y = box[:2]
    step, q = step_of(f / span, DRINK)
    gx = x + arcade.ANTI_MID + 16  # the glass, on the floor to Anti's right
    level, face, lift, sx = GLASS_LEVELS, 'normal', 0, 0
    if step == 'lift':
        k = ease(q)
        lift, sx = round(ANTI_HOVER * k), round(16 * k)
    elif step == 'sip':
        level, face = sip_level(q), 'blink'
        lift, sx = ANTI_HOVER + (1 if (f // 6) % 2 else 0), 16
    elif step == 'lower':
        k = 1 - ease(q)
        level, lift, sx = LAST_SIP, round(ANTI_HOVER * k), round(16 * k)
    elif step == 'ahh':
        level, face = LAST_SIP, 'happy'
    glass(frame, gx - 3, y + arcade.ANTI_FLOOR + 1, level)
    left, top = arcade.anti_stand(frame, box, arcade.anti_art(face, dy=1 if face == 'normal' else 0), lift, sx)
    if step == 'sip':
        straw(draw, [(gx, y + arcade.ANTI_FLOOR - 2), (gx, top + 10)])
    if step == 'ahh':
        sparkle(draw, left + 21, top + 1, twinkle(q))


def anti_stretch(frame, draw, box, f, span, s, plan):
    """Up on its toes (its legs a pixel longer a row), eyes shut, a lean each way, the landing squash, ^ ^."""
    x, y = box[:2]
    step, q = step_of(f / span, STRETCH)
    face, pose = 'normal', 'stand'
    if step in ('rise', 'up', 'back', 'left', 'right'):
        face, pose = 'blink', 'tall' if step != 'rise' or q >= .5 else 'stand'
    elif step == 'settle':
        pose = 'squash' if q < .5 else 'stand'
    elif step == 'ahh':
        face = 'happy'
    args = (face, 'logo', 0, 0, False, 1, pose)
    art = arcade.anti_art(*args)
    cx, floor = x + arcade.ANTI_MID, y + arcade.ANTI_FLOOR + 1
    put_leaning(frame, arcade.anti_art, args, (art.width // 2, art.height), sway(step, q), cx, floor)
    if step in ('up', 'back'):
        stretch_marks(draw, cx, floor - art.height, 4, q)
    if step == 'ahh':
        sparkle(draw, cx + 11, floor - art.height - 1, twinkle(q))


def anti_moment_scene(moment_draw):
    def scene(frame, draw, box, f, span, s, plan):
        left = arcade.anti_left(plan)
        label = plan.get('anti_label', '') if isinstance(plan, dict) and s == 1 else ''
        arcade.anti_maze(draw, box, f, s, left, 'floor', pellets=False)
        moment_draw(frame, draw, box, f, span, s, plan)
        if left is not None:
            arcade.anti_pellets(draw, box, left, label)
    return scene


SCENE_MOMENTS = {
    'codex': {'drink': codex_drink, 'stretch': codex_stretch},
    'grok': {'drink': grok_drink, 'stretch': grok_stretch},
    'copilot': {'drink': copilot_drink, 'stretch': copilot_stretch},
    'antigravity': {'drink': anti_moment_scene(anti_drink), 'stretch': anti_moment_scene(anti_stretch)},
}

