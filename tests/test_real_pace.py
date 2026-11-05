"""v2 phase 2, m1: an SD_PRO shows each picture of a GIF for the delay the GIF gives it but at least one tick of about
142 ms (`device_frame_ms` in the config), so on it every loop's end (moments, one-offs, returns) is timed by the sum of
its pictures' times; the GIF itself is never changed for it, and other clocks keep the length the GIF declares."""
import http.client
import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir  # noqa: E402
from test_moments import FRAME_SD, Rig, physical  # noqa: E402

from token_tv import gif, live, moments  # noqa: E402
from token_tv.arcade import gif_seconds  # noqa: E402
from token_tv.device import PhotoDisplay, UltraDisplay  # noqa: E402
from token_tv.moments import loop_end  # noqa: E402
from token_tv.sources import load_config  # noqa: E402

FRAME_ALTERNATE = 197  # ms: a pace unlike the default, for the setting


def made(delays, colours=None):
    """A GIF of solid pictures with these delays (ms); equal neighbours are one picture with their delays summed."""
    colours = colours or [(k * 40 % 256, 80, 160) for k in range(len(delays))]
    frames = [Image.new('RGB', (8, 8), c) for c in colours]
    return gif.encode(gif.indexed(frames, 'test'), delays)


def delays(image):
    out, source = [], Image.open(io.BytesIO(image))
    for n in range(source.n_frames):
        source.seek(n)
        out.append(source.info['duration'])
    return out


