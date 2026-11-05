"""v2 phase 3b, x7: the Survival face (token_tv/survival.py), as the owner approved it (style A, drafts w30-w32): a face to
pick like the others, one row per account (four at most), ten hearts for what is LEFT of the 5-hour window and ten
drumsticks for what is left of the week (else a month or a budget), half icons for 5%, a bar for today's use (full at
an even day, a second lap in orange), the pet small. A missing reading is a dash or a word, an old one says OLD, and
on the clock it changes only with the readings."""
import http.client
import io
import json
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir  # noqa: E402
from test_moments import Rig  # noqa: E402

from token_tv import readout, survival  # noqa: E402
from token_tv.catalog import theme_list  # noqa: E402
from token_tv.display import STYLES, pixel_text, render_page  # noqa: E402
from token_tv.live import DisplayPreferences, handler  # noqa: E402
from token_tv.sample import D, H, snapshot  # noqa: E402
from token_tv.sources import load_config  # noqa: E402
from token_tv.state import UsageStore  # noqa: E402

NOW = 1793854860  # 2026-11-05 14:01 KST
ROOT = Path(__file__).resolve().parent.parent
HEART, MEAT = survival.HEART, survival.MEAT


def data(*accounts):
    """A snapshot of (key, alias, provider, windows, extra row fields) accounts."""
    snap = snapshot(NOW, [a[:4] for a in accounts])
    for a in accounts:
        if len(a) > 4:
            snap['accounts'][a[0]].update(a[4])
    return snap


def face(snap):
    return survival.render_survival(snap, NOW)


def icon_states(image, x0, y, ink, count=10, pitch=16):
    """Each icon from (x0, y), 'full', 'half' or 'spent', by the colour of its right and its left part."""
    out = []
    for k in range(count):
        x = x0 + k * pitch
        right = {image.getpixel((x + dx, y + dy)) for dx in (10, 11, 12) for dy in (4, 5, 6)}
        left = {image.getpixel((x + dx, y + dy)) for dx in (4, 5, 6) for dy in (4, 5, 6)}
        out.append('full' if ink in right else 'half' if ink in left else
                   'spent' if survival.EMPTY in left | right else 'none')
    return out


def says(test, image, xy, text, scale=1, align='left', colour=None):
    """`text` is drawn at `xy` in the clock's pixel font, nothing else in its box (and in `colour`, if given)."""
    probe = Image.new('RGB', image.size, (0, 0, 0))
    pixel_text(ImageDraw.Draw(probe), xy, text, scale=scale, color=(255, 255, 255), align=align)
    box = probe.getbbox()
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            got = image.getpixel((x, y))
            if probe.getpixel((x, y)) != (0, 0, 0):
                test.assertNotEqual(got, survival.PANEL, (text, x, y))
                if colour:
                    test.assertEqual(got, colour, (text, x, y))
            else:
                test.assertEqual(got, survival.PANEL, (text, x, y))


def stripe(image, box):
    return {image.getpixel((x, y)) for y in range(box[1], box[3]) for x in range(box[0], box[2])}


