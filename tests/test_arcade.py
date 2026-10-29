import io
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from token_tv import arcade
from token_tv.display import render_page
from token_tv.sample import D, H, snapshot
from token_tv.state import ACTIVE_SECONDS, MIN_FETCH_SECONDS, UsageStore

def sample(now, working=()):
    data = snapshot(now, [
        ('claude_a', 'CLAUDE A', 'claude', [('5H', 41, 2 * H), ('WEEK', 86, 3 * D)]),
        ('codex_a', 'CODEX A', 'codex', [('5H', 34, 2 * H)]),
        ('grok_a', 'GROK A', 'grok', [('BUDGET', 61, 6 * D)]),
    ])
    for key in working:
        data['accounts'][key]['active'] = True
    return data


def reply(key, provider, used, status='ok'):
    return {'key': key, 'alias': key.upper(), 'provider': provider, 'status': status, 'fetched_at': time.time(),
            'windows': [{'label': '5H', 'used_percent': used, 'resets_at': None}] if used is not None else []}


class WorkingTests(unittest.TestCase):
    def test_a_rise_in_used_percent_marks_the_account_working_until_it_settles(self):
        readings = [10, 10, 12, 0]
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}],
                           fetch=lambda _: reply('a', 'codex', readings.pop(0)))
        store.refresh()
        self.assertFalse(store.snapshot()['accounts']['a']['active'])  # the first reading has nothing to compare
        store.refresh()
        self.assertFalse(store.snapshot()['accounts']['a']['active'])  # unchanged
        store.refresh()
        self.assertTrue(store.snapshot()['accounts']['a']['active'])  # 10 → 12
        store.refresh()
        self.assertTrue(store.snapshot()['accounts']['a']['active'])  # a reset to 0 is not work, the last rise holds
        later = time.time() + ACTIVE_SECONDS + 1
        with patch('token_tv.state.time.time', return_value=later):
            self.assertFalse(store.snapshot()['accounts']['a']['active'])

    def test_errors_and_missing_readings_never_count_as_work(self):
        readings = [reply('a', 'codex', 10), reply('a', 'codex', None, 'error'), reply('a', 'codex', 10),
                    reply('a', 'codex', None, 'quota_unavailable')]
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}], fetch=lambda _: readings.pop(0))
        for _ in range(4):
            store.refresh()
            self.assertFalse(store.snapshot()['accounts']['a']['active'])

    def test_claude_is_read_at_most_every_five_minutes_while_others_follow_the_poll(self):
        calls = []

        def fetch(account):
            calls.append(account['key'])
            return reply(account['key'], account['provider'], 10)
        accounts = [{'key': 'c', 'alias': 'C', 'provider': 'claude'}, {'key': 'x', 'alias': 'X', 'provider': 'codex'}]
        store = UsageStore(accounts, fetch=fetch, min_fetch_seconds=MIN_FETCH_SECONDS)
        clock = [1000.0]
        with patch('token_tv.state.time.monotonic', side_effect=lambda: clock[0]):
            for _ in range(5):  # one-minute polls
                store.refresh()
                clock[0] += 60
            self.assertEqual(calls.count('c'), 1)
            self.assertEqual(calls.count('x'), 5)
            store.refresh()  # five minutes after the first read
        self.assertEqual(calls.count('c'), 2)


