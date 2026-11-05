"""v2 phase 3b, x8: Arcade's seasonal props (token_tv/seasons.py). On Halloween (10-25 to 11-01), Christmas (12-18 to
12-26) and Seollal (the day before the Korean lunar new year to the day after), endpoints included, on the computer's
local date, Arcade's scenes get their season's scenery and every pet its hat; the pets keep their form, every gauge
stays clear, the one-offs are drawn as ever, other faces are untouched, and off season Arcade is byte for byte as it
was. Through live.main, the season comes in with the next ordinary picture at a loop's end, one upload, and an
interior date of the same season sends nothing."""
import datetime
import io
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import Rig  # noqa: E402

from token_tv import arcade, claude_moments, display, pet_moments, readout, seasons  # noqa: E402
from token_tv.display import STYLES, render_page  # noqa: E402
from token_tv.moments import loop_end  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402

PETS = ('claude', 'codex', 'grok', 'copilot', 'antigravity')
WINDOWS = {'claude': [('5H', 42, 2 * H), ('WEEK', 64, 3 * D)], 'codex': [('WEEK', 36, 4 * D)],
           'grok': [('BUDGET', 61, 6 * D + 2 * H)], 'copilot': [('MONTH', 40, 12 * D)], 'antigravity': [('5H', 30, 3 * H)]}
# Independently pinned (ko.wikipedia 설날 (한국) for 2026-2030; KASI's lunar-to-solar conversion for 2031-2040, each the
# KST day of a new moon by Meeus's algorithm; read 2026-11-05): the Korean lunar new year, not China's (a day earlier in
# 2027 and 2028).
LUNAR_NEW_YEAR = {2026: (2, 17), 2027: (2, 7), 2028: (1, 27), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23), 2032: (2, 11),
                  2033: (1, 31), 2034: (2, 19), 2035: (2, 8), 2036: (1, 28), 2037: (2, 15), 2038: (2, 4), 2039: (1, 24),
                  2040: (2, 12)}
HAT_INK = {'halloween': seasons.WITCH_INK['K'], 'christmas': seasons.SANTA_INK['R'], 'seollal': seasons.CAP_INK['Y']}
SEASONS = ('halloween', 'christmas', 'seollal')
SENTINEL = (1, 2, 3)


def local(y, m, d, hh=14, mm=1, ss=0):
    """That moment on this computer's own clock."""
    return time.mktime((y, m, d, hh, mm, ss, 0, 0, -1))


def account(provider, now, **row):
    key = f'{provider}_a'
    data = snapshot(now, [(key, f"{arcade.SHORT_NAME.get(provider, provider.upper())} A", provider, WINDOWS[provider])])
    data['accounts'][key].update(row)
    return data


def frames(data, now, season, egg=None):
    """Arcade's pictures of `data` at `now`, dressed for `season` (None: as ever) whatever `now`'s date is."""
    with mock.patch.object(seasons, 'season_at', lambda at=None: season):
        return arcade.arcade_frames(data, now, egg)


def gif(data, now, season, egg=None):
    with mock.patch.object(seasons, 'season_at', lambda at=None: season):
        return arcade.render_arcade(data, now, egg=egg)


def palette(season):
    """Every colour the season's props are drawn in: its hats, its scenery, the snow, the kite's line, the little cloud
    Copilot's tree and pouch stand on."""
    names = {'halloween': ('witch', 'witch_small', 'pumpkin', 'pumpkin_small', 'bat_up', 'bat_down'),
             'christmas': ('santa', 'santa_small', 'tree'), 'seollal': ('cap', 'cap_small', 'pouch', 'kite', 'yut')}[season]
    inks = {tuple(colour) for name in names for colour in seasons.PROP_INK[name].values()}
    return inks | {seasons.SNOW, seasons.SNOW_FAR, seasons.STRING, arcade.CLOUD_TOP, arcade.CLOUD_BASE}


