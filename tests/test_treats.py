"""v2 phase 2, e5: `/tokentv pet` and `/tokentv snack` in the Claude Code mod send `claude.pet` and `claude.snack`;
Clawd shows hearts or munches for one loop at the end of the loop the clock is playing. A press while one is still to
show or showing is dropped, and so is one while Claude waits; a wait drops one not shown yet (nothing is queued)."""
import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import FakeClock, Rig, physical, post_bytes, raw  # noqa: E402

from token_tv import arcade, live, moments  # noqa: E402
from token_tv.moments import Moments, loop_end, overlay  # noqa: E402
from token_tv.sample import D, snapshot  # noqa: E402

NOW = int(time.mktime((2026, 11, 1, 14, 1, 0, 0, 0, -1)))  # Sunday 2:01 pm wherever the tests run (the stage dims at night)


def frames(image):
    gif = Image.open(io.BytesIO(image))
    out = []
    for n in range(gif.n_frames):
        gif.seek(n)
        out.append(gif.convert('RGB'))
    return out


class TreatStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        patcher = mock.patch.object(moments, 'CLOCK', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.woken = []
        self.m = Moments({'claude', 'codex'}, wake=lambda: self.woken.append(self.clock.t), active=600)

    def test_the_two_names_are_moments_and_nothing_like_them_is(self):
        self.assertIn('claude.pet', moments.MOMENTS)
        self.assertIn('claude.snack', moments.MOMENTS)
        for body in (b'{"moment":"claude.pet"}', b'{"moment":"claude.snack"}'):
            self.assertEqual(live.moment_of(body), json.loads(body)['moment'])
        for body in (b'{"moment":"Claude.Pet"}', b'{"moment":"claude.PET"}', b'{"moment":"/tokentv pet"}',
                     b'{"moment":"claude.pet","prompt":"x"}', b'{"moment":["claude.pet"]}', b'["claude.pet"]',
                     b'{"moment":"claude.pet","moment":"claude.snack"}', b'{"moment":"claude.treat"}'):
            with self.assertRaises(ValueError):
                live.moment_of(body)

    def test_a_pet_or_a_snack_is_due_from_the_press_and_draws_on_clawds_rows(self):
        self.assertTrue(self.m.note('claude.pet'))
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since, mark), (('treat', 'pet'), self.clock.t, {'kind': 'pet'}))
        self.assertEqual(self.woken, [self.clock.t])
        drawn = overlay(snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)]),
                                       ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])]), what, mark)
        self.assertEqual(drawn['accounts']['claude_a']['moment'], {'kind': 'pet'})
        self.assertNotIn('moment', drawn['accounts']['codex_a'])  # no other pet does it
        self.m.shown(what, self.clock.t + 1)
        self.assertEqual(self.m.wanted()[:2], (None, self.clock.t + 1))  # one loop: the usual face due after it

    def test_presses_while_one_is_to_show_or_showing_are_dropped_and_change_nothing(self):
        self.m.note('claude.snack')
        count, woken = self.m.count, list(self.woken)
        for name in ('claude.snack', 'claude.pet', 'claude.pet'):
            self.assertFalse(self.m.note(name))
        self.assertEqual((self.m.count, self.woken), (count, woken))
        self.assertEqual(self.m.wanted()[0], ('treat', 'snack'))  # neither replaced nor lengthened
        self.m.shown(('treat', 'snack'), self.clock.t)
        for name in ('claude.snack', 'claude.pet'):  # on the clock now: dropped too
            self.assertFalse(self.m.note(name))
        self.assertIsNone(self.m.wanted()[0])
        self.m.shown(None, self.clock.t + 8)  # its loop over, the usual face back on
        self.assertTrue(self.m.note('claude.pet'))  # a fresh press works, no minute to wait as for a bow
        self.assertEqual(self.m.wanted()[0], ('treat', 'pet'))

    def test_a_wait_drops_a_treat_not_shown_and_a_press_while_waiting_is_dropped(self):
        self.m.note('claude.pet')
        self.m.note('claude.ask')
        self.assertEqual(self.m.wanted()[0], ('needs', 1))
        for name in ('claude.pet', 'claude.snack'):
            self.assertFalse(self.m.note(name))
        self.m.note('claude.answered')
        self.assertIsNone(self.m.wanted()[0])  # nothing kept for after: no backlog drains

    def test_a_wait_takes_over_from_a_treat_on_the_clock_which_does_not_come_back(self):
        self.m.note('claude.snack')
        self.m.shown(('treat', 'snack'), self.clock.t)
        self.clock.t += 2
        self.m.note('claude.ask')
        self.assertEqual(self.m.wanted()[:2], (('needs', 1), self.clock.t))  # at the treat's loop end
        self.m.note('claude.answered')
        self.assertIsNone(self.m.wanted()[0])

    def test_a_bow_goes_first_then_the_treat_each_its_own_loop(self):
        self.m.note('claude.end')
        self.m.note('claude.pet')
        self.assertEqual(self.m.wanted()[0], ('done', 'claude'))
        self.m.shown(('done', 'claude'), self.clock.t + 1)
        what, since, _ = self.m.wanted()
        self.assertEqual(what, ('treat', 'pet'))
        self.assertEqual(loop_end({'at': self.clock.t + 1, 'loop': 2.5}, since), self.clock.t + 3.5)  # at the bow's end
        self.m.shown(what, self.clock.t + 3.5)
        self.assertIsNone(self.m.wanted()[0])
        self.assertTrue(self.m.cooling(self.clock.t + 3.5))  # the bow's minute is the bow's alone
        self.m.shown(None, self.clock.t + 10)  # the treat's loop over
        self.m.note('claude.snack')
        self.assertEqual(self.m.wanted()[0], ('treat', 'snack'))

    def test_no_claude_account_no_treat_and_nothing_kept(self):
        m = Moments({'codex'}, active=600)
        self.assertFalse(m.note('claude.pet'))
        self.assertEqual((m.wanted()[0], m.busy(), m.count), (None, False, 0))

    def test_a_treat_with_no_clock_to_show_it_on_is_dropped(self):
        self.m.note('claude.pet')
        self.assertTrue(self.m.busy())
        self.m.drop_bow()
        self.assertEqual((self.m.wanted()[0], self.m.busy()), (None, False))