class ArcadeFaceTests(unittest.TestCase):
    def test_animated_faces_fit_the_clock_and_equal_readings_give_equal_bytes(self):
        now = time.time()
        for style, render in (('arcade', arcade.render_arcade),):
            working = render(sample(now, ('claude_a', 'codex_a', 'grok_a')), now)
            idle = render(sample(now), now)
            for data in (working, idle):
                image = Image.open(io.BytesIO(data))
                self.assertEqual((image.format, image.size), ('GIF', (240, 240)))
                self.assertLess(len(data), 400000)  # the clock's GIF upload limit
            self.assertNotEqual(working, idle)
            self.assertEqual(render(sample(now), now), idle, style)  # unchanged clock is not rewritten
            image = Image.open(io.BytesIO(working))
            total = 0
            for index in range(image.n_frames):  # identical neighbours are merged, the loop keeps its length
                image.seek(index)
                total += image.info['duration']
            self.assertEqual(total, arcade.FRAMES * arcade.FRAME_MS)
            durations = set()
            for index in range(image.n_frames):
                image.seek(index)
                durations.add(image.info['duration'] % arcade.FRAME_MS)
            self.assertEqual(durations, {0})  # every frame the same length (merged ones a whole multiple): no judder

    def test_arcade_takes_turns_on_working_accounts_or_on_all_when_idle(self):
        now = time.time()
        self.assertEqual([r['provider'] for r in arcade.shown_rows(sample(now, ('codex_a',)))], ['codex'])
        self.assertEqual([r['provider'] for r in arcade.shown_rows(sample(now, ('claude_a', 'grok_a')))],
                         ['claude', 'grok'])
        self.assertEqual([r['provider'] for r in arcade.shown_rows(sample(now))], ['claude', 'codex', 'grok'])

    def test_each_scene_moves_only_while_working(self):
        now = time.time()
        for key in ('claude_a', 'codex_a', 'grok_a'):
            frames = arcade.arcade_frames(sample(now, (key,)), now)
            self.assertTrue(ImageChops.difference(frames[0], frames[7]).getbbox(), key)
        claude_only = lambda working: snapshot(now, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 63, 3 * D)])]) \
            if not working else dict(sample(now, ('claude_a',)), accounts={'claude_a': sample(now, ('claude_a',))['accounts']['claude_a']})
        idle = arcade.arcade_frames(claude_only(False), now)
        moving = arcade.arcade_frames(claude_only(True), now)
        ground = (0, 160, 240, 170)  # the dotted ground strip under Clawd's feet: it stands still either way
        stage = (0, 28, 240, 150)
        for frames in (idle, moving):
            self.assertIsNone(ImageChops.difference(frames[1].crop(ground), frames[7].crop(ground)).getbbox())
        self.assertTrue(ImageChops.difference(moving[1].crop(stage), moving[7].crop(stage)).getbbox())  # Clawd jogs

    def test_near_the_limit_each_character_frets_instead_of_its_usual_idle(self):
        now = time.time()
        for provider in ('claude', 'codex', 'grok', 'copilot'):
            def frames(used):
                data = snapshot(now, [(f'{provider}_a', 'A', provider, [('WEEK', used, 3 * D)])])
                return arcade.arcade_frames(data, now)
            calm, worried = frames(50), frames(95)
            scene = (0, 28, 240, 170)  # the stage only; the number differs anyway
            self.assertTrue(any(ImageChops.difference(calm[k].crop(scene), worried[k].crop(scene)).getbbox()
                                for k in (0, 5, 10)), provider)
            self.assertTrue(ImageChops.difference(worried[0], worried[5]).getbbox(), provider)  # fretting moves

    def test_reset_time_is_coarse_so_the_gif_changes_rarely(self):
        now = 1_000_000
        self.assertEqual(arcade.coarse_left(now + 3 * D + 5 * H, now), '3D')
        self.assertEqual(arcade.coarse_left(now + 5 * H + 59 * 60, now), '5H')
        self.assertEqual(arcade.coarse_left(now + 38 * 60, now), '38M')
        self.assertEqual(arcade.coarse_left(None, now), '--')

    def test_missing_services_and_logged_out_accounts_still_render(self):
        only_claude = snapshot(time.time(), [('claude_a', 'CLAUDE A', 'claude', [('5H', 72, 2 * H)])])
        logged_out = {'accounts': {'a': {'alias': 'CODEX A', 'provider': 'codex', 'status': 'auth_required', 'windows': []}}}
        for data in (only_claude, logged_out):
            for style in ('arcade',):
                self.assertEqual(render_page(data, style=style)[:4], b'GIF8')

    def test_a_loop_over_budget_drops_every_other_frame_but_keeps_its_length(self):
        now = time.time()
        with patch.object(arcade, 'BUDGET', 1000):
            data = arcade.render_arcade(sample(now, ('claude_a',)), now)
        image = Image.open(io.BytesIO(data))
        total = 0
        for index in range(image.n_frames):
            image.seek(index)
            total += image.info['duration']
        self.assertLessEqual(image.n_frames, arcade.FRAMES // 2)
        self.assertEqual(total, arcade.FRAMES * arcade.FRAME_MS)
        self.assertEqual(arcade.gif_seconds(data), arcade.LOOP_SECONDS)


class EventTests(unittest.TestCase):
    def test_a_window_that_resets_or_runs_out_is_an_event_once(self):
        readings = [60, 100, 100, 4]
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}],
                           fetch=lambda _: reply('a', 'codex', readings.pop(0)))
        store.refresh()
        self.assertIsNone(store.snapshot()['accounts']['a'].get('event'))
        store.refresh()
        row = store.snapshot()['accounts']['a']
        self.assertEqual(row['event'], 'full')  # 60 → 100
        first = row['event_at']
        store.refresh()
        self.assertEqual(store.snapshot()['accounts']['a']['event_at'], first)  # still full: no new event
        store.refresh()
        row = store.snapshot()['accounts']['a']
        self.assertEqual(row['event'], 'reset')  # 100 → 4
        self.assertGreaterEqual(row['event_at'], first)

    def test_event_scenes_render_for_every_service_and_only_for_their_account(self):
        now = time.time()
        for provider, label in (('claude', 'WEEK'), ('codex', 'WEEK'), ('grok', 'BUDGET'), ('copilot', 'MONTH')):
            data = snapshot(now, [(f'{provider}_a', provider.upper() + ' A', provider, [(label, 100, None)])])
            usual = render_page(data, style='arcade')
            for kind in ('reset', 'full'):
                image = render_page(data, style='arcade', egg=f'{kind}@{provider}_a')
                self.assertLess(len(image), 400000)
                self.assertNotEqual(image, usual, (provider, kind))
            self.assertEqual(render_page(data, style='arcade', egg='full@someone_else'), usual)


    def test_spending_a_saved_reset_is_a_reset_and_the_ticket_shows_in_the_header(self):
        from token_tv.usage import reset_credits
        reply_with = lambda count: {'rateLimitResetCredits': {'availableCount': count, 'credits': [
            {'status': 'available', 'expiresAt': 2_000_000_000}, {'status': 'used', 'expiresAt': 1_900_000_000}]}}
        self.assertEqual(reset_credits(reply_with(2)), {'count': 2, 'expires_at': 2_000_000_000})
        self.assertIsNone(reset_credits({'rateLimits': {}}))
        counts = [2, 2, 1]
        def fetch(_):
            row = reply('a', 'codex', 100)
            row['reset_credits'] = {'count': counts.pop(0), 'expires_at': None}
            return row
        store = UsageStore([{'key': 'a', 'alias': 'A', 'provider': 'codex'}], fetch=fetch)
        store.refresh()
        store.refresh()
        self.assertIsNone(store.snapshot()['accounts']['a'].get('event'))
        store.refresh()
        self.assertEqual(store.snapshot()['accounts']['a']['event'], 'reset')  # one ticket spent
        now = time.time()
        data = snapshot(now, [('codex_a', 'CODEX A', 'codex', [('WEEK', 47, 4 * D)])])
        plain = arcade.arcade_frames(data, now)
        data['accounts']['codex_a']['reset_credits'] = {'count': 1, 'expires_at': now + 20 * D}
        held = arcade.arcade_frames(data, now)
        header = (0, 0, 240, 28)
        self.assertTrue(ImageChops.difference(plain[0].crop(header), held[0].crop(header)).getbbox())
        self.assertIsNone(ImageChops.difference(held[0].crop(header), held[7].crop(header)).getbbox())
        data['accounts']['codex_a']['reset_credits'] = {'count': 1, 'expires_at': now + 2 * D}
        expiring = arcade.arcade_frames(data, now)  # steady red, no blinking
        self.assertTrue(ImageChops.difference(held[0].crop(header), expiring[0].crop(header)).getbbox())
        self.assertIsNone(ImageChops.difference(expiring[0].crop(header), expiring[7].crop(header)).getbbox())


