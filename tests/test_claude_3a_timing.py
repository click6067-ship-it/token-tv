"""v2 phase 3a on the fake SD_PRO, through live.main itself: each moment from Claude Code reaches the clock as the
loop it is playing ends (never mid-loop), a one-off plays its own one loop on the clock (each picture its delay, at
least a 142 ms tick: m1) and the usual face comes back, a minute-long state (the ghost, the back turned) stays in the
one picture the clock loops, a fresh repeat sends nothing, and the thinking word changes at most once a minute and
goes with the turn."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_claude_3a import Turns  # noqa: E402
from test_moments import Rig, physical  # noqa: E402

from token_tv import moments  # noqa: E402
from token_tv.display import render_page  # noqa: E402
from token_tv.moments import COURT_STALE, GHOST, WORD_INTERVAL, loop_end, overlay  # noqa: E402
from token_tv.sample import H  # noqa: E402
from token_tv.state import MIN_FETCH_SECONDS, RATE_WINDOW, UsageStore  # noqa: E402


def mark_of(what):
    """The rows' mark for `what`, as Moments.wanted() gives it (the tests' own oracle, from the rules)."""
    if what is None:
        return None
    if what[0] == 'risky':
        return {'kind': 'risky', 'style': what[1]}
    if what[0] == 'calm':
        return {'kind': 'calm'}
    if what[0] == 'face':
        return {'kind': what[1]}
    if what[0] == 'state':
        _, ghost, back, word = what
        moment = (dict({'kind': 'rude'}, **({'ghost': ghost} if ghost else {})) if back else
                  {'kind': 'deleted', 'style': ghost} if ghost else None)
        return {'moment': moment, 'word': word}
    return {'kind': 'needs', 'since': 0, 'level': what[1]} if what[0] == 'needs' else (
        {'kind': 'done', 'at': 0} if what[0] == 'done' else {'kind': what[1]})


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(moments, 'RANDOM', Turns())  # each kind's variants in turn: A first
        patcher.start()
        self.addCleanup(patcher.stop)

    def picture(self, rig, what=None):
        store = UsageStore(rig.config['accounts'], min_fetch_seconds=MIN_FETCH_SECONDS)
        store.refresh()
        return render_page(overlay(store.snapshot(), what, mark_of(what)), 0, 'arcade')

    def assertAt(self, rig, when, what, since):
        """One more upload at the loop's end `when` (within 250 ms) and the clock shows `what` since then: its start
        and its loop on the clock (each picture its delay, at least a 142 ms tick)."""
        image, started = rig.showing()
        self.assertEqual(image, self.picture(rig, what))
        self.assertGreaterEqual(started, when - 1e-6)
        self.assertLess(started, when + .25)
        self.assertLessEqual(len(rig.uploads(since)), 1)
        return started, physical(image)

    def halfway(self, rig):
        """Half way through the loop playing: (now, that loop's end)."""
        normal, start = rig.showing()
        rig.clock.to(start + physical(normal) / 2)
        return rig.clock.now(), loop_end({'at': start, 'loop': physical(normal)}, rig.clock.now())


class OneOffTests(Base):
    def test_the_courtroom_comes_at_the_loops_end_plays_one_loop_and_the_usual_face_comes_back(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.risky')
        rig.clock.to(due - .01)
        self.assertEqual(rig.requests(said), [])  # nothing interrupts the loop playing
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('risky', 'verdict'), said)
        self.assertNotEqual(physical(self.picture(rig)), loop)  # (its own loop, not the usual face's)
        rig.say('claude.risky')  # inside the day: dropped
        rig.clock.to(start + loop + .3)
        back, again = self.assertAt(rig, start + loop, None, start + .01)
        self.assertLessEqual(len(rig.uploads(said)), 2)  # entry and return
        rig.clock.advance(5 * physical(self.picture(rig)))
        self.assertEqual(rig.uploads(back + .01), [])  # and nothing more: no courtroom put off for later

    def test_dizzy_and_the_squeeze_one_loop_each_and_one_a_minute_between_them(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.failed')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('face', 'failed'), said)
        rig.say('claude.compact')  # inside the minute: dropped
        rig.clock.to(start + loop + .3)
        self.assertAt(rig, start + loop, None, start + .01)
        rig.clock.to(start + 59.9)
        rig.say('claude.compact')
        rig.clock.advance(15)
        self.assertEqual(rig.showing()[0], self.picture(rig))  # dropped, not saved for the minute's end
        rig.clock.to(start + 60.5)
        mark = rig.clock.now()
        rig.say('claude.compact')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('face', 'compact'), mark)

    def test_a_courtroom_held_two_minutes_by_its_open_prompt_is_dropped_and_the_day_is_kept(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.risky')
        rig.say('claude.ask')  # its own prompt, left open
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('needs', 1), said)
        rig.clock.to(said + COURT_STALE + 30)
        answered = rig.clock.now()
        rig.say('claude.answered')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        back, loop = self.assertAt(rig, due, None, answered)  # the usual face: no courtroom two minutes late
        rig.clock.advance(3 * loop)
        self.assertEqual(rig.uploads(back + .01), [])
        fresh = rig.clock.now()
        rig.say('claude.risky')  # it took nothing of the day: a fresh one plays
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('risky', 'objection'), fresh)

    def test_a_wait_owns_the_clock_and_the_courtroom_plays_after_it(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.risky')
        rig.say('claude.ask')  # before the loop's end: the wait comes first
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('needs', 1), said)
        rig.clock.advance(3 * loop)
        answered = rig.clock.now()
        rig.say('claude.answered')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('risky', 'verdict'), answered)
        rig.clock.to(start + loop + .3)
        self.assertEqual(rig.showing()[0], self.picture(rig))