def stage(frame):
    """The scene's own 120 x 71 stage in a 240 x 240 picture (Arcade doubles it), back at one pixel a cell."""
    return frame.crop((0, 28, 240, 170)).resize((120, 71), Image.Resampling.NEAREST)


def changed(a, b):
    """The colours `b` has where it differs from `a` (same size)."""
    mask = ImageChops.difference(a, b).point(lambda v: 255 if v else 0).convert('L').point(lambda v: 255 if v else 0)
    only = Image.composite(b, Image.new('RGB', b.size, SENTINEL), mask)
    return {c for _, c in only.getcolors(1 << 16)} - {SENTINEL}


def count(image, colour):
    return sum(n for n, c in image.convert('RGB').getcolors(1 << 16) if c == colour)


class Frozen:
    """The time module at one instant, for faces that read the time themselves."""
    def __init__(self, at):
        self.at = at

    def time(self):
        return self.at

    def __getattr__(self, name):
        return getattr(time, name)


class SeasonDatesTests(unittest.TestCase):
    def test_halloween_and_christmas_take_in_every_date_through_their_last_in_any_year(self):
        for year in (2026, 2027, 2031):
            for name, (first, last) in (('halloween', ((10, 25), (11, 1))), ('christmas', ((12, 18), (12, 26)))):
                day = datetime.date(year, *first)
                self.assertIsNone(seasons.season_on(day - datetime.timedelta(days=1)))
                while (day.month, day.day) <= last:
                    self.assertEqual(seasons.season_on(day), name, day)
                    day += datetime.timedelta(days=1)
                self.assertIsNone(seasons.season_on(day), day)  # the day after the last

    def test_seollal_is_the_day_before_the_korean_lunar_new_year_to_the_day_after(self):
        for year, (month, day) in LUNAR_NEW_YEAR.items():
            new_year = datetime.date(year, month, day)
            for offset in (-1, 0, 1):
                self.assertEqual(seasons.season_on(new_year + datetime.timedelta(days=offset)), 'seollal')
            for offset in (-2, 2):
                self.assertIsNone(seasons.season_on(new_year + datetime.timedelta(days=offset)))
        # China's comes a day earlier in 2027 and 2028: its first day is no Seollal here, Korea's last day is
        self.assertIsNone(seasons.season_on(datetime.date(2027, 2, 5)))
        self.assertEqual(seasons.season_on(datetime.date(2027, 2, 8)), 'seollal')
        self.assertIsNone(seasons.season_on(datetime.date(2028, 1, 25)))
        self.assertEqual(seasons.season_on(datetime.date(2028, 1, 28)), 'seollal')
        # a year's own date: last year's month and day mean nothing in the next
        self.assertIsNone(seasons.season_on(datetime.date(2027, 2, 17)))
        self.assertIsNone(seasons.season_on(datetime.date(2028, 2, 7)))
        # every year through 2040 has its three days, and only those; past the table, none
        for year in range(2026, 2041):
            days = [day for day in (datetime.date(year, 1, 1) + datetime.timedelta(n) for n in range(366))
                    if day.year == year and seasons.season_on(day) == 'seollal']
            self.assertEqual(days, [datetime.date(year, *LUNAR_NEW_YEAR[year]) + datetime.timedelta(n) for n in (-1, 0, 1)])
        self.assertIsNone(seasons.season_on(datetime.date(2041, 2, 1)))  # (2041's is Feb 1: no line, no Seollal props)

    def test_a_season_starts_at_local_midnight_and_ends_at_the_last_second_of_its_last_date(self):
        for (y, m, d), name in (((2026, 10, 25), 'halloween'), ((2026, 12, 18), 'christmas'), ((2027, 2, 6), 'seollal')):
            self.assertIsNone(seasons.season_at(local(y, m, d, 0, 0, 0) - 1))
            self.assertEqual(seasons.season_at(local(y, m, d, 0, 0, 0)), name)
        for (y, m, d), name in (((2026, 11, 1), 'halloween'), ((2026, 12, 26), 'christmas'), ((2027, 2, 8), 'seollal')):
            self.assertEqual(seasons.season_at(local(y, m, d, 23, 59, 59)), name)
            self.assertIsNone(seasons.season_at(local(y, m, d, 23, 59, 59) + 1))

    @unittest.skipUnless(hasattr(time, 'tzset'), 'needs a settable time zone')
    def test_the_date_is_this_computers_own_not_utcs(self):
        self.addCleanup(time.tzset)  # (runs once the patched TZ is gone again)
        at = datetime.datetime(2026, 10, 24, 15, 30, tzinfo=datetime.timezone.utc).timestamp()  # 10-25 00:30 in Seoul
        gone = datetime.datetime(2026, 11, 1, 15, 30, tzinfo=datetime.timezone.utc).timestamp()  # 11-02 00:30 there
        for zone, first, second in (('Asia/Seoul', 'halloween', None), ('UTC', None, 'halloween')):
            with mock.patch.dict(os.environ, {'TZ': zone}), mock.patch.object(arcade, 'NIGHT_HOURS', ()):
                time.tzset()
                self.assertEqual((seasons.season_at(at), seasons.season_at(gone)), (first, second), zone)
                self.assertEqual(bool(count(stage(arcade.arcade_frames(account('claude', at), at)[0]),
                                            HAT_INK['halloween'])), first == 'halloween', zone)
            time.tzset()