class SpriteTests(unittest.TestCase):
    def test_clawd_poses_decode_like_the_game(self):
        data = arcade.clawd_data()
        for name, sheet in data.items():
            frames = arcade.clawd_frames(name)
            self.assertEqual(len(frames), len(sheet['deltas']) + 1, name)
            self.assertTrue(all(len(frame) == sheet['w'] * sheet['h'] for frame in frames), name)
        for name, first, last in list(arcade.IDLE_MOVES.values()) + [arcade.RUN]:
            self.assertLess(last, len(arcade.clawd_frames(name)), name)
            self.assertIsNotNone(arcade.clawd(name, first, 1).getbbox())
        for index in (*arcade.JUMP_RISE, arcade.JUMP_TOP, *arcade.JUMP_FALL, *arcade.JUMP_LAND):
            self.assertIsNotNone(arcade.clawd('Jumping', index, 1).getbbox())

    def test_the_falcon_window_lights_up_with_grok_aboard_and_the_cores_split(self):
        for height in (43, 13):
            plain, aboard = (arcade.rocket_art(height, glass).convert('RGB') for glass in ('empty', 'grok'))
            self.assertTrue(ImageChops.difference(plain, aboard).getbbox())
        whole = arcade.rocket_art(43)
        pieces = [arcade.rocket_art(43, 'empty', 0, (part,)) for part in ('left', 'centre', 'right')]
        self.assertTrue(all(piece.size == whole.size and piece.getbbox() for piece in pieces))
        self.assertLess(pieces[0].getbbox()[2], pieces[2].getbbox()[0])  # a booster on each side

    def test_codex_is_a_little_smaller_with_its_face_kept(self):
        shared, cloud = arcade.mascot_sprite('codex'), arcade.codex_cloud()
        self.assertLess(cloud.width, shared.width)
        self.assertLess(cloud.height, shared.height)
        face = lambda art: sum(1 for p in art.getdata() if arcade.is_light(p))
        self.assertGreater(face(cloud), face(shared) * .8)  # the '>_' keeps its strokes

    def test_a_napper_shows_only_its_zs_and_the_awake_their_notes(self):
        for asleep, drawn in ((True, False), (False, True)):
            image = Image.new('RGB', (40, 40))
            arcade.mood_marks(ImageDraw.Draw(image), 10, 30, 1, 0, 'happy', asleep)
            self.assertEqual(bool(image.getbbox()), drawn)

    def test_codex_grins_at_a_reset(self):
        grin, plain = arcade.codex_pose('happy', 'smile'), arcade.codex_pose('closed', 'long')
        self.assertTrue(ImageChops.difference(grin.convert('RGB'), plain.convert('RGB')).getbbox())
        ink = sum(1 for p in grin.getdata() if arcade.is_light(p))
        self.assertGreater(ink, sum(1 for p in plain.getdata() if arcade.is_light(p)))

    def test_pixel_retro_draws_a_white_grok_on_a_dark_tile(self):
        data = snapshot(time.time(), [('grok_a', 'GROK A', 'grok', [('BUDGET', 61, 6 * D)])])
        image = Image.open(io.BytesIO(render_page(data, style='retro'))).convert('RGB')
        top = 82  # the single row sits in the middle slot
        tile = image.crop((16, top + 13, 46, top + 43))
        corner = tile.getpixel((1, 1))
        self.assertLess(sum(corner), 120)  # dark, no light lavender card any more
        self.assertGreater(max(sum(p) for p in tile.getdata()), 600)  # the bot itself is white


