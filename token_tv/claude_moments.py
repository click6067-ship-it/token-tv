"""Clawd's phase-3a moments on the Arcade stage, as the owner approved them (drafts w17-w23, 2026-11-05): the courtroom
for a risky command (e3: Judge Clawd's verdict on Clawd in the dock, or Clawd's own OBJECTION!, one of the two at
random each time), the ghost of a deleted file (e4: drifting round Clawd's usual scene, or with Clawd watching it and
waving), Clawd's back turned for a rude prompt and its turn back round (e7), dizzy after a failed tool and squeezing
its head on a compaction (x5). The thinking word (x6) is the readout's alone (arcade.action_label).

A once-through moment (the courtroom, the turn back round, the two tool faces) plays once through Clawd's turn, a
scene frame a frame, as phase 2's do. The ghost and the sulk are states that last a minute: their GIF loops, so each
is drawn to meet its own start (one lap of the ghost, one glare over the shoulder a loop). Whatever is meant to last
keeps something moving (darting eyes, a sweat drop, a tapping foot, a twinkle): drawn when the clock was thought to
show every picture for one 142 ms tick, a still pose flashing by; it shows each for its delay, at least a tick (m1).
Clawd's poses are its own frames from Clawd's Quest; new are the props (the dock, the bench, the gavel, the wig, the
cards, the ghost, the steam, the stars, the thought bubbles), a few eye pixels (none from behind, a frown, squeezed
shut) and the arms put to its head. With its back turned and a ghost about at once, the ghost drifts round the sulk.

arcade.py draws them: claude_scene hands the row's moment to SCENES ({'kind': 'risky', 'style': 'objection'}, say).
Everything is drawn on the scene's 120 x 71 stage, which Arcade doubles.
"""
import functools
import math

from PIL import Image

from token_tv import arcade
from token_tv import pet_moments as pm
from token_tv.arcade import paste
from token_tv.display import pixel_text
from token_tv.moments import COURTS, GHOSTS

BODY, SHADE, DARK = '#d97757', '#be684d', '#141413'


# --- Clawd's own frames, a few pixels changed ---------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def grid(name, index):
    """Clawd's frame as rows of colours ('#d97757'), None where clear; Thinking's bubble left out."""
    sheet = arcade.clawd_data()[name]
    keys = [c.lower() for c in sheet['palette']]
    w = sheet['w']
    values = arcade.clawd_frames(name)[index]
    return tuple(tuple(None if v == 255 or keys[v] == pm.THOUGHT else keys[v] for v in values[y * w:(y + 1) * w])
                 for y in range(sheet['h']))


def eyes_of(g):
    """The eye pixels of a frame, (left eye, right eye), each a list of (x, y)."""
    w = len(g[0])
    spots = [(x, y) for y, row in enumerate(g) for x, c in enumerate(row) if c == DARK]
    return [p for p in spots if p[0] < w / 2], [p for p in spots if p[0] >= w / 2]


@functools.lru_cache(maxsize=None)
def edited(g, look):
    """`g` with its eyes changed: 'none' (from behind: body where the eyes were), 'squeeze' (squeezed shut: > <),
    'shut' (a line on the eye's lowest row), 'frown' (Disappointed's own look: a brow and the eye under its outer
    end)."""
    rows = [list(r) for r in g]
    for side, eye in enumerate(eyes_of(g)):
        if not eye:
            continue
        top, low = min(y for _, y in eye), max(y for _, y in eye)
        x0, x1 = min(x for x, _ in eye), max(x for x, _ in eye)
        for x, y in eye:
            rows[y][x] = BODY
        if look == 'squeeze':  # '>' on the left, '<' on the right, three rows tall
            tip, back = (x1, x0) if side == 0 else (x0, x1)
            for y, x in ((top - 1, back), (top, tip), (low, back)):
                rows[y][x] = DARK
        elif look == 'shut':
            for x in range(x0 - (side == 1), x1 + 1 + (side == 0)):
                rows[low][x] = DARK
        elif look == 'frown':  # Disappointed's own look: a brow three wide, the eye a pixel under its outer end
            for x in range(x0 - (side == 0), x1 + 1 + (side == 1)):
                rows[top][x] = DARK
            rows[low][x0 if side == 0 else x1] = DARK
    return tuple(tuple(r) for r in rows)