class TreatDrawingTests(unittest.TestCase):
    def picture(self, kind, *others):
        accounts = [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)])] + list(others)
        data = snapshot(NOW, accounts)
        data['accounts']['claude_a']['moment'] = {'kind': kind}
        return arcade.render_arcade(data, NOW), data

    def test_hearts_and_munching_move_through_one_loop_and_differ(self):
        pet, snack = self.picture('pet')[0], self.picture('snack')[0]
        self.assertNotEqual(pet, snack)
        for image, ink in ((pet, (255, 92, 136)), (snack, (226, 172, 102))):  # a heart's pink, the cookie's brown
            shots = frames(image)
            self.assertGreater(len(shots), 20)  # moving, not a still with a label
            stages = [shot.crop((0, 28, 240, 170)) for shot in shots]
            self.assertGreater(len({s.tobytes() for s in stages}), 20)
            self.assertTrue(any(ink in {c for _, c in s.getcolors(65536)} for s in stages))

    def test_its_readout_says_what_clawd_does_and_no_bow_or_wait(self):
        data = snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)])])
        row = dict(data['accounts']['claude_a'], key='claude_a')
        for kind, word in (('pet', 'PETTED'), ('snack', 'SNACKING')):
            plan = arcade.scene_plan(dict(row, moment={'kind': kind}), NOW)
            self.assertEqual(arcade.action_label(dict(row, moment={'kind': kind}), plan, None, 0, 120), word)

    def test_beside_another_pet_only_clawd_does_it_and_the_other_keeps_its_place(self):
        plain = snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)]),
                               ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])])
        petted = overlay(plain, ('treat', 'pet'), {'kind': 'pet'})
        self.assertEqual([r['provider'] for r in arcade.shown_rows(petted, NOW)], ['claude', 'codex'])
        usual, shots = arcade.arcade_frames(plain, NOW), arcade.arcade_frames(petted, NOW)
        half = len(shots) // 2  # Clawd's turn, then the Codex cloud's
        stage = lambda frame: frame.crop((0, 28, 240, 170)).tobytes()  # noqa: E731
        self.assertEqual([stage(f) for f in shots[half:]], [stage(f) for f in usual[half:]])  # the cloud as ever
        self.assertNotEqual([stage(f) for f in shots[:half]], [stage(f) for f in usual[:half]])  # Clawd petted