class LoopLengthTests(unittest.TestCase):
    def test_an_sd_pro_shows_each_picture_for_its_delay_but_at_least_one_tick(self):
        image = made([70, 140, 700, 70])  # the three short pictures take a tick each, the long one its delay
        sd_pro = PhotoDisplay('http://127.0.0.1:1')
        self.assertAlmostEqual(live.loop_seconds(image, sd_pro), (3 * live.DEVICE_FRAME_MS + 700) / 1000)
        self.assertAlmostEqual(live.loop_seconds(image, sd_pro, FRAME_ALTERNATE), (3 * FRAME_ALTERNATE + 700) / 1000)
        merged = made([70, 70, 70, 70], [(10, 10, 10)] * 3 + [(200, 0, 0)])  # three equal pictures: encoded once
        self.assertEqual(delays(merged), [210, 70])
        self.assertAlmostEqual(live.loop_seconds(merged, sd_pro), (210 + live.DEVICE_FRAME_MS) / 1000)
        held = made([3000, 100], [(255, 0, 0), (0, 0, 255)])  # the clock showed red, not a flicker a tick apart
        self.assertAlmostEqual(live.loop_seconds(held, sd_pro), 3.142)
        bow = made([350, 210, 350, 140, 3150])  # the low bow's poses over a still stage, its last one held
        self.assertAlmostEqual(live.loop_seconds(bow, sd_pro), 4.202)  # the whole bow, not five ticks (0.71 s)

    def test_other_clocks_keep_what_the_gif_declares(self):
        image = made([70, 140, 700, 70])
        self.assertAlmostEqual(live.loop_seconds(image, UltraDisplay('http://127.0.0.1:1'), FRAME_ALTERNATE), .98)
        self.assertAlmostEqual(live.loop_seconds(image, None), gif_seconds(image))

    def test_the_pace_is_one_setting_and_a_sane_one(self):
        folder = temp_dir(self)
        base = {'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'a@example.com'}]}
        for value in (20, 142, FRAME_ALTERNATE, 2000, 141.5):
            (folder / 'c.json').write_text(json.dumps(dict(base, device_frame_ms=value)), encoding='utf-8')
            self.assertEqual(load_config(folder / 'c.json')['device_frame_ms'], value)
        for value in (0, 19, 2001, True, '142', [142], float('inf')):
            (folder / 'c.json').write_text(json.dumps(dict(base, device_frame_ms=value)), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_config(folder / 'c.json')
        self.assertEqual(live.DEVICE_FRAME_MS, 142)


class RealPaceTests(unittest.TestCase):
    """Through live.main: entry, a one-loop moment's length and its return, by the fake clock's own pace."""
    def snack(self, rig):
        """normal -> SNACK -> normal, the press half a loop in; ((entry due, entry), (return due, return), image)."""
        normal, start = rig.showing()
        rig.clock.to(start + rig.loop(normal) / 2)
        pressed = rig.clock.now()
        rig.say('claude.snack')
        due = loop_end({'at': start, 'loop': rig.loop(normal)}, pressed)
        rig.clock.to(due + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('treat', 'snack')))
        end = began + rig.loop(image)
        rig.clock.to(end + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture())
        return (due, began), (end, returned), image

    def test_the_default_pace_and_another_set_in_the_config_time_every_loop_and_change_no_byte(self):
        at = time.time()
        pictures = []
        for frame_ms, frame in ((None, FRAME_SD), (FRAME_ALTERNATE, FRAME_ALTERNATE / 1000)):
            rig = Rig(self, frame_ms=frame_ms, at=at)
            self.assertEqual(rig.frame, frame)
            (due, began), (end, returned), image = self.snack(rig)
            for wanted, seen in ((due, began), (end, returned)):
                self.assertGreaterEqual(seen, wanted)
                self.assertLess(seen, wanted + .25)
            self.assertAlmostEqual(end - began, sum(max(ms / 1000, frame) for ms in delays(image)), places=6)
            self.assertNotAlmostEqual(end - began, gif_seconds(image), places=1)  # not what the GIF declares
            self.assertEqual(set(delays(image)) - {70, 140, 210, 280, 350, 420}, set())  # its own delays, untouched
            pictures.append(image)
        self.assertEqual(pictures[0], pictures[1])  # the same bytes at either pace

    def test_a_bow_that_holds_its_last_pose_is_not_cut_short(self):
        rig = Rig(self)
        rig.say('claude.end')
        due = rig.end_of_loop()  # the usual face's loop, its held pictures whole too
        rig.clock.to(due + .3)
        bow, began = rig.showing()
        self.assertEqual(bow, rig.picture(('done', 'claude')))
        self.assertGreaterEqual(began, due - 1e-6)
        self.assertLess(began, due + .25)
        self.assertGreater(max(delays(bow)), 1000)  # over a still stage its poses are a few pictures, the last held
        end = began + rig.loop(bow)  # each pose for its delay: the held one whole, not a tick of it
        rig.clock.to(end - .05)
        self.assertEqual(rig.showing()[0], bow)  # still bowing
        rig.clock.to(end + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture())
        self.assertGreaterEqual(returned, end - 1e-6)
        self.assertLess(returned, end + .25)

    def test_the_next_loop_counts_from_when_the_picture_went_on_not_when_its_send_began(self):
        rig = Rig(self, delay=.1)  # each send takes 100 ms on the clock
        normal, start = rig.showing()
        rig.clock.to(start + rig.loop(normal) / 2)
        rig.say('claude.snack')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        image, began = rig.showing()
        sent = [t for t in rig.uploads() if t >= due]
        self.assertTrue(sent and sent[0] >= due)  # not begun before the loop's end
        self.assertGreater(began, sent[0])  # on once the send was done
        rig.clock.to(began + rig.loop(image) / 2)
        asked = rig.clock.now()
        rig.say('claude.ask')
        end = began + rig.loop(image)  # its own pictures from its own start, not from the send's start
        rig.clock.to(end - .01)
        self.assertEqual(rig.showing()[0], image)
        rig.clock.to(end + .4)
        waiting, at = rig.showing()
        self.assertEqual(waiting, rig.picture(('needs', 1)))
        self.assertGreaterEqual(at, end)
        self.assertLess(at, end + .25)
        rig.say('claude.answered')
        rig.clock.to(rig.end_of_loop() + .4)
        self.assertEqual(rig.showing()[0], rig.picture())
        self.assertLessEqual(len(rig.uploads(asked)), 2)  # the wait and the return; no stale return of the snack

    def test_a_loop_counts_from_the_switchs_last_request_the_old_slot_turned_off(self):
        rig = Rig(self, switch_off=.6)  # the clock takes 0.6 s to turn the old slot off, its animation held meanwhile
        normal, start = rig.showing()
        rig.clock.to(start + rig.loop(normal) / 2)
        rig.say('claude.pet')
        due = loop_end({'at': start, 'loop': rig.loop(normal)}, rig.clock.now())
        rig.clock.to(due + .3)
        pet, began = rig.showing()  # (when its slot went on)
        self.assertEqual(pet, rig.picture(('treat', 'pet')))
        self.assertGreaterEqual(began, due - 1e-6)
        self.assertLess(began, due + .25)
        end = began + .6 + rig.loop(pet)  # its loop under way once the old slot was off
        rig.clock.to(end - .01)
        self.assertEqual(rig.showing()[0], pet)  # not cut short by that request's hold
        rig.clock.to(end + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture())
        self.assertGreaterEqual(returned, end - 1e-6)
        self.assertLess(returned, end + .25)

    def test_a_usage_redraw_goes_as_the_loop_playing_when_its_reading_came_ends_however_soon_after_its_start(self):
        at, window = float(int(time.time())), {'codex': [('5H', 30, 4 * 3600)]}
        learn = Rig(self, providers=('codex',), wall=True, windows=window, at=at)
        loop = learn.loop(learn.showing()[0])  # the usual face's loop on this clock
        learn.stop()
        for phase in (.001, .05, loop / 2, loop - .001, 0):  # how far into a loop the minute's reading comes
            rig = Rig(self, providers=('codex',), wall=True, windows=window, at=at, late=(60 - phase) % loop)
            normal, start = rig.showing()  # (the first picture went on that much later, its loop with it)
            rig.clock.to(rig.poll_at(1) - 1)
            rig.set('codex_a', '5H', 45)
            rig.write()
            read = rig.poll_at(1)
            due = loop_end({'at': start, 'loop': loop}, read)
            self.assertAlmostEqual(due, read - phase + (loop if phase else 0), places=6, msg=phase)
            rig.clock.to(due - .001)
            self.assertEqual([t for t in rig.switches(read)], [], phase)  # nothing cuts the loop that was playing
            rig.clock.to(due + .3)
            image, began = rig.showing()
            self.assertEqual(image, rig.picture(snapshot=rig.held()), phase)  # the new reading
            self.assertGreaterEqual(began, due - 1e-6, phase)
            self.assertLess(began, due + .25, phase)
            self.assertEqual(len(rig.uploads(read)), 1, phase)
            rig.stop()

    def test_an_ultra_keeps_the_length_the_gif_declares(self):
        rig = Rig(self, model='ultra', frame_ms=FRAME_ALTERNATE)  # the SD_PRO's setting is no Ultra's
        (due, began), (end, returned), image = self.snack(rig)
        self.assertAlmostEqual(end - began, gif_seconds(image), places=6)
        self.assertNotAlmostEqual(end - began, physical(image, FRAME_ALTERNATE / 1000), places=1)
        self.assertGreaterEqual(returned, end)
        self.assertLess(returned, end + .25)


class SlowPickTests(unittest.TestCase):
    """The hidden one-offs are picked as a reading comes in, before it is drawn. A pick that takes PICK on the clock,
    over the end of the loop that was playing as the reading came, puts nothing a loop later: the reading's redraw, a
    wait asked for meanwhile and the one-off picked all go as that loop ends, here at once just after it (live.LATE)."""
    PICK = .1

    def rig(self, picked=None, asked=None, **options):
        """A rig whose minute's reading comes 50 ms before the end of the usual face's loop, the pick then taking PICK:
        30 ms into it `asked` is sent (a moment, as the mod sends it), and it returns `picked`. (rig, when the reading
        comes, that loop's end, when each pick began), the clock a second before the reading."""
        at = float(int(time.time()))
        learn = Rig(self, at=at, **options)
        loop = learn.loop(learn.showing()[0])
        learn.stop()
        rig = Rig(self, at=at, late=(60 - (loop - .05)) % loop, **options)
        picks = []

        def pick(snapshot):
            picks.append(moments.CLOCK.now())
            if len(picks) > 1:  # (the readings after it: at once, nothing)
                return None
            moments.CLOCK.bump(.03)
            if asked:  # sent from here, so it comes in while the pick goes on (rig.say would wait for TokenTV)
                conn = http.client.HTTPConnection('127.0.0.1', rig.port, timeout=5)
                conn.request('POST', '/moment', json.dumps({'moment': asked}), {'Content-Type': 'application/json'})
                self.assertEqual(conn.getresponse().status, 204)
                conn.close()
            moments.CLOCK.bump(self.PICK - .03)
            return picked
        patcher = mock.patch.object(live.Lockbox, 'pick', side_effect=pick)
        patcher.start()
        self.addCleanup(patcher.stop)
        normal, start = rig.showing()
        read = rig.poll_at(1)
        due = loop_end({'at': start, 'loop': loop}, read)
        self.assertAlmostEqual(due - read, .05, places=6)
        rig.clock.to(read - 1)
        return rig, read, due, picks

    def assertOn(self, rig, image, due, read, picks):
        """`image` went on as the loop playing at `read` ended (`due`), or once the pick was done just after it, alone."""
        self.assertEqual(picks[:1], [read])  # (picked as the reading came in)
        shown, began = rig.showing()
        self.assertEqual(shown, image)
        self.assertGreaterEqual(began, due - 1e-6)
        self.assertLess(began, due + .25)  # not a loop later
        self.assertEqual(len(rig.uploads(read)), 1)

    def test_a_usage_redraw_goes_as_the_loop_its_reading_came_in_ends_however_long_the_pick_takes(self):
        rig, read, due, picks = self.rig(providers=('codex',), wall=True, windows={'codex': [('5H', 30, 4 * 3600)]})
        rig.set('codex_a', '5H', 45)
        rig.write()
        rig.clock.to(due + .3)
        self.assertOn(rig, rig.picture(snapshot=rig.held()), due, read, picks)

    def test_a_wait_asked_for_while_the_one_offs_are_picked_goes_as_the_loop_it_came_in_ends(self):
        rig, read, due, picks = self.rig(asked='claude.ask')
        rig.clock.to(due + .3)
        self.assertOn(rig, rig.picture(('needs', 1)), due, read, picks)

    def test_a_one_off_picked_slowly_goes_on_as_the_loop_its_reading_came_in_ends(self):
        from token_tv.lockbox import Box
        stage = lambda colour: Image.new('RGB', (120, 71), colour)  # noqa: E731
        box = Box('Test', 'unique', 'claude_a', tuple(stage((200, 40, 40)) for _ in range(4)), 40,
                  after=(stage((40, 40, 200)),))
        rig, read, due, picks = self.rig(picked=box)
        rig.clock.to(due + .3)
        self.assertOn(rig, rig.picture(egg=box), due, read, picks)


if __name__ == '__main__':
    unittest.main()


class EdgeTests(unittest.TestCase):
    """A moment just before a loop's end, exactly at it, or just after: the first two at that end, the last at the
    next, each counted from the picture's own start (v2p2-06)."""
    def test_a_moment_at_a_loops_very_end(self):
        eps = .001
        for offset, ends in ((-eps, 3), (0, 3), (eps, 4)):  # pressed around the third loop's end
            rig = Rig(self)
            normal, start = rig.showing()
            loop = rig.loop(normal)
            rig.clock.to(start + 3 * loop + offset)
            rig.say('claude.pet')
            due = start + ends * loop
            rig.clock.to(due + .3)
            image, began = rig.showing()
            self.assertEqual(image, rig.picture(('treat', 'pet')), offset)
            self.assertGreaterEqual(began, due - 1e-9, offset)
            self.assertLess(began, due + .25, offset)