def flipped(g):
    return tuple(tuple(reversed(r)) for r in g)


ELBOW = ((1, 7), (2, 7), (0, 6), (1, 6), (2, 6), (0, 5), (1, 5), (2, 5), (1, 4), (2, 4), (3, 4), (2, 3), (3, 3),
         (3, 2), (3, 1))  # the left arm bent up, elbow out, its hand at the temple (the right one mirrors it)


@functools.lru_cache(maxsize=None)
def hands_on_head(g, press=False):
    """A standing frame holding its head: both arms bent up, elbows out, hands at its temples (the hands in the shade,
    so they read apart from the head); `press` squeezes: the arms up a pixel and in at the hands, the head's top
    corners pinched in."""
    rows = [list(r) for r in g]
    w = len(rows[0])
    for y in range(4, 8):  # the arms leave their place
        for x in list(range(0, 4)) + list(range(w - 4, w)):
            rows[y][x] = None
    for x, y in ELBOW:
        if press:
            x, y = x + (y <= 4), y - 1
        ink = SHADE if y <= 3 and x >= 3 else BODY
        rows[y][x] = rows[y][w - 1 - x] = ink
    if press:
        for y in (0, 1):
            rows[y][4] = rows[y][w - 5] = None
    return tuple(tuple(r) for r in rows)


@functools.lru_cache(maxsize=None)
def tap(g, up):
    """One leg (the outer one on the right) lifted a pixel: its lowest pixels cleared, a foot tapping."""
    if not up:
        return g
    rows = [list(r) for r in g]
    low = max(y for y, r in enumerate(rows) if any(r))
    right = [x for x, c in enumerate(rows[low]) if c]
    for x in right[-2:]:
        rows[low][x] = None
    return tuple(tuple(r) for r in rows)


@functools.lru_cache(maxsize=None)
def art(g):
    out = Image.new('RGBA', (len(g[0]), len(g)))
    out.putdata([(0, 0, 0, 0) if c is None else tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
                 for row in g for c in row])
    return arcade.tag(out, 'claude')


@functools.lru_cache(maxsize=None)
def robed(g):
    """Judge Clawd's frame: its own, untagged, so in season its wig is all it wears on its head (seasons.py)."""
    out = art(g).copy()
    out.info.pop('pet', None)
    return out


def pivot(name):
    x, y, w, h = arcade.clawd_data()[name]['a0']
    return round(x + w / 2), y + h


def put(frame, name, g, foot_x, foot_y, lean=0, lift=0):
    """Stand frame `g` of animation `name` on (foot_x, foot_y) as place_clawd does, leaning `lean` at its top."""
    pm.put_leaning(frame, art, (g,), pivot(name), lean, foot_x, foot_y - lift)


def clawd(frame, name, index, foot_x, foot_y, look=None, lean=0, lift=0):
    g = grid(name, index)
    put(frame, name, edited(g, look) if look else g, foot_x, foot_y, lean, lift)


def backdrop(frame, draw, box, f, s, plan):
    """Clawd's world standing still, with its moon (the 5-hour window), as claude_scene draws it for a moment;
    returns where Clawd stands."""
    x, y, w, h = box
    ground_y = arcade.claude_backdrop(frame, draw, box, f, s, False)[0]
    if isinstance(plan, dict) and plan.get('moon') is not None:
        arcade.moon_gauge(draw, x + w - 12 * s, y + 11 * s, 8 * s, plan['moon'])
        if s == 1:
            arcade.gauge_label(draw, x + w - 12, y + 21, '5H', 'centre')
    return x + round(w * .3), ground_y


def sweat(draw, x, y, k):
    """A drop of sweat sliding down beside a head: `k` (0..1) how far it has slid."""
    yy = y + round(5 * k)
    draw.point((x, yy), fill=(220, 240, 255))
    draw.rectangle((x - 1, yy + 1, x + 1, yy + 2), fill=arcade.SWEAT_INK)


