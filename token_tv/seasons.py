"""Arcade's seasonal props (x8), as the owner approved them (drafts w34-w37, 2026-11-05): on Halloween (10-25 to
11-01), Christmas (12-18 to 12-26) and Seollal (the day before the Korean lunar new year to the day after), endpoints
included, on the computer's local date, Arcade dresses its pets for the season by itself. Behind each scene's pet and
gauge goes the season's scenery (bats and pumpkin lanterns; falling snow and a small tree; a yut set and a lucky
pouch), clear of every gauge, and on each pet its hat (a witch's, Santa's, a saekdong cap); at Seollal Clawd, the
cloud and Copilot fly a shield kite. The pets keep their own form: only props are added. Every moment keeps the
season on (a hat waits while its pet spins), Judge Clawd keeps its wig; the hidden one-offs and the two events (a
reset's fireworks, a flop) are drawn as ever. On any other day Arcade is as it always was, byte for byte.

arcade.py draws them: arcade_frames dresses each scene it draws (Dress, in arcade.SEASON for its thread), each
backdrop then calls scenery(), and arcade.paste() calls wear() for art tagged with its pet (its info['pet']).
Everything is drawn on the scene's 120 x 71 stage, which Arcade doubles; every moving prop meets its loop's start.
"""
import datetime
import functools
import math
import random
import time

from PIL import ImageDraw

from token_tv import arcade
from token_tv.pet_moments import sprite

HALLOWEEN = ((10, 25), (11, 1))
CHRISTMAS = ((12, 18), (12, 26))
# The lunar new year in Korea (설날), by the Korean calendar, not China's: the new moon can fall either side of
# midnight between the two, and in 2027 (CN 02-06) and 2028 (CN 01-26, the new moon at 00:12 KST on 01-27) China's
# comes a day earlier. From KASI (한국천문연구원, Korea's official calendar), its lunar-to-solar conversion of each year's
# first lunar day (astro.kasi.re.kr/life/lunc?yyyy=<year>&mm=01&dd=01), read 2026-11-05. A year after 2040 needs its
# line here: until then it has no Seollal props.
SEOLLAL = {year: datetime.date(year, month, day) for year, (month, day) in {
    2026: (2, 17), 2027: (2, 7), 2028: (1, 27), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23), 2032: (2, 11),
    2033: (1, 31), 2034: (2, 19), 2035: (2, 8), 2036: (1, 28), 2037: (2, 15), 2038: (2, 4), 2039: (1, 24),
    2040: (2, 12)}.items()}
SEOLLAL_DAYS = (-1, 0, 1)  # the day before the lunar new year, the day, the day after


def season_on(day):
    """The season Arcade dresses for on `day` (a date): 'halloween', 'christmas', 'seollal', or None for every other
    day."""
    if HALLOWEEN[0] <= (day.month, day.day) <= HALLOWEEN[1]:
        return 'halloween'
    if CHRISTMAS[0] <= (day.month, day.day) <= CHRISTMAS[1]:
        return 'christmas'
    new_year = SEOLLAL.get(day.year)
    if new_year and (day - new_year).days in SEOLLAL_DAYS:
        return 'seollal'
    return None


def season_at(now=None):
    """The season of this computer's local date at `now` (time.time() when None), as the night's dimming reads it."""
    return season_on(datetime.date.fromtimestamp(time.time() if now is None else now))


class Dress:
    """What the scene being drawn wears: the `season`, and the scene's own `provider`, frame `f` of its turn of `span`
    frames, at work or not (`active`), how many scene frames each picture moves (`speed`), and the `stage` image."""
    __slots__ = ('season', 'provider', 'f', 'span', 'active', 'speed', 'stage')

    def __init__(self, season, provider, f, span, active, speed, stage):
        self.season, self.provider, self.f, self.span = season, provider, f, span
        self.active, self.speed, self.stage = active, speed, stage


# --- the props, one pixel a cell on the 120 x 71 stage, each drawn for TokenTV in colour -----------------------------

WITCH_INK = {'K': (92, 56, 150), 'k': (132, 92, 200), 'B': (255, 150, 50), 'Y': (255, 220, 90)}
SANTA_INK = {'R': (226, 48, 60), 'W': (248, 248, 252)}
CAP_INK = {'T': (230, 50, 70), 'R': (236, 70, 90), 'Y': (255, 206, 70), 'G': (84, 186, 108), 'B': (70, 128, 230),
           'P': (255, 140, 180)}
