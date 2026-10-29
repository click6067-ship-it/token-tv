"""The one-offs everyone may read about: fireworks when a window resets (or a saved reset is spent),
a flop when one runs out. Not random: the live loop plays one when the store sees it happen, for the
account it happened to. The rarer, hidden one-offs ship only as locked boxes (`lockbox.py`)."""
import math

from token_tv import arcade
from token_tv.arcade import paste, place_clawd
from token_tv.display import pixel_text


def timeline(f, parts):
    """The (sprite, frame) playing at `f` from a list of (sprite, first, last) clips at 12 fps; after the
    last clip its final pose is held, so the key moment lingers."""
    for name, first, last in parts:
        length = last - first + 1
        if f < length:
            return name, first + f
        f -= length
    name, _, last = parts[-1]
    return name, last


def clawd_ground(frame, draw, box, f, s):
    x, y, w, h = box
    ground, *_ = arcade.claude_backdrop(frame, draw, box, f, s, False, pit=False)
    return ground, x + round(w * .3)


def codex_place(box, s):
    x, y, w, h = box
    cw, ch = arcade.codex_art(s).size
    return x + round(w * .5), y + max(2, round(h * .05)) + ch // 2, cw, ch


SPARKS = ((255, 214, 107), (255, 255, 255), (255, 128, 150), (120, 220, 255), (150, 240, 170))
SWEAT = (140, 200, 255)