class FaceTests(unittest.TestCase):
    def test_survival_is_a_face_to_pick_like_the_others(self):
        self.assertIn('survival', STYLES)
        image = Image.open(io.BytesIO(render_page(snapshot(NOW), style='survival')))
        self.assertEqual((image.format, image.size), ('JPEG', (240, 240)))
        listed = {t['id']: t for t in theme_list()['themes']}['survival']
        self.assertEqual((listed['name'], listed['local'], listed['installed'], listed['needs_update']),
                         ('Survival HUD', False, True, False))
        self.assertNotIn('minecraft', json.dumps(listed).lower())
        self.assertIn("s === 'survival' ? 'Survival HUD'", (ROOT / 'token_tv' / 'web' / 'app.js').read_text(encoding='utf-8'))

    def test_the_dashboard_previews_applies_and_keeps_it_as_it_does_every_face(self):
        account = {'key': 'a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'owner@example.com'}
        row = dict(account, status='ok', windows=[{'label': 'WEEK', 'used_percent': 30, 'resets_at': None}], fetched_at=100)
        store = UsageStore([account], fetch=lambda a: dict(row))
        store.refresh()
        path = temp_dir(self) / 'config.json'
        path.write_text(json.dumps({'accounts': [account], 'display_style': 'arcade'}), encoding='utf-8')
        prefs = DisplayPreferences(path, load_config(path))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(store, prefs))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/frame/0.jpg?style=survival') as response:  # a preview changes nothing
            self.assertEqual(Image.open(io.BytesIO(response.read())).size, (240, 240))
        self.assertEqual(prefs.snapshot()['style'], 'arcade')
        with urlopen(root + '/display') as response:
            self.assertIn('survival', json.load(response)['styles'])
        request = Request(root + '/display/style', data=b'{"style":"survival"}', headers={'Content-Type': 'application/json'})
        with urlopen(request) as response:
            self.assertEqual(json.load(response)['style'], 'survival')
        self.assertEqual(load_config(path)['display_style'], 'survival')
        self.assertEqual(DisplayPreferences(path, load_config(path)).snapshot()['style'], 'survival')  # after a restart

    def test_hearts_are_what_is_left_of_the_5_hours_and_hunger_of_the_week(self):
        for five, week in ((25, 75), (75, 25)):
            image = face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', five, 2 * H), ('WEEK', week, 3 * D)])))
            left5, leftw = (100 - five) / 10, (100 - week) / 10  # icons: whole ones, then a half
            self.assertEqual(icon_states(image, 30, 110, HEART), ['full'] * int(left5) + ['half'] + ['spent'] * (9 - int(left5)))
            self.assertEqual(icon_states(image, 30, 148, MEAT), ['full'] * int(leftw) + ['half'] + ['spent'] * (9 - int(leftw)))
            says(self, image, (230, 111), f'{100 - five}%', 2, 'right', survival.TEXT)
            says(self, image, (230, 149), f'{100 - week}%', 2, 'right', survival.TEXT)
            says(self, image, (10, 114), '5H', colour=survival.MUTED)
            says(self, image, (10, 152), 'WK', colour=survival.MUTED)
        swapped = face(data(('claude_a', 'CLAUDE A', 'claude', [('WEEK', 75, 3 * D), ('5H', 25, 2 * H)])))
        self.assertEqual(swapped.tobytes(), face(data(('claude_a', 'CLAUDE A', 'claude',
                                                       [('5H', 25, 2 * H), ('WEEK', 75, 3 * D)]))).tobytes())

    def test_icons_step_in_halves_and_never_say_empty_while_anything_is_left(self):
        for used, states in ((0, ['full'] * 10), (100, ['spent'] * 10), (99.5, ['half'] + ['spent'] * 9),
                             (96, ['half'] + ['spent'] * 9), (94, ['half'] + ['spent'] * 9), (92, ['full'] + ['spent'] * 9),
                             (50, ['full'] * 5 + ['spent'] * 5),
                             (47, ['full'] * 5 + ['half'] + ['spent'] * 4)):
            image = face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', used, 2 * H)])))
            self.assertEqual(icon_states(image, 30, 110, HEART), states, used)
        full = face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', 0, 2 * H)])))
        says(self, full, (236, 111), '100%', 2, 'right', survival.TEXT)  # clear of the tenth heart

    def test_hunger_is_the_week_by_its_length_and_else_a_month_or_a_budget_with_its_name(self):
        alias = data(('codex_a', 'CODEX A', 'codex', [('5H', 50, 2 * H), ('WINDOW', 20, 3 * D)]))
        alias['accounts']['codex_a']['windows'][1]['duration_minutes'] = 10080
        image = face(alias)
        self.assertEqual(icon_states(image, 30, 148, MEAT), ['full'] * 8 + ['spent'] * 2)
        says(self, image, (10, 152), 'WK', colour=survival.MUTED)
        grok = face(data(('grok_a', 'GROK A', 'grok', [('BUDGET', 61, 6 * D)])))
        self.assertEqual(icon_states(grok, 30, 110, MEAT), ['full'] * 4 + ['spent'] * 6)  # its only row (39%: 4)
        says(self, grok, (10, 114), 'BUD', colour=survival.MUTED)
        self.assertNotIn(HEART, stripe(grok, (0, 100, 240, 196)))  # no hearts made up for it
        anti = face(data(('antigravity_a', 'ANTI A', 'antigravity', [('5H', 30, 3 * H)])))
        self.assertEqual(icon_states(anti, 30, 110, HEART), ['full'] * 7 + ['spent'] * 3)
        self.assertNotIn(MEAT, stripe(anti, (0, 100, 240, 196)))
        mixed = face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', 50, 2 * H), ('WEEK', 50, 3 * D)]),
                          ('codex_a', 'CODEX A', 'codex', [('5H', 50, 2 * H), ('MONTH', 50, 9 * D)]),
                          ('grok_a', 'GROK A', 'grok', [('BUDGET', 50, 6 * D)])))
        says(self, mixed, (236, 80 + 31 + 4), 'MO', align='right', colour=survival.MUTED)  # a month beside 5 hours: named
        self.assertEqual(stripe(mixed, (220, 31 + 4, 240, 31 + 11)), {survival.PANEL})  # a week beside them: not

    def test_an_account_with_no_reading_says_why_and_an_old_one_says_old(self):
        login = face(data(('claude_a', 'CLAUDE A', 'claude', [], {'status': 'auth_required'})))
        says(self, login, (30, 111), 'LOGIN', 2, colour=survival.WARN)
        self.assertNotIn(HEART, stripe(login, (0, 100, 240, 196)))
        old = face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', 40, 2 * H)], {'status': 'stale'})))
        says(self, old, (230, 8), 'OLD', 2, 'right', survival.WARN)
        says(self, old, (230, 111), '60%', 2, 'right', survival.MUTED)
        two = face(data(('grok_a', 'GROK A', 'grok', [], {'status': 'quota_unavailable'}),
                        ('codex_a', 'CODEX A', 'codex', [('WEEK', 40, 3 * D)], {'status': 'stale'})))
        says(self, two, (230, 30), 'OLD', align='right', colour=survival.WARN)  # Codex first, in service order
        says(self, two, (30, 120 + 51), 'NO DATA', 2, colour=survival.WARN)
        four = face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', 40, 2 * H)], {'status': 'stale'}),
                         ('claude_b', 'CLAUDE B', 'claude', [], {'status': 'auth_required'}),
                         ('codex_a', 'CODEX A', 'codex', [('WEEK', 40, 3 * D)]),
                         ('grok_a', 'GROK A', 'grok', [('BUDGET', 40, 3 * D)])))
        says(self, four, (234, 60 + 5), 'LOGIN', align='right', colour=survival.WARN)
        reset = '5H ' + readout.reset_clock(NOW + 2 * H, NOW)
        says(self, four, (234 - survival.width(reset) - 6, 5), 'OLD', align='right', colour=survival.WARN)

    def test_todays_bar_and_number_and_a_dash_while_it_is_not_known(self):
        def hero(today):
            extra = {} if today is None else {'today': today}
            return face(data(('claude_a', 'CLAUDE A', 'claude', [('5H', 40, 2 * H), ('WEEK', 40, 3 * D)], extra)))
        bar = (62, 200, 174, 208)
        self.assertEqual(stripe(hero(None), bar), {survival.TRACK})
        says(self, hero(None), (230, 198), '--', 2, 'right', survival.MUTED)
        self.assertEqual(stripe(hero(0.0), bar) - {survival.PANEL}, {survival.TRACK})  # (its quarter marks: panel)
        says(self, hero(0.0), (230, 198), '0%', 2, 'right', survival.TEXT)
        half = hero(.5)
        says(self, half, (230, 198), '50%', 2, 'right', survival.TEXT)
        self.assertIn(survival.GOLD, stripe(half, (62, 204, 117, 208)))
        self.assertEqual(stripe(half, (120, 204, 174, 208)) - {survival.PANEL}, {survival.TRACK})
        lap = hero(1.5)
        says(self, lap, (230, 198), '150%', 2, 'right', survival.TEXT)
        self.assertIn(survival.OVER, stripe(lap, (62, 204, 117, 208)))  # a second lap, orange, half way
        self.assertIn(survival.GOLD, stripe(lap, (120, 204, 174, 208)))
        self.assertNotIn(survival.OVER, stripe(lap, (120, 204, 174, 208)))
        rows = [(f'{p}_a', f'{p.upper()} A', p, [('WEEK', 40, 3 * D)], {} if p == 'codex' else {'today': .4})
                for p in ('claude', 'codex', 'grok')]
        three = face(data(*rows))
        says(self, three, (70, 80 + 47), '--', colour=survival.MUTED)  # Codex's day not known: a dash, no bar
        self.assertNotIn(survival.TRACK, stripe(three, (82, 80 + 49, 228, 80 + 53)))
        self.assertIn(survival.TRACK, stripe(three, (70, 47 + 2, 228, 47 + 6)))
        self.assertIn(survival.GOLD, stripe(three, (70, 47 + 2, 228, 47 + 6)))

    def test_every_account_gets_its_own_row_and_pet_four_at_most_the_busiest_first(self):
        rows = [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 10, 3 * D)]), ('claude_b', 'CLAUDE B', 'claude', [('WEEK', 20, 3 * D)]),
                ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)]), ('grok_a', 'GROK A', 'grok', [('BUDGET', 40, 3 * D)]),
                ('copilot_a', 'COPILOT A', 'copilot', [('MONTH', 50, 9 * D)], {'active': True})]
        image = face(data(*rows))
        names = ['CLAUDE B', 'CODEX A', 'GROK A', 'COPILOT A']  # the one at work, then the fullest; in service order
        for k, name in enumerate(names):
            says(self, image, (60, k * 60 + 5), name, colour=survival.TEXT)
        pets = {'claude': (217, 119, 87), 'grok': (242, 244, 248)}
        self.assertIn(pets['claude'], stripe(image, (0, 0, 56, 60)))
        self.assertIn(pets['grok'], stripe(image, (0, 120, 56, 180)))
        for k in range(4):
            self.assertGreaterEqual(len(stripe(image, (8, k * 60 + 8, 50, k * 60 + 58)) - {survival.PANEL}), 2, k)  # a pet
        mine = face(data(('claude_a', 'CLAUDE WORK LAPTOP', 'claude', [('5H', 40, 2 * H), ('WEEK', 40, 3 * D)]),
                         ('claude_b', 'CLAUDE B', 'claude', [('5H', 40, 2 * H), ('WEEK', 40, 3 * D)])))
        says(self, mine, (66, 10), 'WORK LAPTOP', 2, colour=survival.TEXT)
        says(self, mine, (66, 130), 'CLAUDE B', 2, colour=survival.TEXT)  # one service, two rows

    def test_a_long_name_is_cut_clear_of_what_stands_beside_it(self):
        reset = survival.width('5H ' + readout.reset_clock(NOW + 2 * H, NOW))
        names = {1: [(0, 0, 230 - survival.width('CLAWD', 2) - 4, 24)], 2: [(60, y0, 236, y0 + 26) for y0 in (0, 120)],
                 4: [(56, y0, 234 - reset - 6, y0 + 13) for y0 in (0, 60, 120, 180)]}  # where each name may go
        for count in (1, 2, 4):
            short = [(f'claude_{c}', f'CLAUDE {c.upper()}', 'claude', [('5H', 40, 2 * H), ('WEEK', 40, 3 * D)])
                     for c in 'abcd'[:count]]
            long_ = [(k, 'CLAUDE ' + 'VERYLONGNAME' * 3, p, w) for k, _, p, w in short]
            a, b = face(data(*short)), face(data(*long_))
            self.assertNotEqual(a.tobytes(), b.tobytes())
            for image in (a, b):
                for box in names[count]:
                    ImageDraw.Draw(image).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=(0, 0, 0))
            self.assertEqual(a.tobytes(), b.tobytes(), count)  # everything else as it was

    def test_the_same_readings_draw_the_same_picture(self):
        snap = data(('claude_a', 'CLAUDE A', 'claude', [('5H', 40, 2 * H), ('WEEK', 40, 3 * D)], {'today': .3}))
        self.assertEqual(render_page(snap, style='survival'), render_page(snap, style='survival'))
        snap['accounts']['claude_a']['windows'][0]['used_percent'] = 45
        self.assertNotEqual(face(snap).tobytes(), face(data(('claude_a', 'CLAUDE A', 'claude',
                                                             [('5H', 40, 2 * H), ('WEEK', 40, 3 * D)], {'today': .3}))).tobytes())