class TreatTimingTests(unittest.TestCase):
    """On the fake SD_PRO, through live.main: each starts at the end of the loop playing, plays its own one loop of
    pictures at the clock's pace, then the usual face; presses beside it change nothing."""
    def test_pet_then_snack_each_one_loop_at_the_next_loop_end(self):
        rig = Rig(self)
        normal, start = rig.showing()
        loop = physical(normal)
        rig.clock.to(start + loop / 4)
        pressed = rig.clock.now()
        rig.say('claude.pet')
        due = loop_end({'at': start, 'loop': loop}, pressed)
        rig.clock.to(due - .01)
        self.assertEqual(rig.requests(pressed), [])  # nothing interrupts the loop that is playing
        rig.clock.to(due + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('treat', 'pet')))
        self.assertGreaterEqual(began, due)
        self.assertLess(began, due + .25)
        end = began + physical(image)
        rig.clock.to(end + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture())  # one loop, then the usual face: no bow, no wait
        self.assertGreaterEqual(returned, end)
        self.assertLess(returned, end + .25)
        self.assertLessEqual(len(rig.uploads(pressed)), 2)  # entry and return
        rig.clock.to(returned + physical(back) / 2)
        pressed = rig.clock.now()
        rig.say('claude.snack')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('treat', 'snack')))
        self.assertLess(began, due + .25)
        rig.clock.to(began + physical(image) + .3)
        self.assertEqual(rig.showing()[0], rig.picture())
        self.assertLessEqual(len(rig.uploads(pressed)), 2)

    def test_presses_while_one_is_to_show_or_showing_send_nothing_more(self):
        rig = Rig(self)
        normal, start = rig.showing()
        rig.clock.to(start + physical(normal) / 4)
        pressed = rig.clock.now()
        rig.say('claude.snack')
        for name in ('claude.snack', 'claude.pet', 'claude.pet', 'claude.snack'):
            rig.say(name)  # all still to show: dropped
        rig.clock.to(rig.end_of_loop() + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('treat', 'snack')))
        for name in ('claude.pet', 'claude.snack'):
            rig.say(name)  # showing: dropped
        rig.clock.to(began + physical(image) + .3)
        back, returned = rig.showing()
        self.assertEqual(back, rig.picture())
        rig.clock.advance(5 * physical(back))  # several quiet loops: nothing queued comes
        self.assertLessEqual(len(rig.uploads(pressed)), 2)  # (the usual face may still be on the clock: a switch)
        self.assertEqual(len(rig.switches(pressed)), 2)  # the snack on, the usual face back: no more
        self.assertEqual(rig.showing()[0], rig.picture())

    def test_a_wait_outranks_a_press_and_none_comes_back_after_it(self):
        rig = Rig(self)
        normal, start = rig.showing()
        rig.clock.to(start + physical(normal) / 4)
        rig.say('claude.pet')  # still to show when the wait comes: dropped
        asked = rig.clock.now()
        rig.say('claude.ask')
        rig.say('claude.snack')
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.showing()[0], rig.picture(('needs', 1)))
        rig.say('claude.pet')
        rig.clock.advance(30)
        self.assertEqual(rig.showing()[0], rig.picture(('needs', 1)))  # no press clears it
        rig.say('claude.answered')
        rig.clock.to(rig.end_of_loop() + .3)
        back, _ = rig.showing()
        self.assertEqual(back, rig.picture())
        rig.clock.advance(5 * physical(back))
        self.assertEqual(rig.showing()[0], rig.picture())  # no backlog drains
        self.assertLessEqual(len(rig.uploads(asked)), 2)

    def test_a_wait_during_a_treat_takes_over_at_its_end(self):
        rig = Rig(self)
        normal, start = rig.showing()
        rig.say('claude.snack')
        rig.clock.to(rig.end_of_loop() + .3)
        image, began = rig.showing()
        self.assertEqual(image, rig.picture(('treat', 'snack')))
        rig.clock.to(began + physical(image) / 2)
        rig.say('claude.ask')
        end = began + physical(image)
        rig.clock.to(end + .3)
        waiting, at = rig.showing()
        self.assertEqual(waiting, rig.picture(('needs', 1)))
        self.assertGreaterEqual(at, end)  # the treat's one loop whole, then the wait
        self.assertLess(at, end + .25)
        rig.say('claude.answered')
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.showing()[0], rig.picture())  # the treat does not play again

    def test_without_claude_on_the_clock_a_press_does_nothing(self):
        rig = Rig(self, providers=('codex',))
        _, start = rig.showing()
        rig.say('claude.pet')
        rig.clock.advance(30)
        self.assertEqual(rig.uploads(start + .001), [])
        self.assertEqual(rig.showing()[0], rig.picture())

    def test_the_endpoint_takes_the_two_names_and_refuses_what_is_near_them(self):
        rig = Rig(self)
        for body in (b'{"moment":"Claude.Pet"}', b'{"moment":"/tokentv pet"}', b'{"moment":"claude.pet","x":1}'):
            status = raw(rig.port, post_bytes(rig.port, body))[0]
            self.assertEqual(status, 400, body)
        rig.clock.advance(10)
        self.assertEqual(rig.uploads(rig.t0 + .001), [])  # nothing changed
        rig.say('claude.pet')  # and the real one still works
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.showing()[0], rig.picture(('treat', 'pet')))


if __name__ == '__main__':
    unittest.main()