PUMPKIN_INK = {'O': (240, 128, 40), 'Y': (255, 226, 110), 'G': (100, 160, 60)}
BAT_INK = {'B': (130, 92, 186), 'E': (255, 210, 90)}
TREE_INK = {'Y': (255, 214, 80), 'G': (60, 170, 90), 'g': (40, 128, 72), 'r': (240, 70, 80), 'b': (90, 150, 255),
            'T': (130, 84, 50)}
POUCH_INK = {'R': (236, 72, 108), 'r': (186, 44, 80), 'Y': (255, 205, 80)}
KITE_INK = {'W': (248, 246, 236), 'R': (230, 50, 70), 'B': (70, 128, 230), 'S': (196, 170, 120)}
YUT_INK = {'L': (236, 204, 150), 'K': (120, 70, 40), 'D': (178, 118, 66), 'd': (210, 150, 92)}
SNOW, SNOW_FAR = (240, 244, 255), (150, 160, 190)
STRING = (210, 210, 220)

PROPS = {
    'witch': ('.......kK..', '......kKK..', '.....kKKK..', '....kKKKK..', '....kKKKKK.', '...BBBYBBB.', 'KKKKKKKKKKK'),
    'witch_small': ('....K..', '...KK..', '..KKK..', '..BYBB.', 'KKKKKKK'),
    'santa': ('........WW.', '.......RWW.', '......RR...', '....RRRR...', '...RRRRRR..', '..RRRRRRRR.', '.WWWWWWWWW.'),
    'santa_small': ('.....W.', '...RRW.', '..RRR..', '.RRRRR.', 'WWWWWWW'),
    'cap': ('...TTT...', '..RRRRR..', '.RYYYYYR.', 'PGGGGGGGP', 'BBBBBBBBB'),
    'cap_small': ('..T..', '.RRR.', 'YYYYY', 'BBBBB'),
    'pumpkin': ('....G....', '.OOOGOOO.', 'OOYOOOYOO', 'OYYOOOYYO', 'OOOOOOOOO', 'OYOYYYOYO', 'OOYYYYYOO', '.OOOOOOO.'),
    'pumpkin_small': ('...G...', '.OOGOO.', 'OYOOOYO', 'OOOOOOO', 'OYYYYYO', '.OOOOO.'),
    'bat_up': ('B.......B', 'BB.B.B.BB', '.BBEBEB..', '...BBB...'),
    'bat_down': ('...B.B...', '..BEBEB..', '.BBBBBBB.', 'B.......B'),
    'tree': ('....Y....', '...YYY...', '....G....', '...GGg...', '..GGrGg..', '...GGg...', '..GGGGg..', '.GGbGGGg.',
             '..GGGGg..', '.GGGGGGg.', 'GGGGGGrGg', '....T....'),
    'pouch': ('..Y.Y..', '.RRYRR.', '..rRr..', '.RRRRR.', 'RRRYRRR', 'RRYYYRR', 'RRRYRRr', '.rRRRr.'),
    'kite': ('WWWWWWWWW', 'WWWRRRWWW', 'WWRRRRRWW', 'WWWRRRWWW', 'WWS...SWW', 'WS.....SW', 'WWS...SWW', 'WWWWWWWWW',
             'BBWWWWWBB', 'BBBWWWBBB'),
    'yut': ('LLL.DDD.LLL.DDD', 'KLK.DdD.KLK.DdD', 'LKL.DdD.LKL.DdD', 'KLK.DdD.KLK.DdD', 'LLL.DdD.LLL.DdD',
            'KLK.DdD.KLK.DdD', 'LKL.DdD.LKL.DdD', 'KLK.DdD.KLK.DdD', 'LLL.DDD.LLL.DDD'),
}
PROP_INK = {'witch': WITCH_INK, 'witch_small': WITCH_INK, 'santa': SANTA_INK, 'santa_small': SANTA_INK, 'cap': CAP_INK,
            'cap_small': CAP_INK, 'pumpkin': PUMPKIN_INK, 'pumpkin_small': PUMPKIN_INK, 'bat_up': BAT_INK,
            'bat_down': BAT_INK, 'tree': TREE_INK, 'pouch': POUCH_INK, 'kite': KITE_INK, 'yut': YUT_INK}
HATS = {'halloween': 'witch', 'christmas': 'santa', 'seollal': 'cap'}