class ClockTests(unittest.TestCase):
    """Through live.main on a fake SD_PRO, picked on the dashboard as a person would."""
    def pick(self, rig, style):
        conn = http.client.HTTPConnection('127.0.0.1', rig.port, timeout=5)
        conn.request('POST', '/display/style', json.dumps({'style': style}), {'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 200)
        rig.clock.settle()

    def held_face(self, rig):
        return render_page(rig.held(), 0, 'survival')

    def test_on_the_clock_it_changes_with_the_readings_only(self):
        rig = Rig(self, providers=('codex',))  # (read every minute, as a Claude account is not)
        arcade, began = rig.showing()
        self.pick(rig, 'survival')
        due = rig.end_of_loop()
        rig.clock.to(due + .5)
        image, on = rig.showing()
        self.assertEqual(Image.open(io.BytesIO(image)).format, 'JPEG')
        self.assertEqual(image, self.held_face(rig))
        self.assertGreaterEqual(on, due - 1e-6)  # Arcade's loop played out first
        self.assertLess(on, due + .25)
        sent, switched = len(rig.uploads()), len(rig.switches())
        for n in range(1, 4):  # readings with nothing new: nothing sent
            rig.clock.to(rig.poll_at(n) + .5)
        rig.say('claude.ask')  # an agent's moment is Arcade's: nothing here either
        rig.clock.to(rig.clock.now() + 30)
        self.assertEqual((len(rig.uploads()), len(rig.switches())), (sent, switched))
        rig.set('codex_a', 'WEEK', 55)  # a new reading: one picture, at once (a still face has no loop to wait for)
        rig.write()
        rig.clock.to(rig.poll_at(4) + .5)
        self.assertEqual(len(rig.uploads()), sent + 1)
        image, on = rig.showing()
        self.assertEqual(image, self.held_face(rig))
        self.assertLess(on, rig.poll_at(4) + .25)
        kept = json.loads((rig.state / 'snapshot.json').read_text(encoding='utf-8'))['accounts']['codex_a']['day']
        self.assertEqual(kept['used'], 55)  # today's use goes into the state folder with the snapshot
        self.pick(rig, 'arcade')  # and back: Arcade as before
        rig.clock.to(rig.clock.now() + 1)
        self.assertEqual(Image.open(io.BytesIO(rig.showing()[0])).format, 'GIF')


if __name__ == '__main__':
    unittest.main()