DARTING = (0, 9, 10, 9, 0, 6, 7, 6, 0, 13)  # LookingAround: ahead, up left, left, ..., right, down: eyes darting


# --- e3: the courtroom ---------------------------------------------------------------------------------------------

WOOD, WOOD_DARK, WOOD_LIGHT, WOOD_EDGE = (124, 76, 46), (82, 50, 32), (160, 104, 62), (204, 150, 92)
GOLD = (232, 186, 74)
CARD, CARD_EDGE, CARD_INK = (250, 244, 226), (196, 40, 52), (206, 30, 46)
IMPACT = (255, 236, 160)


def dock(draw, cx, ground, half=14, top=9):
    """The dock: a wooden box Clawd stands in, its rail at `top` pixels over the ground."""
    x0, x1, y0 = cx - half, cx + half, ground - top
    draw.rectangle((x0, y0 + 2, x1, ground - 1), fill=WOOD)
    for px in range(x0 + 4, x1 - 2, 6):  # the panels' grooves
        draw.line((px, y0 + 4, px, ground - 2), fill=WOOD_DARK)
    draw.rectangle((x0 - 1, y0, x1 + 1, y0 + 1), fill=WOOD_LIGHT)  # the rail
    draw.line((x0 - 1, y0, x1 + 1, y0), fill=WOOD_EDGE)


SCALES = ('....#....', '.#######.', '.#..#..#.', '###.#.###', '....#....', '...###...')