@functools.lru_cache(maxsize=None)
def prop(name):
    return sprite(PROPS[name], PROP_INK[name])


def put(frame, art, x, y):
    frame.paste(art, (round(x), round(y)), art)


def stamp(frame, name, cx, bottom):
    """A prop standing with its bottom middle at (cx, bottom)."""
    art = prop(name)
    put(frame, art, round(cx - art.width / 2), bottom - art.height)


SKIP = {'claude': ((97, 0, 119, 27),), 'grok': ((100, 2, 119, 20),), 'copilot': ((0, 0, 119, 22),),
        'antigravity': ((10, 14, 20, 24), (100, 14, 110, 24), (100, 46, 110, 56), (10, 46, 20, 56))}
# what the snow and the bats keep clear of: Claude's moon and its 5H, Grok's Earth, Copilot's five clouds, Anti's four
# pellets


def clear_of(provider, x0, y0, x1, y1):
    return not any(x0 <= b[2] and b[0] <= x1 and y0 <= b[3] and b[1] <= y1 for b in SKIP.get(provider, ()))


def laps(dress, pictures):
    """How many times something that takes `pictures` pictures goes round in the scene's turn: a whole number, so the
    loop meets its start (at least once)."""
    return max(1, round(dress.span / (pictures * dress.speed)))


def snow(dress, draw, box):
    """Snow falling the stage's height in about 30 pictures (4 s on an SD_PRO), a whole number of times a turn so the
    loop meets its start; a third of the flakes far off (dim), a few big (a small plus); none on the gauges."""
    x, y, w, h = box
    f, span, provider = dress.f, dress.span, dress.provider
    rnd = random.Random(7)
    cycles = laps(dress, 30)
    for k in range(26):
        fx0, fy0, far = rnd.randrange(w), rnd.randrange(h), k % 3 == 0
        fall = (fy0 + f * h * cycles / span) % h
        drift = round(math.sin(2 * math.pi * (f / span * cycles + k / 7)) * 1.5)
        fx, fy = x + (fx0 + drift) % w, y + int(fall)
        if not clear_of(provider, fx - 1, fy - 1, fx + 1, fy + 1):
            continue
        if far:
            draw.point((fx, fy), fill=SNOW_FAR)
        elif k % 4 == 1:  # a bigger flake: a small plus
            draw.point((fx, fy), fill=SNOW)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                draw.point((fx + dx, fy + dy), fill=SNOW_FAR)
        else:
            draw.point((fx, fy), fill=SNOW)