class OffSeasonTests(unittest.TestCase):
    """Off season, Arcade is as it was: no season code draws a thing, and the pets' tags change no pixel."""
    SCENES = [{}, {'active': True}, {'worry': True}, {'moment': {'kind': 'drink'}}, {'moment': {'kind': 'stretch'}},
              {'moment': {'kind': 'done', 'at': 5}}]
    CLAWD = [{'moment': {'kind': k}} for k in ('pet', 'snack', 'calm', 'failed', 'compact', 'rude')] + [
        {'moment': {'kind': 'needs', 'since': 0, 'level': 3}}, {'moment': {'kind': 'risky', 'style': 'verdict'}},
        {'moment': {'kind': 'risky', 'style': 'objection'}}, {'moment': {'kind': 'deleted', 'style': 'wave'}},
        {'word': 'PONDERING', 'active': True}]

    def renders(self, now):
        out = []
        for provider in PETS:
            for row in self.SCENES + (self.CLAWD if provider == 'claude' else []):
                out.append(arcade.render_arcade(account(provider, now, **row), now))
        return out

    def test_on_any_other_date_no_season_code_draws_anything(self):
        drew = []
        with mock.patch.object(seasons, 'scenery', lambda *a: drew.append('scenery')), \
                mock.patch.object(seasons, 'wear', lambda *a: drew.append('wear')):
            for now in (local(2026, 10, 24, 23, 59, 59), local(2026, 11, 2, 0, 0, 0), local(2026, 12, 17),
                        local(2026, 12, 27), local(2027, 2, 5), local(2027, 2, 9), local(2027, 6, 1)):
                self.renders(now)
            self.assertEqual(drew, [])
            arcade.render_arcade(account('claude', local(2026, 12, 25)), local(2026, 12, 25))  # a positive control
            self.assertIn('scenery', drew)
            self.assertIn('wear', drew)

    def test_the_pets_tags_change_no_pixel(self):
        now = local(2027, 6, 1)
        cached = (arcade.clawd, arcade.clawd_spun, arcade.codex_art, arcade.grok_pose, arcade.copilot_pose,
                  arcade.anti_art, pet_moments.clawd_art, pet_moments.leaning, pet_moments.taller, claude_moments.art,
                  claude_moments.robed)

        def clear():
            for build in cached:
                build.cache_clear()
        self.addCleanup(clear)
        tagged = self.renders(now)
        clear()
        with mock.patch.object(arcade, 'tag', lambda art, pet: art):
            untagged = self.renders(now)
        clear()
        self.assertEqual(tagged, untagged)