def fireworks(draw, box, f, s, colors=None):
    """Five rockets rise and burst over the scene one after another: a flash, streaks, falling sparks."""
    colors = colors or SPARKS
    x, y, w, h = box
    for n, (start, fx, fy) in enumerate(((2, .22, .24), (20, .72, .18), (38, .48, .3), (58, .82, .26), (78, .3, .16))):
        t = f - start
        cx, cy = x + round(w * fx), y + round(h * fy)
        if 0 <= t < 5:  # the rising spark
            draw.rectangle((cx, cy + (5 - t) * 5 * s, cx + s - 1, cy + (5 - t) * 5 * s + 3 * s), fill=colors[0])
        elif t == 5:  # the flash
            draw.ellipse((cx - 3 * s, cy - 3 * s, cx + 3 * s, cy + 3 * s), fill=(255, 255, 240))
        elif 5 < t < 24:
            r = (t - 5) * 2.4 * s
            fall = (t - 5) ** 2 * .06 * s
            for k in range(16):
                a = math.radians(k * 22.5 + n * 9)
                color = colors[(k + n) % len(colors)]
                if t > 16:
                    color = tuple(c * 2 // 3 for c in color)
                ex, ey = cx + math.cos(a) * r, cy + math.sin(a) * r + fall
                if t < 13:  # a streak behind each spark
                    bx, by = cx + math.cos(a) * (r - 3 * s), cy + math.sin(a) * (r - 3 * s) + fall
                    draw.line((round(bx), round(by), round(ex), round(ey)), fill=color, width=max(1, s // 2))
                d = max(1, s if t < 18 else s // 2)
                draw.rectangle((round(ex), round(ey), round(ex) + d - 1, round(ey) + d - 1), fill=color)


def sweat(draw, x, y, s, f):
    """A cartoon sweat drop sliding down beside a tired face."""
    dy = (f % 24) * s // 3
    draw.rectangle((x, y + dy, x + s, y + dy + 2 * s), fill=SWEAT)
    draw.rectangle((x + s // 2, y + dy - s, x + s // 2, y + dy - 1), fill=SWEAT)


def star(draw, x, y, s, colour=(255, 214, 107)):
    """A small four-pointed sparkle centred on (x, y)."""
    draw.rectangle((x - s, y - 3 * s, x, y + 2 * s), fill=colour)
    draw.rectangle((x - 3 * s, y - s, x + 2 * s, y), fill=colour)


def hop(f, period=12, height=10):
    t = f % period
    half = period / 2
    return 4 * (t / half) * (1 - t / half) * height if t < half else 0


EGG_SECONDS = 11  # a rare one-off plays the whole ten-second loop once, then the usual face again


def lerp(a, b, t):
    return a + (b - a) * max(0, min(1, t))


def ease(t):
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)


def anti_event(frame, draw, box, f, happy, points=200, left=None):
    """Anti's reset and full, in the old arcade's terms (`f` at 12 a second). Reset: PLAYER ONE, READY!, its body
    grows back round its eyes, it leaves the house by the door and the pellets come back one by one, up to what is
    really left (`left`, None to leave them out). Full: wide-eyed and blue, flashing, eaten (only the points stay
    a moment), the eyes rush home, and a little star: it used it all."""
    x, y, w, h = box
    hx, hy = x + arcade.ANTI_HOME[0], y + arcade.ANTI_HOME[1] + 2
    art = arcade.anti_art
    if happy:
        refill = 0 if f < 56 else min(4, (f - 56) // 6 + 1)
        shown = None if left is None else min(left, refill / 4)
        arcade.anti_maze(draw, box, f, 1, shown, house=True, door=f < 36, pellets=left is not None)
        if f < 24:
            pixel_text(draw, (x + 60, y + 13), 'PLAYER ONE', scale=1, color=(0, 255, 255), align='center')
        if 6 <= f < 36:
            pixel_text(draw, (x + 60, y + 22), 'READY!', scale=1, color=(255, 255, 0), align='center')
        if f < 12:
            paste(frame, art('eaten', 'none'), hx, hy)
        elif f < 24:  # the body comes back round the eyes
            paste(frame, art('normal', 'logo') if f % 4 < 2 else art('eaten', 'none'), hx, hy)
        elif f < 36:
            paste(frame, art('happy', 'logo'), hx, hy)
        elif f < 56:  # up through the door
            paste(frame, art('normal', 'logo', (f // 6) % 2, 0, -1), hx, lerp(hy, y + 9, ease((f - 36) / 19)))
        else:
            paste(frame, art('happy' if f < 100 else 'normal', 'logo', (f // 6) % 2),
                  hx + 20 * math.sin(2 * math.pi * (f - 56) / 64), y + 9)
        if left is not None and 56 <= f < 56 + 6 * math.ceil(left * 4) and (f - 56) % 6 < 2:  # each glints as it comes back
            px_, py_ = arcade.ANTI_PELLETS[3 - min(3, (f - 56) // 6)]
            draw.point((x + px_, y + py_ - 5), fill=(255, 255, 255))
            draw.point((x + px_ + 5, y + py_), fill=(255, 255, 255))
        return
    arcade.anti_maze(draw, box, f, 1, left, house=True, pellets=left is not None)
    if f < 24:
        paste(frame, art('wide_scared', 'scared', (f // 3) % 2), hx, y + 9)
    elif f < 48:
        lit = (f // 4) % 2
        paste(frame, art('wide_flash' if lit else 'wide_scared', 'flash' if lit else 'scared', (f // 3) % 2), hx, y + 9)
    elif f < 62:  # eaten: only the points stay a moment
        pixel_text(draw, (x + 60, y + 17), str(points), scale=1, color=(0, 255, 255), align='center')
    elif f < 70:  # the eyes rush home, the fastest thing in the scene
        paste(frame, art('eaten', 'none'), hx, lerp(y + 9, hy, (f - 62) / 7))
    else:
        paste(frame, art('eaten', 'none'), hx, hy)
        if f >= 78:
            star(draw, x + 60, y + 28, 1)


def event_scene(kind, provider, streak=1):
    """The one-off scene for `kind` ('reset' or 'full') starring `provider`; `streak` is how many periods in a row
    it has used its whole limit (Anti's points double with each: 200, 400, 800, 1600)."""
    happy = kind == 'reset'

    def scene(frame, draw, box, f, s, plan=None):
        x, y, w, h = box
        u = s / 2
        if provider == 'claude':
            ground, foot = clawd_ground(frame, draw, box, f, s)
            if happy:
                clips = [('Excited', 2, 21), ('DancingHappy', 4, 38), ('Excited', 2, 21), ('DancingHappy', 4, 38)]
                fireworks(draw, box, f, s)
                place_clawd(frame, *timeline(f, clips), s, foot, ground)
            elif f < 44:  # worn out: it staggers, swaying from side to side
                name, index = timeline(f, [('Disappointed', 2, 21), ('Dizzy', 2, 25)])
                place_clawd(frame, name, index, s, foot + round(math.sin(f / 3) * 2 * s), ground)
            else:  # then flops flat and lies there breathing hard, with a little star: it did use it all
                t = f - 44
                art = arcade.clawd('Dizzy', 25, s)
                art = art.crop(art.getbbox())
                fall, breath = min(1, t / 6), s if (t // 8) % 2 else 0
                flat = art.resize((round(art.width * (1 + .3 * fall)), max(1, round(art.height * (1 - .5 * fall)) + breath)),
                                  arcade.Image.Resampling.NEAREST)
                paste(frame, flat, foot - flat.width / 2, ground - flat.height)
                if t >= 8:
                    sweat(draw, foot + flat.width // 2, ground - flat.height - 3 * s, max(1, s - 1), f)
                    if (t // 6) % 3:
                        star(draw, foot - flat.width // 2 - 2 * s, ground - flat.height - 6 * s, s)
        elif provider == 'codex':
            ground = arcade.garden_backdrop(draw, box, f, s)
            cx, mid, cw, ch = codex_place(box, s)
            if happy:
                fireworks(draw, box, f, s)
                lift = round(hop(f, 12, 6 * s))
                cloud = arcade.codex_art(s, 'happy', 'smile', 1 if f % 12 == 0 else 0)
                paste(frame, cloud, cx - cloud.width / 2, mid - cloud.height / 2 - lift)
            else:  # out of breath: heaving fast, gasping through an 'o', puffs of breath, sweat
                beat = f % 6
                cloud = arcade.codex_art(s, 'closed', 'open' if beat < 3 else 'long', (1, 2, 1, 0, -1, 0)[beat])
                low = mid + 4 * s
                paste(frame, cloud, cx - cloud.width / 2, low - cloud.height / 2)
                for k in range(2):  # each gasp breathes out a little puff that drifts off and fades
                    t = (f + k * 3) % 6
                    if t < 4:
                        arcade.puff(draw, round(cx + cw * .22 + t * 4 * s), round(low + ch * .08 - t * s),
                                    max(1, round((4 - t) * s * .8)))
                for k, side in enumerate((-1, 1)):
                    t = (f + k * 10) % 20
                    if t < 11:
                        p = t / 10
                        arcade.sweat_drop(draw, round(cx + side * (cw * .25 + p * 6 * s)),
                                          round(low - ch * .45 - 4 * p * (1 - p) * 6 * s + p * p * 4 * s), s)
        elif provider == 'grok':
            u, ground, deck, hr, rx, rest_art, gsize, gx0, sep = arcade.grok_backdrop(draw, box, f, s)
            arcade.draw_stage(frame, draw, rx, deck, hr, u, ('left', 'centre', 'right'), 0, 0, 'empty', 0, 0, 1, 0, f)
            if happy:
                fireworks(draw, box, f, s)
                lift = hop(f, 10, 14 * u)
                art = arcade.grok_pose(gsize, 'open', 2 if f % 10 == 0 else 0)
                paste(frame, art, gx0 - art.width / 2, ground - art.height - lift)
            else:  # out of fuel: the rocket only coughs smoke, Grok is dizzy
                if f % 20 < 6:
                    arcade.puff(draw, rx, deck - 2 * u, round((2 + f % 20) * u))
                art = arcade.grok_pose(gsize, 'dizzy', 1)
                paste(frame, art, gx0 - art.width / 2, ground - art.height)
                sweat(draw, round(gx0 + gsize * .45), ground - gsize, max(1, s - 1), f)
        elif provider == 'antigravity':
            anti_event(frame, draw, box, f // 2, happy, 200 * 2 ** (min(4, max(1, streak)) - 1), arcade.anti_left(plan))
        else:  # copilot
            arcade.copilot_backdrop(draw, box, f, s)
            base_y = y + round(h * .78)
            arcade.cloud(draw, x + round(w * .5), base_y, max(5, round(14 * u)))
            if happy:
                fireworks(draw, box, f, s)
                head = arcade.copilot_pose(max(10, round(arcade.COPILOT_HEAD * s)))
                lift = hop(f, 12, 12 * u)
                paste(frame, head, x + round(w * .5 - head.width / 2), base_y - head.height - round(4 * u) - lift)
            else:  # the plane sputters down onto the cloud
                p = min(1, f / 60)
                art = arcade.plane(u, (f // 3) % 2)
                px_ = x + round(w * (.2 + .3 * p) - art.width / 2)
                py_ = round(y + h * .2 + (base_y - art.height - y - h * .2) * p) + (s if f % 6 < 3 and p < 1 else 0)
                if f % 8 < 4:
                    arcade.puff(draw, px_ + art.width - round(4 * u), py_ + round(12 * u), round(3 * u))
                head = arcade.copilot_pose(max(8, round(17 * u)), 'shut')
                paste(frame, head, px_ + round(30 * u) - head.width / 2, py_ + round(17 * u) - head.height)
                paste(frame, art, px_, py_)
    return scene