def bench(frame, draw, x0, x1, top, ground, shake=0):
    """The judge's bench: a tall desk, its top a lighter board, the scales of justice in gold on its front."""
    x0, x1 = x0 + shake, x1 + shake
    draw.rectangle((x0, top + 2, x1, ground - 1), fill=WOOD)
    draw.rectangle((x0 + 3, top + 5, x1 - 3, ground - 4), outline=WOOD_DARK)
    draw.rectangle((x0 - 2, top, x1 + 2, top + 1), fill=WOOD_LIGHT)
    draw.line((x0 - 2, top, x1 + 2, top), fill=WOOD_EDGE)
    scales = pm.sprite(SCALES, {'#': GOLD})
    paste(frame, scales, (x0 + x1) // 2 - 4, top + 8)


WIG, WIG_CURL = (244, 242, 236), (176, 176, 186)


def wig(draw, left, top):
    """A judge's white wig on a head whose top row is `top` and whose left edge is `left` (a 16-wide head): a cap
    two rows over it and rows of curls down both sides."""
    for x in range(left, left + 16):
        draw.point((x, top - 2), fill=WIG if 1 <= x - left <= 14 else WIG_CURL)
        draw.point((x, top - 1), fill=WIG_CURL if (x - left) % 3 == 1 else WIG)
        draw.point((x, top), fill=WIG)
    for y in range(top, top + 6):
        for x in (left - 2, left - 1, left + 16, left + 17):
            curl = (y - top + (x > left)) % 2
            draw.point((x, y), fill=WIG_CURL if curl else WIG)


GAVEL_UP = ('BHHHHHB', 'BHHHHHB', '...h...', '...h...', '...h...', '...h...', '...h...')  # held up by its handle's end
GAVEL_DOWN = ('BB.....', 'HH.....', 'HHhhhhh', 'HH.....', 'HH.....', 'BB.....')  # struck: the head down on the block
GAVEL_INK = {'H': (150, 92, 54), 'B': (226, 186, 120), 'h': (110, 68, 40)}


def judge(frame, draw, jx, jy, strike, nod=0, startled=False):
    """Judge Clawd, in a wig, behind the bench at (jx, jy), turned to the dock on its left, the gavel in its left
    hand: raised, or `strike`: down on the block, with a few lines off it; `startled`, its wig jumps off its head.
    Its own frame (Turning's three quarters to the left); the wig and the gavel are new."""
    g = grid('Turning', 20)
    pm.put_leaning(frame, robed, (edited(g, 'shut') if startled else g,), pivot('Turning'), 0, jx, jy + nod)
    left, top = jx - 12 + 3, jy + nod - 17 + 1  # the head's left edge and top row in that frame
    wig(draw, left, top - (4 if startled else 0))
    hand_x, hand_y = jx - 12, jy + nod - 17 + 6  # the end of its left arm
    if strike:
        paste(frame, pm.sprite(GAVEL_DOWN, GAVEL_INK), hand_x - 7, hand_y - 2)
        for dx, dy in ((-4, -1), (-5, 1), (3, -2), (4, 0)):
            draw.point((hand_x - 6 + dx, hand_y + 4 + dy), fill=IMPACT)
    else:
        paste(frame, pm.sprite(GAVEL_UP, GAVEL_INK), hand_x - 4, hand_y - 7)


def card(draw, cx, top, text, ink=CARD_INK):
    """A placard with `text` in red: cream board, a red rim."""
    w = len(text) * 6 - 1
    x0 = cx - w // 2 - 4
    draw.rectangle((x0, top, x0 + w + 7, top + 12), fill=CARD_EDGE)
    draw.rectangle((x0 + 1, top + 1, x0 + w + 6, top + 11), fill=CARD)
    pixel_text(draw, (x0 + 4, top + 3), text, color=ink)


GUILTY = (('nervous', .12), ('order', .46), ('verdict', .52), ('slump', 1.0))
BANG = (0, 0, 1, 1, 0, 0)  # each bang a picture at a time: up, up, down, down (lines), up, up


def court_guilty(frame, draw, box, f, span, active, s, plan, base):
    """The verdict: Clawd in the dock, eyes darting; Judge Clawd, in a wig at its bench, bangs the gavel three times
    (ORDER!) and Clawd flinches at each; the GUILTY card slams down; Clawd slumps, eyes shut, sweating."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    p = f / span
    step, q = pm.step_of(p, GUILTY)
    pic = f // 2  # the picture, 0-59
    jx, jy = 86, 50
    strike = step == 'order' and BANG[(pic - 7) % len(BANG)] == 1
    first_down = step == 'order' and BANG[(pic - 7) % len(BANG)] == 1 and BANG[(pic - 8) % len(BANG)] == 0
    draw.rectangle((jx - 21, 40, jx - 16, 41), fill=WOOD_DARK)  # the block the gavel strikes
    judge(frame, draw, jx, jy, strike, nod=1 if first_down else 0)
    bench(frame, draw, 72, 100, 42, ground, 1 if first_down else 0)
    if step == 'nervous':
        clawd(frame, 'LookingAround', DARTING[pic % len(DARTING)], foot_x, ground)
        sweat(draw, foot_x + 11, ground - 15, q)
    elif step == 'order':
        if strike:
            clawd(frame, 'Turning', 4, foot_x, ground)  # flinching, eyes shut
        else:
            clawd(frame, 'LookingAround', (6, 7)[pic % 2], foot_x, ground)  # eyes on the judge
    elif step == 'verdict':
        clawd(frame, 'LookingAround', 8, foot_x, ground, lift=1)  # up at the card
    else:
        index = 12 + min(8, int(q * 24))  # Disappointed: eyes shut, slumping down
        clawd(frame, 'Disappointed', index, foot_x, ground)
        sweat(draw, foot_x + 12, ground - 12, (q * 3) % 1)
    dock(draw, foot_x, ground)
    if step in ('verdict', 'slump'):  # the card slams down from above and stays, swinging a pixel
        k = pic - round(GUILTY[1][1] * span / 2)  # pictures since it fell
        top = (-12, -2, 7, 4, 5)[k] if k < 5 else 5 + (pic // 3) % 2
        card(draw, 50, top, 'GUILTY')


OBJECT = (('look', .12), ('gasp', .20), ('jump', .32), ('lunge', .38), ('shout', .94), ('settle', 1.0))
JUMP = (4, 4, 5, 6, 7, 8, 10, 11, 13, 14)  # Jumping's frames: crouch, up, at the top, down, the landing squash
BURST_FILL, BURST_EDGE, BURST_INK = (255, 255, 255), (196, 40, 52), (206, 30, 46)


@functools.lru_cache(maxsize=None)
def burst_points(cx, cy, rx, ry, spikes, phase):
    pts = []
    for k in range(spikes * 2):
        a = math.pi * k / spikes + phase
        r = 1 if k % 2 == 0 else .8
        pts.append((cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r))
    return tuple(pts)


def objection(draw, cx, cy, grow):
    """The shout: a jagged white burst with a red rim, OBJECTION! in red across it once it is full size."""
    pts = burst_points(cx, cy, round(42 * grow), round(12 * grow), 14, .1)
    draw.polygon(pts, fill=BURST_FILL, outline=BURST_EDGE)
    if grow >= 1:
        pixel_text(draw, (cx - 29, cy - 3), 'OBJECTION!', color=BURST_INK)


def court_objection(frame, draw, box, f, span, active, s, plan, base):
    """Clawd's own objection, before Judge Clawd at its bench: it looks about, starts (!), leaps, lands in a lunge
    with a frown, and OBJECTION! bursts over the court, shaking at first, so hard the judge's wig jumps off; Clawd
    holds the lunge, trembling with it, then straightens up, pleased."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    step, q = pm.step_of(f / span, OBJECT)
    pic = f // 2
    k = pic - round(OBJECT[3][1] * span / 2)  # pictures since the shout burst
    judge(frame, draw, 86, 50, False, startled=step == 'shout' and 1 <= k < 4)
    bench(frame, draw, 72, 100, 42, ground)
    if step == 'look':
        clawd(frame, 'LookingAround', DARTING[pic % len(DARTING)], foot_x, ground)
    elif step == 'gasp':
        clawd(frame, 'Excited', 3 if q < .25 else 4 if q < .5 else 0, foot_x, ground)
        arcade.alert_mark(draw, foot_x + 9, ground - 26, 1, 0)
    elif step == 'jump':
        clawd(frame, 'Jumping', JUMP[min(len(JUMP) - 1, int(q * len(JUMP)))], foot_x, ground)
    elif step in ('lunge', 'shout'):
        lean = 2 if step == 'lunge' and q < .5 else 4 + (pic % 2 if step == 'shout' else 0)
        clawd(frame, 'Disappointed', 9, foot_x, ground, lean=lean)
    else:
        clawd(frame, 'Excited', 6 if q < .7 else 0, foot_x, ground)
    if step == 'shout':
        grow = (.45, .8)[k] if k < 2 else 1
        shake = (0, 0, 2, -2, 1, -1)[k] if k < 6 else 0
        objection(draw, 54 + shake, 15, grow)


# --- e4: the ghost of a deleted file ---------------------------------------------------------------------------------

GHOST_INK = {'W': (236, 241, 252), 'F': (166, 182, 214), 'E': (34, 38, 64), 'L': (190, 204, 230)}
GHOST = ('WWWWWWF...', 'WWWWWWFF..', 'WWWWWWWWF.', 'WWWWWWWWWW', 'WWWWWWWWWW', 'WWWWWWWWWW', 'WWWWWWWWWW',
         'WLLLLLWWWW', 'WWWWWWWWWW', 'WLLLLWWWWW', 'WWWWWWWWWW')  # a page, its corner folded, two lines on it
HEMS = ('W.WW.WW.WW', 'WW.WW.WW.W')  # the hem's two shapes, a flutter


@functools.lru_cache(maxsize=None)
def ghost_art(hem, look, down, flip):
    """The ghost of a deleted file: a page with its corner folded, two eyes (`look` -1, 0, 1: to its left, ahead,
    to its right; `down` a row lower) and a wavy hem; flipped when it floats to the left."""
    rows = [list(r) for r in GHOST] + [list(HEMS[hem])]
    for y in (3 + down, 4 + down):
        for x in (2, 6):
            rows[y][x + look] = 'E'
    out = pm.sprite([''.join(r) for r in rows], GHOST_INK)
    return out.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip else out


GHOST_PATH = (54, 27, 32, 6)  # its lap: an oval's middle and half widths, clear of the moon


def ghost_at(p):
    """Where the ghost is at `p` (0..1) through its lap, and whether it floats right: a slow oval over the scene, its
    left end (over Clawd) halfway through the loop, along the high side leftwards and the low side back, bobbing."""
    cx, cy, rx, ry = GHOST_PATH
    a = 2 * math.pi * (p - .5)
    return cx - rx * math.cos(a), cy + ry * math.sin(a) + 2 * math.sin(4 * a), math.sin(a) >= 0


def draw_ghost(frame, f, span, down=0):
    x, y, right = ghost_at(f / span)
    g = ghost_art((f // 2) % 2, 1, down, not right)
    paste(frame, g, x - g.width / 2, y - g.height / 2)


def ghost_drift(frame, draw, box, f, span, active, s, plan, base):
    """The ghost of a deleted file drifting round the scene, once round a loop, while Clawd does what it was doing
    (its usual scene, at its usual pace)."""
    base(frame, draw, box, (f * arcade.SPEED) % span, span, active, s, dict(plan, moment=None))
    draw_ghost(frame, f, span)


def ghost_wave(frame, draw, box, f, span, active, s, plan, base):
    """Clawd stops to watch the ghost go round, its eyes on it, and waves at it as it floats by overhead; the ghost
    looks down at Clawd as it passes."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    gx = ghost_at(f / span)[0]
    near = abs(gx - foot_x) < 13
    if near:
        clawd(frame, 'Waving', 6 + (f // 2) % 10, foot_x, ground)
    else:
        clawd(frame, 'LookingAround', 9 if gx < foot_x - 4 else 8 if gx < foot_x + 20 else 7, foot_x, ground)
    draw_ghost(frame, f, span, down=1 if near else 0)


# --- e7: the back turned --------------------------------------------------------------------------------------------

def back():
    """Clawd from behind: its standing frame with no eyes."""
    return edited(grid('LookingAround', 0), 'none')


def back_quarter():
    """Turned three quarters away: Turning's quarter turn (its side in the shade) with no eyes."""
    return edited(grid('Turning', 20), 'none')


STEAM = (214, 218, 228)


def puff(draw, x, y, age, side):
    """A puff of steam blown out sideways (`side` -1 or 1) off the head, `age` pictures old (gone at 5)."""
    if not 0 <= age < 5:
        return
    cx, cy = x + side * 2 * age, y - (age // 2)
    if age == 0:
        draw.rectangle((cx, cy, cx + 1, cy + 1), fill=STEAM)
    elif age < 3:
        draw.rectangle((cx - 1, cy, cx + 1, cy + 1), fill=STEAM)
        draw.point((cx, cy - 1), fill=STEAM)
        draw.point((cx + side * 2, cy + 1), fill=STEAM)
    else:
        for dx, dy in ((-1, 0), (1, -1), (side * 2, 1)):
            draw.point((cx + dx, cy + dy), fill=STEAM)


ANGER = ('.##.##.', '##...##', '.......', '##...##', '.##.##.')
ANGER_INK = (238, 64, 72)

SULK = (('back', .40), ('turn', .44), ('glare', .66), ('hmph', .72), ('again', 1.0))


def sulk(frame, draw, box, f, span, active, s, plan, base):
    """Its back to you, a foot tapping, a huff of steam now and then; once a loop it turns round to glare at you
    (Disappointed's frown, an anger mark by its head) and turns its back again with a puff each side: hmph."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    step, q = pm.step_of(f / span, SULK)
    pic = f // 2
    up = pic % 2 == 1
    head = ground - 13  # beside the head, a row under its eyes' level
    if step in ('back', 'again'):
        put(frame, 'LookingAround', tap(back(), up), foot_x, ground)
        for start, side in (((4, 1), (15, -1)) if step == 'back' else ((50, 1),)):  # huffs, now one side, now the other
            puff(draw, foot_x + side * 13, head, pic - start, side)
    elif step == 'turn':
        put(frame, 'Turning', back_quarter(), foot_x, ground)
    elif step == 'glare':
        put(frame, 'Turning', tap(edited(grid('Turning', 20), 'frown'), up), foot_x, ground)
        if pic % 4 != 3:
            paste(frame, pm.sprite(ANGER, {'#': ANGER_INK}), foot_x + 9, ground - 22)
    else:  # hmph: a squash, eyes shut, then the hop back round
        k = pic - round(SULK[2][1] * span / 2)
        if k < 2:
            clawd(frame, 'Turning', 28, foot_x, ground)
        else:
            put(frame, 'Turning', edited(grid('Turning', 17), 'none'), foot_x, ground)
        for side in (-1, 1):
            puff(draw, foot_x + side * 13, head, k, side)


CALM = (('back', .12), ('peek', .30), ('turn', .36), ('happy', .80), ('settle', 1.0))
WONDER = (240, 240, 250)


def calm(frame, draw, box, f, span, active, s, plan, base):
    """A calm prompt: the tapping slows, Clawd looks round over its shoulder (?), hops round to face you, and is
    happy again, a heart rising; then it settles into its usual stance."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    p = f / span
    step, q = pm.step_of(p, CALM)
    pic = f // 2
    if step == 'back':
        put(frame, 'LookingAround', tap(back(), pic in (1, 4)), foot_x, ground)
    elif step == 'peek':
        k = pic - round(CALM[0][1] * span / 2)
        if k < 1:
            put(frame, 'Turning', back_quarter(), foot_x, ground)
        else:
            clawd(frame, 'Turning', 20, foot_x, ground, look='shut' if k == 6 else None)
            if k % 4 != 0:  # a question mark over its head, blinking: is it over?
                pixel_text(draw, (foot_x - 6, ground - 27), '?', color=WONDER)
    elif step == 'turn':
        clawd(frame, 'Turning', 28 if q < .5 else 0, foot_x, ground)
    elif step == 'happy':
        clawd(frame, 'Excited', 3 if q < .06 else 4 if q < .12 else 5 + int(q * 32) % 16, foot_x, ground)
    else:
        clawd(frame, 'Excited', 21 if q < .2 else 22 if q < .4 else 6 if q < .8 else 0, foot_x, ground)
        pm.sparkle(draw, foot_x + 12, ground - 19, pm.twinkle(q))
    if step in ('happy', 'settle'):  # one heart, big then small, rising
        a = (p - CALM[2][1]) / .45
        if 0 <= a < 1:
            h = pm.HEART_BIG if a < .6 else pm.HEART_SMALL
            x = foot_x + 2 + round(math.sin(a * math.pi * 2) * 1.5)
            paste(frame, h, x - h.width // 2, ground - 22 - round(16 * a) - h.height)


# --- x5: a failed tool, a compaction --------------------------------------------------------------------------------

STAR, STAR_CORE = (255, 216, 92), (255, 250, 220)


def stars_round(draw, cx, cy, f, n=3):
    """Little stars going round over a dizzy head, a step on each picture."""
    for k in range(n):
        a = 2 * math.pi * (k / n + f / 24)
        x, y = round(cx + 10 * math.cos(a)), round(cy + 2.5 * math.sin(a))
        draw.point((x, y), fill=STAR_CORE)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw.point((x + dx, y + dy), fill=STAR)


DIZZY = (('stand', .05), ('spin', .72), ('shake', .86), ('back', 1.0))


def dizzy(frame, draw, box, f, span, active, s, plan, base):
    """A tool failed: Clawd's own Dizzy (spiral eyes, wobbling), stars going round over its head; it shakes it off
    with its eyes shut and stands again."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    step, q = pm.step_of(f / span, DIZZY)
    if step == 'stand':
        clawd(frame, 'Dizzy', min(5, int(q * 6)), foot_x, ground)
    elif step == 'spin':
        clawd(frame, 'Dizzy', 6 + int(q * 40) % 24, foot_x, ground)
        stars_round(draw, foot_x + 1, ground - 21, f)
    elif step == 'shake':
        clawd(frame, 'Dizzy', 30 + min(5, int(q * 6)), foot_x, ground)
    else:
        clawd(frame, 'Dizzy', 36 + min(4, int(q * 5)), foot_x, ground)


BUBBLE = ('.###.', '#####', '#####', '.###.', '.#...')  # Clawd's own thought bubble, small
BUBBLE_SMALL = ('.#.', '###', '.#.')
SQUEEZE = (('stand', .06), ('hands', .12), ('squeeze', .72), ('drop', .78), ('fresh', 1.0))


def squeeze(frame, draw, box, f, span, active, s, plan, base):
    """A compaction: Clawd puts its hands to its head and squeezes, eyes shut tight, trembling, three squeezes; each
    squeezes a thought bubble out of the top of its head (its own bubble's blue), which floats off and shrinks away;
    then hands down and a fresh ^ ^."""
    foot_x, ground = backdrop(frame, draw, box, f, s, plan)
    step, q = pm.step_of(f / span, SQUEEZE)
    stand = grid('LookingAround', 0)
    pic = f // 2
    if step == 'stand':
        clawd(frame, 'LookingAround', (0, 8)[pic % 2], foot_x, ground)
    elif step == 'hands':
        put(frame, 'LookingAround', hands_on_head(edited(stand, 'squeeze')), foot_x, ground)
    elif step == 'squeeze':
        k = (q * 3) % 1  # three squeezes: press (trembling), then ease
        press = k < .55
        jitter = (pic % 2) * 2 - 1 if press else 0
        put(frame, 'LookingAround', hands_on_head(edited(stand, 'squeeze'), press), foot_x + jitter, ground)
        if press and pic % 2 == 0:  # the strain, flickering
            pm.stretch_marks(draw, foot_x, ground - 16, 12, 0)
    elif step == 'drop':
        put(frame, 'LookingAround', edited(stand, 'squeeze'), foot_x, ground)
    else:
        clawd(frame, 'Excited', 3 if q < .1 else 6, foot_x, ground)
        pm.sparkle(draw, foot_x + 12, ground - 19, pm.twinkle(q))
    start = round(SQUEEZE[1][1] * span / 2)  # the bubbles: one a squeeze, popping at its height
    for n in range(3):
        age = pic - (start + 3 + n * 10)
        if 0 <= age < 9:
            side = (-1, 1, -1)[n]
            x = foot_x + side * (2 + age * 2)
            y = ground - 22 - age * 2
            b = pm.sprite(BUBBLE if age < 5 else BUBBLE_SMALL, {'#': (105, 154, 203)})
            if age < 8:
                paste(frame, b, x - b.width // 2, y - b.height)


# --- which scene draws a moment ---------------------------------------------------------------------------------------

def sulk_haunted(frame, draw, box, f, span, active, s, plan, base):
    """Its back turned and a ghost about at once: the sulk, the ghost drifting round it (Clawd has no eyes for it)."""
    sulk(frame, draw, box, f, span, active, s, plan, base)
    draw_ghost(frame, f, span)


# The two variants of each (moments.COURTS, moments.GHOSTS), one picked at random each time one begins, as the bows
# are: the courtroom's A, Judge Clawd's verdict on Clawd in the dock, or B, Clawd's own OBJECTION!; the ghost's A,
# drifting round Clawd's usual scene, or B, Clawd watching it go and waving.
SCENES = {('risky', COURTS[0]): court_guilty, ('risky', COURTS[1]): court_objection,
          ('deleted', GHOSTS[0]): ghost_drift, ('deleted', GHOSTS[1]): ghost_wave, ('rude', None): sulk,
          ('calm', None): calm, ('failed', None): dizzy, ('compact', None): squeeze}


def scene_of(moment):
    """The scene that draws Clawd's phase-3a `moment` (a row's {'kind', 'style'?, 'ghost'?}), or None for any other.
    A moment without its style draws the first variant; the sulk with a ghost about, the two together."""
    kind = moment.get('kind')
    if kind == 'rude' and moment.get('ghost'):
        return sulk_haunted
    style = moment.get('style') or {'risky': COURTS[0], 'deleted': GHOSTS[0]}.get(kind)
    return SCENES.get((kind, style if kind in ('risky', 'deleted') else None))