class StateTests(Base):
    def test_a_ghost_floats_its_minute_in_one_picture_more_deletions_send_nothing_then_it_goes(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.deleted')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', 'drift', False, None), said)
        rig.clock.to(said + 30)
        fresh = rig.clock.now()
        rig.say('claude.deleted')  # a minute from this one now, the same ghost
        rig.clock.to(said + GHOST + 5)  # past the first one's minute: still there, nothing sent
        self.assertEqual(rig.uploads(start + .01), [])
        self.assertEqual(rig.switches(start + .01), [])
        self.assertEqual(rig.showing()[0], self.picture(rig, ('state', 'drift', False, None)))
        gone = loop_end({'at': start, 'loop': loop}, fresh + GHOST)
        rig.clock.to(gone + .3)
        self.assertAt(rig, gone, None, start + .01)
        self.assertLessEqual(len(rig.uploads(said)), 2)  # its entry and its end, nothing between

    def test_the_back_turned_a_calm_prompt_turns_it_round_for_one_loop_then_the_usual_face(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.rude')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, True, None), said)
        rig.clock.to(start + 20)
        calmed = rig.clock.now()
        rig.say('claude.calm')
        due = loop_end({'at': start, 'loop': loop}, calmed)
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('calm',), calmed)  # the turn back round (w20), one loop
        rig.clock.to(start + loop + .3)
        self.assertAt(rig, start + loop, None, start + .01)
        self.assertLessEqual(len(rig.uploads(said)), 3)  # the back, the turn round, the usual face (the draft's three)
        rig.clock.to(said + 120)  # past the old minute: nothing
        self.assertEqual(rig.uploads(start + loop + .5), [])

    def test_a_sulking_clawd_does_not_bow_for_the_rude_prompts_own_turn_nor_while_it_sulks(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.rude')
        rig.clock.advance(.5)
        rig.say('claude.end')  # its own turn ends before the back is on the clock: no DONE first
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, True, None), said)
        rig.clock.to(start + 20)
        rig.say('claude.end')  # another turn while it sulks: no bow either
        rig.clock.to(start + 50)
        self.assertEqual(rig.uploads(start + .01), [])
        self.assertEqual(rig.switches(start + .01), [])

    def test_rude_then_calm_inside_one_loop_sends_nothing_and_never_flashes_a_back(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.rude')
        rig.say('claude.calm')
        for _ in range(3):
            rig.say('claude.rude')
            rig.say('claude.calm')
        rig.clock.to(due + 3 * physical(self.picture(rig)))
        self.assertEqual(rig.requests(said), [])

    def test_the_back_turned_its_minute_up_on_the_clock_also_turns_round(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.rude')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, True, None), said)
        turned = loop_end({'at': start, 'loop': loop}, said + 60)
        rig.clock.to(turned + .3)
        self.assertAt(rig, turned, ('calm',), start + .01)


class WordTests(Base):
    def test_the_word_comes_at_the_loops_end_the_same_again_sends_nothing_a_new_one_after_a_minute(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.word:Pondering')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, False, 'PONDERING'), said)
        for _ in range(4):
            rig.say('claude.word:Pondering')
        rig.clock.to(start + 10)
        rig.say('claude.word:Brewing')  # inside the minute: waits for it
        rig.clock.to(start + WORD_INTERVAL - .01)
        self.assertEqual(rig.uploads(start + .01), [])  # no picture per spinner drawing, none for the waiting word
        due = loop_end({'at': start, 'loop': loop}, start + WORD_INTERVAL)
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, False, 'BREWING'), start + 1)

    def test_a_newer_word_waiting_goes_on_at_its_minutes_end_with_no_reading_to_wake_tokentv(self):
        rig = Rig(self)
        rig.clock.to(rig.t0 + 30)  # the first word's minute will end between two readings
        said, due = rig.clock.now(), rig.end_of_loop()
        rig.say('claude.word:Pondering')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, False, 'PONDERING'), said)
        rig.clock.to(rig.poll_at(1) + 2)  # after a reading: nothing else wakes TokenTV till the next one
        rig.say('claude.word:Musing')  # waits for the minute...
        due = loop_end({'at': start, 'loop': loop}, start + WORD_INTERVAL)
        self.assertLess(due + 1, rig.poll_at(2))
        rig.clock.to(due + .3)
        self.assertAt(rig, due, ('state', None, False, 'MUSING'), start + 1)  # ...and goes on as it ends

    def test_a_word_said_behind_slow_starts_its_minute_once_slow_lifts(self):
        rig = Rig(self, wall=True, windows={'claude': [('5H', 60, 4 * H)]})
        drawn = lambda what: render_page(overlay(rig.held(), what, mark_of(what)), 0, 'arcade')  # noqa: E731
        polls = RATE_WINDOW // rig.poll
        for k in range(1, polls + 1):  # 1.5 % a minute: running out (SLOW)
            rig.set('claude_a', '5H', 60 + 1.5 * k)
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.held()['accounts']['claude_a']['slow'], ['5H'])
        said = rig.clock.now()
        rig.say('claude.word:Pondering')  # SLOW keeps the label: the same picture, nothing sent
        rig.clock.advance(20)
        self.assertEqual(rig.requests(said), [])
        k = polls
        while rig.held()['accounts']['claude_a']['slow']:  # flat from now: SLOW lifts after a while
            k += 1
            rig.write(rig.now() + rig.poll_at(k) - rig.clock.now())
            rig.clock.to(rig.poll_at(k) + .5)
        due = rig.end_of_loop(rig.poll_at(k))
        rig.clock.to(due + .3)
        image, read = rig.showing()
        self.assertEqual(image, drawn(('state', None, False, 'PONDERING')))  # the word, read at last
        self.assertGreater(read, said + 60)
        rig.clock.to(read + 5)
        rig.say('claude.word:Musing')  # a minute from when it was read, not from when it was said
        due = loop_end({'at': read, 'loop': physical(image)}, read + WORD_INTERVAL)
        rig.clock.to(due - .3)
        self.assertEqual(rig.uploads(read + .01), [])
        rig.clock.to(due + .3)
        musing, at = rig.showing()
        self.assertEqual(musing, drawn(('state', None, False, 'MUSING')))
        self.assertGreaterEqual(at, due - 1e-6)
        self.assertLess(at, due + .25)

    def test_the_turns_end_takes_the_word_into_the_bow_in_one_picture_and_a_cut_turn_without_a_bow(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        rig.say('claude.word:Pondering')
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, False, 'PONDERING'), said)
        rig.clock.to(start + 5)
        rig.say('claude.word:Brewing')  # waiting for its minute as the turn ends
        ended = rig.clock.now()
        rig.say('claude.end')
        due = loop_end({'at': start, 'loop': loop}, ended)
        rig.clock.to(due + .3)
        bowed, bow_loop = self.assertAt(rig, due, ('done', 'claude'), ended)  # the bow with no word: one picture
        rig.clock.to(bowed + bow_loop + .3)
        self.assertAt(rig, bowed + bow_loop, None, bowed + .01)
        rig.clock.to(start + 70)  # the waiting word went with the turn: nothing at its minute
        self.assertEqual(rig.showing()[0], self.picture(rig))
        rig.say('claude.word:Musing')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        start, loop = self.assertAt(rig, due, ('state', None, False, 'MUSING'), start + 69)
        rig.clock.advance(2)
        cut = rig.clock.now()
        rig.say('claude.stop')
        due = rig.end_of_loop()
        rig.clock.to(due + .3)
        self.assertAt(rig, due, None, cut)  # the usual face: no bow for a turn cut short

    def test_nothing_of_the_word_or_the_moments_is_written_anywhere(self):
        rig = Rig(self)
        before = {p: p.read_bytes() for p in rig.state.rglob('*') if p.is_file()}
        said, due = self.halfway(rig)
        for name in ('claude.word:Philosophising', 'claude.deleted', 'claude.rude'):
            rig.say(name)
        rig.clock.to(due + .3)
        self.assertEqual(rig.showing()[0], self.picture(rig, ('state', 'drift', True, 'PHILOSOPHISING')))
        for path in rig.state.rglob('*'):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(b'PHILOSOPHISING', data.upper(), path)
                self.assertNotIn(b'rude', data, path)
                if path in before:  # an existing file is only ever the usual face's (the moments' never kept)
                    self.assertNotEqual(data, rig.showing()[0])
        self.assertFalse(any(p.read_bytes() == rig.showing()[0] for p in rig.state.rglob('*') if p.is_file()))

    def test_the_dashboards_preview_shows_the_word_and_the_ghost_as_the_clock_will(self):
        import http.client
        rig = Rig(self)
        rig.say('claude.word:Pondering')
        rig.say('claude.deleted')
        conn = http.client.HTTPConnection('127.0.0.1', rig.port, timeout=5)
        conn.request('GET', '/frame/0.jpg')
        self.assertEqual(conn.getresponse().read(), self.picture(rig, ('state', 'drift', False, 'PONDERING')))
        conn.close()
        rig.clock.to(rig.end_of_loop() + .3)
        self.assertEqual(rig.showing()[0], self.picture(rig, ('state', 'drift', False, 'PONDERING')))

    def test_a_restart_forgets_the_word_the_ghost_and_the_back(self):
        rig = Rig(self)
        said, due = self.halfway(rig)
        for name in ('claude.word:Pondering', 'claude.deleted', 'claude.rude', 'claude.risky'):
            rig.say(name)
        rig.clock.to(due + .3)
        rig.stop()
        rig.start()
        rig.clock.advance(5)
        self.assertEqual(rig.showing()[0], self.picture(rig))
        rig.clock.advance(120)  # past every old minute: nothing comes back
        self.assertEqual(rig.showing()[0], self.picture(rig))


if __name__ == '__main__':
    unittest.main()