def bats(dress, frame, lanes):
    """Bats crossing the sky along `lanes` [(height, start, direction)], one crossing a lap of about 40 pictures, the
    wings up and down about every other picture (an even number of flaps a turn, so the loop meets its start)."""
    f, span = dress.f, dress.span
    cycles = laps(dress, 40)
    flaps = 2 * laps(dress, 4)
    for k, (ly, start, way) in enumerate(lanes):
        p = (f / span * cycles + start) % 1
        bx = round(-10 + p * 140) if way > 0 else round(130 - p * 140)
        by = ly + round(math.sin(2 * math.pi * (p * 3 + k / 3)) * 2)
        art = prop('bat_up' if (int(f / span * flaps) + k) % 2 else 'bat_down')
        if clear_of(dress.provider, bx - 5, by - 4, bx + 5, by + 1):
            put(frame, art, bx - art.width // 2, by - art.height)


def kite(dress, frame, draw, at, hand):
    """The shield kite (방패연: the hole in its middle, the red disc on top) swaying at `at` (its top middle), its line
    sagging down to `hand`."""
    f, span = dress.f, dress.span
    cycles = laps(dress, 60)
    sway = round(math.sin(2 * math.pi * f / span * cycles) * 1.5)
    kx, ky = at[0] + sway, at[1] + round(math.sin(2 * math.pi * f / span * cycles + 1) * 1)
    art = prop('kite')
    tail = (kx, ky + art.height - 1)
    steps = 12
    for k in range(steps + 1):  # the line, sagging a little between the kite and the hand
        t = k / steps
        lx = tail[0] + (hand[0] - tail[0]) * t
        ly = tail[1] + (hand[1] - tail[1]) * t + math.sin(math.pi * t) * 3
        draw.point((round(lx), round(ly)), fill=STRING)
    put(frame, art, kx - art.width // 2, ky)


HALLOWEEN_LANES = {'claude': ((16, 0, 1), (30, .55, 1)), 'codex': ((38, 0, -1), (30, .5, 1)),
                   'grok': ((12, .2, 1), (26, .7, 1)), 'copilot': ((28, 0, 1), (34, .5, -1)),
                   'antigravity': ((14, 0, 1),)}
TREE_SPOT = {'claude': 86, 'codex': 96, 'grok': 44, 'antigravity': 34}  # where each scene's tree stands, clear of it


def scenery(dress, draw, box, ground):
    """Behind the pet and its gauge, as a backdrop ends (`ground`: where its scene's ground is): the season's things in
    this scene, each clear of the gauge."""
    frame, provider = dress.stage, dress.provider
    x, y, w, h = box
    if dress.season == 'christmas':
        snow(dress, draw, box)
        if provider == 'copilot':  # its tree on a little cloud of its own
            arcade.cloud(draw, x + 98, y + 62, 4)
            stamp(frame, 'tree', x + 98, y + 61)
        elif provider in TREE_SPOT:
            stamp(frame, 'tree', x + TREE_SPOT[provider], ground)
    elif dress.season == 'halloween':
        bats(dress, frame, HALLOWEEN_LANES.get(provider, ()))
        if provider == 'claude':
            stamp(frame, 'pumpkin', x + 80, ground + 1)
            stamp(frame, 'pumpkin_small', x + 92, ground + 1)
        elif provider == 'codex':
            stamp(frame, 'pumpkin', x + 24, ground + 1)
            stamp(frame, 'pumpkin_small', x + 96, ground + 1)
        elif provider == 'grok':
            stamp(frame, 'pumpkin', x + 44, ground)
        elif provider == 'antigravity':  # the maze's bonus fruit this week: a pumpkin on the floor
            stamp(frame, 'pumpkin', x + 86, ground)
    elif dress.season == 'seollal':
        if provider == 'claude':
            stamp(frame, 'yut', x + 84, ground + 1)
        elif provider == 'codex':
            stamp(frame, 'pouch', x + 24, ground + 1)
        elif provider == 'grok':
            stamp(frame, 'pouch', x + 44, ground)
        elif provider == 'copilot':
            arcade.cloud(draw, x + 98, y + 62, 4)
            stamp(frame, 'pouch', x + 98, y + 61)
        elif provider == 'antigravity':  # a game of yut on the maze floor, and the pouch by it
            stamp(frame, 'yut', x + 32, ground)
            stamp(frame, 'pouch', x + 88, ground)


def crown(art):
    """Where a pet's head is in its art: the middle of its top and the top row, found in the middle of its width (so
    Clawd's arms up in the air are not taken for its head)."""
    w, h = art.size
    alpha = art.getchannel('A')
    band = alpha.crop((round(w * .3), 0, round(w * .7), h)).getbbox()
    top = band[1] if band else 0
    row = alpha.crop((0, top, w, top + 2)).getbbox() or (0, 0, w, 2)
    return (row[0] + row[2]) / 2, top


def wear(dress, frame, art, x, y):
    """On the pet `art` just pasted at (x, y): its hat, the brim over the top row of its head; and, at Seollal, the kite
    on a line held by Clawd, the cloud or Copilot. Only the scene's own pet; a pet spinning past 30 degrees (a
    break-dance) has its hat back once it is upright again."""
    provider = art.info.get('pet')
    if provider != dress.provider:
        return
    turn = art.info.get('turn', 0) % 360
    if min(turn, 360 - turn) > 30:
        return
    cx, top = crown(art)
    hat = prop(HATS[dress.season] + ('' if art.width >= 14 else '_small'))
    sink = 1 if provider != 'antigravity' else 0
    put(frame, hat, round(x + cx - hat.width / 2), y + top + sink - hat.height + (1 if provider == 'claude' else 0))
    if dress.season == 'seollal' and provider in ('claude', 'codex', 'copilot') and art.width >= 14:
        draw = ImageDraw.Draw(frame)
        if provider == 'claude':  # held in its right hand (the arm at the side of its body)
            hand = (x + art.width - 2, y + art.height - 9)
            kite(dress, frame, draw, (min(hand[0] + 22, 84), 4), hand)
        elif provider == 'codex':  # tied under the cloud
            kite(dress, frame, draw, (min(x + art.width + 18, 108), 24), (x + art.width - 6, y + art.height - 3))
        else:
            kite(dress, frame, draw, (106, 22), (x + art.width - 2, y + art.height - 6))