if __name__ == '__main__':
    unittest.main()


class ReadoutTests(unittest.TestCase):
    def test_every_look_reads_one_or_two_windows_known_or_not(self):
        from token_tv import readout
        now = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))
        cases = ([('WEEK', 47, 4 * D)], [('5H', 41, 2 * H), ('WEEK', 63, 3 * D)], [('MONTH', 100, None)])
        try:
            for style, bar in (('score', None), ('chips', None), ('pixel', None), ('lcd', 'cells'), ('lcd', 'ticks'),
                               ('lcd', 'dots'), ('lcd', 'zones'), ('lcd', 'capsule'), ('lcd', 'capsule_along'),
                               ('lcd', 'capsule_lit'), ('lcd', 'capsule_heat')):
                readout.STYLE = style
                readout.LCD_BAR = bar or 'capsule'
                for windows in cases:
                    data = snapshot(now, [('codex_a', 'CODEX A', 'codex', windows)])
                    image = Image.open(io.BytesIO(arcade.render_arcade(data, now)))
                    self.assertEqual(image.size, (240, 240), style)
                    bottom = arcade.arcade_frames(data, now)[0].crop((0, 172, 240, 240))
                    self.assertGreater(len(bottom.getcolors(4096)), 3, style)  # something is drawn there
                data['accounts']['codex_a']['windows'] = []
                arcade.arcade_frames(data, now)  # no reading at all: dashes, no crash
        finally:
            readout.STYLE, readout.LCD_BAR = 'lcd', 'capsule'

    def test_seven_segment_digits_light_their_own_strokes(self):
        from token_tv import readout
        def lit(char):
            image = Image.new('RGB', (40, 50))
            readout.seven(ImageDraw.Draw(image), 0, 0, char, 'big', (255, 255, 255))
            return sum(1 for p in image.getdata() if p == (255, 255, 255))
        self.assertLess(lit('1'), lit('7'))
        self.assertLess(lit('7'), lit('8'))
        self.assertEqual(lit('8'), max(lit(c) for c in '0123456789'))