class InSeasonTests(unittest.TestCase):
    NOW = local(2026, 11, 5, 14, 1)  # a day-time instant; each season is put on by hand, so the moves are the same

    def test_only_props_are_added_and_the_header_and_readout_stay_as_they_are(self):
        for season in SEASONS:
            inks = palette(season)
            for provider in PETS:
                for row in ({}, {'active': True}, {'moment': {'kind': 'drink'}}):
                    plain = frames(account(provider, self.NOW, **row), self.NOW, None)
                    dressed = frames(account(provider, self.NOW, **row), self.NOW, season)
                    self.assertEqual(len(plain), len(dressed))
                    seen = set()
                    for a, b in zip(plain, dressed):
                        self.assertEqual(a.crop((0, 0, 240, 28)).tobytes(), b.crop((0, 0, 240, 28)).tobytes())
                        self.assertEqual(a.crop((0, 170, 240, 240)).tobytes(), b.crop((0, 170, 240, 240)).tobytes())
                        seen |= changed(stage(a), stage(b))
                    self.assertTrue(seen, (season, provider, row))
                    self.assertLessEqual(seen, inks, (season, provider, row))

    def test_clawds_body_under_its_hats_brim_is_its_own(self):
        """Clawd standing still: below the top two rows of its head every pixel of its own is where it was (the hat
        sits on top; at Seollal only the kite's line starts in its hand)."""
        body = {tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in arcade.clawd_data()['LookingAround']['palette']}
        for season in SEASONS:
            plain = stage(frames(account('claude', self.NOW), self.NOW, None)[0])
            dressed = stage(frames(account('claude', self.NOW), self.NOW, season)[0])
            spots = [(x, y) for y in range(71) for x in range(60) if plain.getpixel((x, y)) in body]
            top = min(y for _, y in spots)
            for x, y in spots:
                if y >= top + 2 and dressed.getpixel((x, y)) != plain.getpixel((x, y)):
                    self.assertEqual((season, dressed.getpixel((x, y))), ('seollal', seasons.STRING), (x, y))

    def test_every_pet_wears_its_seasons_hat_through_its_usual_scene_and_its_moments(self):
        moments = {'claude': ['pet', 'snack', 'drink', 'stretch', 'done', 'needs', 'calm', 'failed', 'compact', 'rude',
                              ('deleted', 'wave'), ('risky', 'objection')],
                   'codex': ['drink', 'stretch', 'done'], 'grok': ['drink', 'stretch'], 'copilot': ['drink', 'stretch'],
                   'antigravity': ['drink', 'stretch']}
        for season in SEASONS:
            for provider in PETS:
                for kind in [None, 'active'] + moments[provider]:
                    row = {} if kind is None else {'active': True} if kind == 'active' else \
                        {'moment': {'kind': kind[0], 'style': kind[1]}} if isinstance(kind, tuple) else \
                        {'moment': {'kind': kind, 'at': self.NOW, 'since': self.NOW - 1000, 'level': 3}}
                    pictures = frames(account(provider, self.NOW, **row), self.NOW, season)
                    if (provider, kind) == ('copilot', 'active'):  # it flies in from off the stage and out again
                        pictures = pictures[len(pictures) // 5:len(pictures) * 4 // 5]
                    hatted = sum(1 for f in pictures if count(stage(f), HAT_INK[season]))
                    # (a bow's tilt or a leap may hide it a picture or two)
                    self.assertGreater(hatted, len(pictures) * .8, (season, provider, kind))

    def test_judge_clawd_keeps_its_wig_and_the_clawd_in_the_dock_wears_the_hat(self):
        for season in SEASONS:
            pictures = frames(account('claude', self.NOW, moment={'kind': 'risky', 'style': 'verdict'}), self.NOW, season)
            for f in pictures:
                s = stage(f)
                self.assertTrue(count(s.crop((0, 0, 60, 71)), HAT_INK[season]), season)
                self.assertFalse(count(s.crop((66, 0, 120, 71)), HAT_INK[season]), season)

    def test_a_pet_turned_past_30_degrees_waits_for_its_hat_till_it_is_upright(self):
        for turn, hat in ((0, True), (20, True), (-28, True), (45, False), (315, False), (180, False), (350, True)):
            frame = Image.new('RGB', (120, 71), (0, 0, 0))
            art = arcade.rotsprite(arcade.clawd('LookingAround', 0, 1), turn) if turn else arcade.clawd('LookingAround', 0, 1)
            seasons.wear(seasons.Dress('christmas', 'claude', 0, 120, False, 4, frame), frame, art, 40, 30)
            self.assertEqual(bool(count(frame, HAT_INK['christmas'])), hat, turn)
        frame = Image.new('RGB', (120, 71), (0, 0, 0))  # another pet's art in this scene: none of its business
        seasons.wear(seasons.Dress('christmas', 'codex', 0, 120, False, 4, frame), frame,
                     arcade.clawd('LookingAround', 0, 1), 40, 30)
        self.assertFalse(count(frame, HAT_INK['christmas']))

    def test_no_scenery_covers_a_gauge(self):
        """Every pixel of each pet's gauge (in its gauge's colours, where the gauge is) is the same with the season's
        scenery. (A hat goes where its pet goes: Anti on patrol passes over its corner pellets, as it always has.)"""
        gauges = {'claude': ((97, 0, 120, 28), {arcade.MOON_LIT, arcade.MOON_DARK, arcade.LABEL_INK}),
                  'codex': ((0, 40, 120, 71), {arcade.STEM, arcade.LEAF, arcade.BUD, arcade.PETAL, arcade.HEART,
                                               arcade.PLOT}),
                  'grok': ((0, 30, 20, 71), {arcade.TANK, arcade.TANK_DARK, arcade.FUEL, arcade.FUEL_TOP,
                                             arcade.FUEL_LOW, arcade.LABEL_INK}),
                  'copilot': ((0, 0, 120, 23), {arcade.CLOUD_TOP, arcade.CLOUD_BASE, arcade.CLOUD_SPOT}),
                  'antigravity': ((0, 0, 120, 71), {arcade.MAZE_DOT, (90, 70, 80)})}
        pellets = [(10, 14, 21, 25), (100, 14, 111, 25), (100, 46, 111, 57), (10, 46, 21, 57)]
        for season in SEASONS:
            for provider in PETS:
                box, inks = gauges[provider]
                for row in ({}, {'active': True}):
                    plain = frames(account(provider, self.NOW, **row), self.NOW, None)
                    with mock.patch.object(seasons, 'wear', lambda *a: None):
                        dressed = frames(account(provider, self.NOW, **row), self.NOW, season)
                    for a, b in zip(plain, dressed):
                        sa, sb = stage(a), stage(b)
                        for y in range(box[1], box[3]):
                            for x in range(box[0], box[2]):
                                if provider == 'antigravity' and not any(p[0] <= x < p[2] and p[1] <= y < p[3]
                                                                         for p in pellets):
                                    continue  # (the maze's dots are no gauge; its four pellets are)
                                if sa.getpixel((x, y)) in inks:
                                    self.assertEqual(sb.getpixel((x, y)), sa.getpixel((x, y)), (season, provider, x, y))

    def test_the_one_offs_are_drawn_as_ever(self):
        for season in SEASONS:
            for provider in PETS:
                for egg, used in ((f'reset@{provider}_a', None), (f'full@{provider}_a', 100)):
                    data = account(provider, self.NOW)
                    if used:
                        for w in data['accounts'][f'{provider}_a']['windows']:
                            w['used_percent'] = used
                    self.assertEqual(gif(data, self.NOW, season, egg), gif(data, self.NOW, None, egg), (season, egg))

    def test_other_faces_wear_nothing(self):
        data = snapshot(self.NOW)
        with mock.patch.object(display, 'time', Frozen(self.NOW)), mock.patch.object(readout, 'time', Frozen(self.NOW)):
            for style in STYLES:
                if style == 'arcade':
                    continue
                with mock.patch.object(seasons, 'season_at', lambda at=None: 'christmas'):
                    dressed = render_page(data, style=style)
                self.assertEqual(dressed, render_page(data, style=style), style)

    def test_a_seasons_gif_still_fits_on_the_clock(self):
        for season in SEASONS:
            for provider in PETS:
                for row in ({}, {'active': True}):
                    self.assertLessEqual(len(gif(account(provider, self.NOW, **row), self.NOW, season)), arcade.BUDGET)
            every = snapshot(self.NOW, [(f'{p}_a', 'A', p, WINDOWS[p]) for p in PETS])
            for row in every['accounts'].values():
                row['active'] = True
            self.assertLessEqual(len(gif(every, self.NOW, season)), arcade.BUDGET)

    def test_on_a_real_date_in_season_arcade_dresses_itself(self):
        for (y, m, d), season in (((2026, 10, 31), 'halloween'), ((2026, 12, 24), 'christmas'), ((2028, 1, 28), 'seollal')):
            now = local(y, m, d)
            self.assertEqual(arcade.render_arcade(account('claude', now), now), gif(account('claude', now), now, season))
            self.assertNotEqual(arcade.render_arcade(account('claude', now), now), gif(account('claude', now), now, None))


class SeasonOnTheClockTests(unittest.TestCase):
    """Through live.main on a fake SD_PRO: crossing into a season, its first ordinary picture brings the props at the
    loop's end, one switch and at most one upload (the usual picture may still be on the clock's album); an interior
    date of the same season, nothing; out of it, one switch back to the usual."""
    def test_the_season_comes_and_goes_with_the_date_at_a_loops_end_one_upload_each(self):
        days = [local(2026, 10, 24, 12, 1, 5), local(2026, 10, 25, 12, 1, 5), local(2026, 10, 26, 12, 1, 5),
                local(2026, 11, 1, 12, 1, 5), local(2026, 11, 2, 12, 1, 5)]
        days = [t + (1 - int(t // 60) % 6) % 6 * 60 for t in days]  # the same minute of keeping still in any zone
        rig = Rig(self, at=days[0], windows={'claude': [('5H', 40, 3 * H)]})
        shown, _ = rig.showing()
        self.assertEqual(count(Image.open(io.BytesIO(shown)), HAT_INK['halloween']), 0)
        polls = 1
        for k, day in enumerate(days[1:], 1):
            rig.frozen.at = day  # the drawings' and TokenTV's own date
            before, switched = len(rig.uploads()), len(rig.switches())
            showing, began = rig.showing()
            reading = rig.poll_at(polls)
            due = loop_end({'at': began, 'loop': rig.loop(showing)}, reading)
            rig.clock.to(due + rig.loop(showing) + .5)  # the reading, the loop's end and a loop more
            polls += 1
            image, on = rig.showing()
            wanted = seasons.season_on(datetime.date.fromtimestamp(day))
            previous = seasons.season_on(datetime.date.fromtimestamp(days[k - 1]))
            self.assertEqual(image, rig.picture(), day)
            self.assertEqual(bool(count(Image.open(io.BytesIO(image)), HAT_INK['halloween'])), wanted == 'halloween', day)
            self.assertEqual(len(rig.switches()) - switched, 0 if wanted == previous else 1, day)
            self.assertLessEqual(len(rig.uploads()) - before, 0 if wanted == previous else 1, day)
            if wanted != previous:
                self.assertGreaterEqual(on, due - 1e-6)  # at the end of the loop the clock was playing
                self.assertLess(on, due + .25)
            for _ in range(2):  # more readings, the same date: nothing more
                rig.clock.to(rig.poll_at(polls) + .5)
                polls += 1
            self.assertEqual(len(rig.switches()) - switched, 0 if wanted == previous else 1, day)
            self.assertLessEqual(len(rig.uploads()) - before, 0 if wanted == previous else 1, day)
        self.assertEqual(len(rig.uploads()), 2)  # the usual picture, Halloween's; the usual one again was still there


if __name__ == '__main__':
    unittest.main()
