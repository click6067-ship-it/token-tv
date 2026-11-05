"""v2 phase 3a, TokenTV's side of the moments from Claude Code: the courtroom (claude.risky), the ghost
(claude.deleted), the back turned and turned round (claude.rude, claude.calm), the tool faces (claude.failed,
claude.compact) and the thinking word (claude.word:<WORD>, gone with claude.end or claude.stop). The state machine on
a fake clock, the endpoint's names, and what goes on the rows to draw."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import FakeClock  # noqa: E402

from token_tv import live, moments  # noqa: E402
from token_tv.moments import (BACK, COOLDOWN, COURT_LIMIT, COURT_STALE, FACE_COOLDOWN, GHOST,  # noqa: E402
                              WORD_INTERVAL, WORD_STALE, Moments, overlay, urgent, word_of)
from token_tv.sample import D, snapshot  # noqa: E402

NOW = 1793509260


class Turns:
    """moments.RANDOM as a test sets it: each kind of pick takes its options in turn, the first, then the second..."""
    def __init__(self):
        self.asked = []

    def choice(self, options):
        options = tuple(options)
        self.asked.append(options)
        return options[(self.asked.count(options) - 1) % len(options)]


class StateBase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        for patcher in (mock.patch.object(moments, 'CLOCK', self.clock),
                        mock.patch.object(moments, 'RANDOM', Turns())):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.woken = []
        self.m = Moments({'claude', 'codex'}, wake=lambda: self.woken.append(self.clock.t), active=600)

    def at(self, t):
        self.clock.t = t

    def what(self):
        return self.m.wanted()[0]

    def show(self, at=None):
        """The clock starts showing what is due, at `at` (default now)."""
        at = self.clock.t if at is None else at
        what = self.what()
        self.m.shown(what, at)
        return what


class CourtroomTests(StateBase):
    def test_a_risky_command_brings_one_courtroom_drawn_on_clawds_rows(self):
        t0 = self.clock.t
        self.assertTrue(self.m.note('claude.risky'))
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since, mark), (('risky', 'verdict'), t0, {'kind': 'risky', 'style': 'verdict'}))
        self.assertEqual(self.woken, [t0])
        drawn = overlay(snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)]),
                                       ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])]), what, mark)
        self.assertEqual(drawn['accounts']['claude_a']['moment'], {'kind': 'risky', 'style': 'verdict'})
        self.assertNotIn('moment', drawn['accounts']['codex_a'])
        self.assertTrue(self.m.busy())  # the hidden one-offs keep out of its way
        self.m.shown(what, t0 + 2)
        self.assertEqual(self.m.wanted()[:2], (None, t0 + 2))  # one loop, then the usual face

    def test_at_most_one_a_day_from_the_last_ones_start_and_none_kept_for_later(self):
        self.m.note('claude.risky')
        start = self.clock.t + 3
        self.m.shown(self.what(), start)
        count, woken = self.m.count, list(self.woken)
        for t in (start + 1, start + 3600, start + COURT_LIMIT - 1e-3):  # a day not yet over: dropped, all of them
            self.at(t)
            self.assertFalse(self.m.note('claude.risky'))
        self.assertEqual((self.m.count, self.woken, self.what()), (count, woken, None))
        self.at(start + COURT_LIMIT + 3600)  # past the day with no new risky command: nothing comes back
        self.assertIsNone(self.what())
        self.assertIsNone(self.m.next_change())
        self.at(start + COURT_LIMIT)
        self.assertTrue(self.m.note('claude.risky'))  # a day after the last one's start: a new one
        self.assertEqual(self.what(), ('risky', 'objection'))  # (the other variant this time)

    def test_midnight_is_nothing_special_the_day_rolls(self):
        self.m.note('claude.risky')
        self.m.shown(self.what(), self.clock.t)
        self.at(self.clock.t + 60)  # (a fake clock: whatever the date, the 24 hours run from the start)
        self.assertFalse(self.m.note('claude.risky'))

    def test_one_to_show_at_a_time_and_one_while_it_plays_is_dropped(self):
        self.m.note('claude.risky')
        self.assertFalse(self.m.note('claude.risky'))  # one waiting already
        self.assertEqual(moments.RANDOM.asked, [moments.COURTS])  # picked once, for the one kept
        self.m.shown(self.what(), self.clock.t)
        self.assertFalse(self.m.note('claude.risky'))

    def test_it_waits_out_a_wait_and_plays_after_it_and_a_bow_and_a_treat_go_first(self):
        t0 = self.clock.t
        self.m.note('claude.risky')
        self.m.note('claude.ask')
        self.assertEqual(self.what(), ('needs', 1))  # the wait owns the clock
        self.at(t0 + 100)
        self.m.note('claude.answered')
        self.assertEqual(self.m.wanted()[:2], (('risky', 'verdict'), t0))  # still due, from its own time
        self.m.note('claude.end')
        self.m.note('claude.pet')
        self.assertEqual(self.show(), ('done', 'claude'))
        self.assertEqual(self.show(t0 + 110), ('treat', 'pet'))
        self.assertEqual(self.show(t0 + 120), ('risky', 'verdict'))
        self.assertIsNone(self.what())

    def test_one_not_on_the_clock_two_minutes_after_its_command_is_dropped_and_takes_nothing_of_the_day(self):
        t0 = self.clock.t
        self.m.note('claude.risky')
        self.m.note('claude.ask')  # its own prompt, left open
        self.assertEqual(self.m.next_change(), t0 + COURT_STALE)  # (the publisher looks again then)
        self.at(t0 + COURT_STALE - 1e-3)
        self.m.note('claude.answered')  # answered in time: it is still due
        self.assertEqual(self.what(), ('risky', 'verdict'))
        self.at(t0 + COURT_STALE)  # and not on the clock by then: gone, never played later
        self.assertIsNone(self.what())
        self.assertFalse(self.m.busy())
        self.assertIsNone(self.m.next_change())
        self.assertTrue(self.m.note('claude.risky'))  # the day was not used up by it
        self.assertEqual(self.what(), ('risky', 'objection'))

    def test_a_prompt_left_open_till_it_is_let_go_takes_its_courtroom_with_it(self):
        self.m.note('claude.risky')
        self.m.note('claude.ask')
        self.at(self.clock.t + moments.EXPIRE)  # nobody answered: the wait is let go, half an hour on
        self.assertIsNone(self.what())  # no courtroom then

    def test_before_the_break_and_the_tool_faces(self):
        self.m.note('claude.failed')
        self.m.note('claude.risky')
        self.assertEqual(self.show(), ('risky', 'verdict'))
        self.assertEqual(self.show(self.clock.t + 5), ('face', 'failed'))

    def test_no_clock_to_show_it_on_drops_it_and_takes_nothing_of_the_day(self):
        self.m.note('claude.risky')
        self.m.drop_bow()
        self.assertIsNone(self.what())
        self.assertTrue(self.m.note('claude.risky'))  # never shown: the day is not used up

    def test_with_no_claude_account_nothing_happens_and_nothing_is_kept(self):
        m = Moments({'codex'}, active=600)
        for name in ('claude.risky', 'claude.deleted', 'claude.rude', 'claude.calm', 'claude.failed', 'claude.compact',
                     'claude.word:PONDERING', 'claude.stop'):
            self.assertFalse(m.note(name))
        self.assertEqual((m.wanted()[0], m.busy(), m.count, m.next_change()), (None, False, 0, None))
        self.assertTrue(m.note('codex.end'))  # the others' moments are unaffected


class GhostTests(StateBase):
    def test_a_deletion_floats_a_ghost_for_a_minute_from_it(self):
        t0 = self.clock.t
        self.assertTrue(self.m.note('claude.deleted'))
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since), (('state', 'drift', False, None), t0))
        self.assertEqual(mark, {'moment': {'kind': 'deleted', 'style': 'drift'}, 'word': None})
        self.assertFalse(self.m.busy())  # a state of the usual face, not a one-off
        self.assertFalse(urgent(what))
        self.assertEqual(self.m.next_change(), t0 + GHOST)
        self.m.shown(what, t0 + 1)
        self.at(t0 + GHOST - 1e-3)
        self.assertEqual(self.what(), what)
        self.at(t0 + GHOST + 5)  # looked at late: gone from its deadline
        self.assertEqual(self.m.wanted()[:2], (None, t0 + GHOST))
        self.assertIsNone(self.m.next_change())

    def test_more_deletions_in_its_minute_keep_it_the_same_ghost_with_nothing_to_send(self):
        t0 = self.clock.t
        self.m.note('claude.deleted')
        what = self.show()
        count = self.m.count
        self.at(t0 + 30)
        self.assertFalse(self.m.note('claude.deleted'))  # the same picture: nothing changes on the clock
        self.assertEqual(self.m.count, count)
        self.assertEqual(self.m.next_change(), t0 + 30 + GHOST)  # a minute from the fresh one
        self.at(t0 + 30 + GHOST - 1e-3)
        self.assertEqual(self.what(), what)
        self.at(t0 + 30 + GHOST)
        self.assertIsNone(self.what())
        self.assertTrue(self.m.note('claude.deleted'))  # a new deletion later: a new ghost, its own pick
        self.assertEqual(self.what(), ('state', 'wave', False, None))

    def test_a_one_off_hides_it_and_its_minute_runs_on_meanwhile(self):
        t0 = self.clock.t
        self.m.note('claude.deleted')
        self.show()
        self.at(t0 + 20)
        self.m.note('claude.end')
        self.assertEqual(self.show(), ('done', 'claude'))  # the bow over the ghost
        self.assertEqual(self.what(), ('state', 'drift', False, None))  # after it, the ghost still about
        self.at(t0 + 70)  # its minute over while something else might have hidden it: never a fresh minute
        self.assertIsNone(self.what())

    def test_its_minute_over_under_a_wait_it_does_not_come_back(self):
        t0 = self.clock.t
        self.m.note('claude.deleted')
        self.m.note('claude.ask')
        self.at(t0 + GHOST + 1)
        self.m.note('claude.answered')
        self.assertIsNone(self.what())


class BackTests(StateBase):
    def test_a_rude_prompt_turns_its_back_for_a_minute_and_a_fresh_one_from_then(self):
        t0 = self.clock.t
        self.assertTrue(self.m.note('claude.rude'))
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since, mark), (('state', None, True, None), t0, {'moment': {'kind': 'rude'}, 'word': None}))
        self.m.shown(what, t0 + 1)
        self.at(t0 + 40)
        self.assertFalse(self.m.note('claude.rude'))  # the same picture: nothing to send
        self.assertEqual(self.m.next_change(), t0 + 40 + BACK)
        self.at(t0 + 40 + BACK - 1e-3)
        self.assertEqual(self.what(), what)
        self.at(t0 + 40 + BACK)  # its minute up while on the clock: Clawd turns back round, one loop
        self.assertEqual(self.m.wanted()[:3], (('calm',), t0 + 40 + BACK, {'kind': 'calm'}))
        self.assertTrue(self.m.busy())
        self.m.shown(('calm',), t0 + 101)
        self.assertEqual(self.m.wanted()[:2], (None, t0 + 101))

    def test_a_calm_prompt_turns_it_round_at_once_if_the_clock_showed_the_back(self):
        t0 = self.clock.t
        self.m.note('claude.rude')
        self.show()
        self.at(t0 + 20)
        self.assertTrue(self.m.note('claude.calm'))
        self.assertEqual(self.m.wanted()[:2], (('calm',), t0 + 20))
        self.show()
        self.at(t0 + 200)  # its old minute: nothing then
        self.assertIsNone(self.what())
        self.assertFalse(self.m.note('claude.calm'))  # calm while calm: nothing

    def test_rude_then_calm_before_the_clock_showed_it_is_nothing_at_all(self):
        count = self.m.count
        self.m.note('claude.rude')
        self.m.note('claude.calm')
        self.assertIsNone(self.what())  # no back, and no turning round from a back never shown
        self.m.note('claude.calm')
        self.m.note('claude.rude')
        self.assertEqual(self.what(), ('state', None, True, None))  # the last one stands: rude
        for _ in range(3):
            self.m.note('claude.calm')
            self.m.note('claude.rude')
        self.m.note('claude.calm')
        self.assertIsNone(self.what())
        self.assertGreater(self.m.count, count)

    def test_rude_again_while_it_turns_round_keeps_the_back_turned(self):
        self.m.note('claude.rude')
        self.show()
        self.m.note('claude.calm')
        self.assertEqual(self.what(), ('calm',))
        self.m.note('claude.rude')
        self.assertEqual(self.what(), ('state', None, True, None))  # the picture on the clock already: no flash

    def test_a_back_hidden_by_a_moment_as_it_ends_does_not_turn_round_later(self):
        t0 = self.clock.t
        self.m.note('claude.rude')
        self.show()
        self.m.note('claude.pet')
        self.assertEqual(self.show(), ('treat', 'pet'))
        self.at(t0 + BACK + 1)  # its minute over while the pat played
        self.assertIsNone(self.what())
        self.m.note('claude.rude')
        self.show()
        self.m.note('claude.ask')
        self.show()
        self.m.note('claude.calm')  # calm under a wait: the wait stands, and no turning round after it
        self.m.note('claude.answered')
        self.assertIsNone(self.what())

    def test_something_else_going_on_first_drops_the_turn_round(self):
        self.m.note('claude.rude')
        self.show()
        self.m.note('claude.calm')
        self.m.note('claude.end')
        self.assertEqual(self.show(), ('done', 'claude'))
        self.assertIsNone(self.what())

    def test_a_sulking_clawd_does_not_bow_not_even_for_the_rude_prompts_own_turn(self):
        t0 = self.clock.t
        self.m.note('claude.end')  # a turn before it: its bow still to show...
        self.m.note('claude.rude')  # ...goes as the back turns
        self.assertEqual(self.what(), ('state', None, True, None))
        self.at(t0 + 5)
        self.assertFalse(self.m.note('claude.end'))  # the rude prompt's own turn: no bow
        self.show()
        self.at(t0 + 20)
        self.assertFalse(self.m.note('claude.end'))  # nor another while the back is turned
        self.assertEqual(self.what(), ('state', None, True, None))
        self.assertTrue(self.m.note('codex.end'))  # Codex's cloud does not sulk: it bows
        self.assertEqual(self.show(), ('done', 'codex'))
        self.m.note('claude.calm')  # turned round...
        self.at(t0 + 20 + COOLDOWN)
        self.assertTrue(self.m.note('claude.end'))  # ...Clawd bows again
        self.assertEqual(self.what(), ('done', 'claude'))

    def test_a_rude_prompts_turn_that_outlasts_the_minute_bows(self):
        t0 = self.clock.t
        self.m.note('claude.rude')
        self.show()
        self.at(t0 + BACK + 30)  # a long turn: Clawd turned back round meanwhile
        self.assertEqual(self.show(), ('calm',))
        self.assertTrue(self.m.note('claude.end'))
        self.assertEqual(self.what(), ('done', 'claude'))

    def test_with_a_ghost_about_too_both_are_drawn_and_each_keeps_its_own_minute(self):
        t0 = self.clock.t
        self.m.note('claude.deleted')
        self.at(t0 + 10)
        self.m.note('claude.rude')
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since), (('state', 'drift', True, None), t0 + 10))
        self.assertEqual(mark['moment'], {'kind': 'rude', 'ghost': 'drift'})
        self.m.shown(what, t0 + 11)
        self.at(t0 + 30)
        self.m.note('claude.calm')  # the back turns round; the ghost floats on
        self.assertEqual(self.what(), ('calm',))
        self.show()
        self.assertEqual(self.what(), ('state', 'drift', False, None))
        self.m.note('claude.deleted')  # a deletion keeps the ghost: it does not put the back round again
        self.at(t0 + 30 + GHOST)
        self.assertIsNone(self.what())


class ToolFaceTests(StateBase):
    def test_a_failure_or_a_compaction_is_one_loop_of_its_face_on_clawds_rows(self):
        for name, kind in (('claude.failed', 'failed'), ('claude.compact', 'compact')):
            self.at(self.clock.t + 100)
            self.assertTrue(self.m.note(name))
            what, since, mark = self.m.wanted()
            self.assertEqual((what, since, mark), (('face', kind), self.clock.t, {'kind': kind}))
            self.assertTrue(self.m.busy())
            self.m.shown(what, self.clock.t + 1)
            self.assertIsNone(self.what())

    def test_one_face_in_any_rolling_minute_shared_by_the_two_from_its_start(self):
        self.m.note('claude.failed')
        start = self.clock.t + 2
        self.m.shown(self.what(), start)
        for t, name in ((start + 1, 'claude.compact'), (start + 30, 'claude.failed'), (start + FACE_COOLDOWN - 1e-3,
                                                                                       'claude.compact')):
            self.at(t)
            self.assertFalse(self.m.note(name))  # dropped, not saved for the minute's end
        self.at(start + FACE_COOLDOWN + 10)
        self.assertIsNone(self.what())  # nothing comes back with time alone
        self.at(start + FACE_COOLDOWN)
        self.assertTrue(self.m.note('claude.compact'))

    def test_a_face_to_show_takes_no_other_and_one_while_waiting_is_dropped(self):
        self.m.note('claude.compact')
        self.assertFalse(self.m.note('claude.failed'))
        self.assertEqual(self.what(), ('face', 'compact'))
        self.m.note('claude.ask')  # a wait drops the one not shown
        self.m.note('claude.failed')
        self.m.note('claude.answered')
        self.assertIsNone(self.what())

    def test_the_lowest_of_them_all_after_the_others_and_the_break(self):
        self.m.note('claude.failed')
        for name in ('claude.end', 'claude.pet', 'claude.risky'):
            self.m.note(name)
        self.assertEqual([self.show(self.clock.t + k) for k in range(5)],
                         [('done', 'claude'), ('treat', 'pet'), ('risky', 'verdict'), ('face', 'failed'), None])

    def test_its_minute_is_its_own_not_the_bows(self):
        self.m.note('claude.end')
        self.show()
        self.m.note('claude.failed')
        self.assertEqual(self.show(), ('face', 'failed'))  # inside the bow's minute
        self.assertFalse(self.m.note('claude.end'))  # and the bows' minute holds for bows alone
        self.assertTrue(self.m.cooling(self.clock.t))


class WordTests(StateBase):
    def test_the_word_shows_in_place_of_the_usual_one_and_the_same_again_changes_nothing(self):
        t0 = self.clock.t
        self.assertTrue(self.m.note('claude.word:Pondering'))
        what, since, mark = self.m.wanted()
        self.assertEqual((what, since, mark), (('state', None, False, 'PONDERING'), t0, {'moment': None, 'word': 'PONDERING'}))
        drawn = overlay(snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)]),
                                       ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])]), what, mark)
        self.assertEqual(drawn['accounts']['claude_a']['word'], 'PONDERING')
        self.assertNotIn('moment', drawn['accounts']['claude_a'])
        self.assertNotIn('word', drawn['accounts']['codex_a'])
        count = self.m.count
        for _ in range(5):
            self.assertFalse(self.m.note('claude.word:PONDERING'))
        self.assertEqual(self.m.count, count)

    def test_a_new_word_at_most_once_a_minute_from_the_last_ones_start_the_newest_waiting(self):
        self.m.note('claude.word:Pondering')
        start = self.clock.t + 1
        self.m.shown(self.what(), start)
        self.at(start + 10)
        self.assertFalse(self.m.note('claude.word:Brewing'))  # inside the minute: waits
        self.assertFalse(self.m.note('claude.word:Baking'))  # the newest waits instead
        self.assertEqual(self.what(), ('state', None, False, 'PONDERING'))
        self.assertEqual(self.m.next_change(), start + WORD_INTERVAL)
        self.at(start + WORD_INTERVAL - 1e-3)
        self.assertEqual(self.what()[3], 'PONDERING')
        self.at(start + WORD_INTERVAL)
        self.assertEqual(self.m.wanted()[:2], (('state', None, False, 'BAKING'), start + WORD_INTERVAL))
        self.m.shown(self.what(), start + 61)
        self.at(start + 61 + WORD_INTERVAL + 5)
        self.assertTrue(self.m.note('claude.word:Musing'))  # past the minute: at once

    def test_a_newer_word_gives_way_when_the_shown_one_is_said_again(self):
        self.m.note('claude.word:Pondering')
        self.show()
        self.m.note('claude.word:Brewing')
        self.m.note('claude.word:Pondering')
        self.at(self.clock.t + WORD_INTERVAL + 1)
        self.assertEqual(self.what()[3], 'PONDERING')

    def test_words_before_the_first_is_shown_replace_it_never_queue(self):
        for word in ('Pondering', 'Brewing', 'Musing'):
            self.m.note('claude.word:' + word)
        self.assertEqual(self.what(), ('state', None, False, 'MUSING'))

    def test_the_turns_end_takes_the_word_at_once_into_the_bow_and_a_cut_turn_without_one(self):
        t0 = self.clock.t
        self.m.note('claude.word:Pondering')
        self.m.shown(self.what(), t0)
        self.at(t0 + 5)
        self.m.note('claude.word:Brewing')  # waiting for the minute
        self.m.note('claude.end')
        self.assertEqual(self.m.wanted()[0], ('done', 'claude'))  # the bow, no word: one picture for both
        self.m.shown(('done', 'claude'), t0 + 6)
        self.assertEqual(self.m.wanted()[:2], (None, t0 + 6))
        self.at(t0 + 61)
        self.assertIsNone(self.what())  # the waiting word went with the turn
        self.m.note('claude.word:Musing')  # a new turn: its word, at most a minute after the last one's start
        self.assertEqual(self.what(), ('state', None, False, 'MUSING'))
        self.m.shown(self.what(), t0 + 62)
        self.at(t0 + 70)
        self.assertTrue(self.m.note('claude.stop'))  # cut short: the word goes, no bow
        self.assertEqual(self.m.wanted()[:2], (None, t0 + 70))
        self.at(t0 + 80)
        self.assertFalse(self.m.note('claude.word:Musing'))  # the same word, a new turn: inside the minute, waits
        self.assertIsNone(self.what())
        self.at(t0 + 62 + WORD_INTERVAL)
        self.assertEqual(self.what()[3], 'MUSING')

    def test_the_same_word_in_a_new_turn_is_a_new_start_on_the_clock(self):
        self.m.note('claude.word:Pondering')
        first = self.clock.t
        self.m.shown(self.what(), first)
        self.at(first + 5)
        self.m.note('claude.end')
        self.m.shown(self.what(), first + 6)  # the bow
        self.at(first + 100)
        self.m.note('claude.word:Pondering')  # the next turn happens to say it again
        again = first + 101
        self.m.shown(self.what(), again)
        self.at(again + 10)
        self.assertFalse(self.m.note('claude.word:Brewing'))  # a minute from its new start, not from the old one
        self.at(again + WORD_INTERVAL)
        self.assertEqual(self.what()[3], 'BREWING')

    def test_a_word_behind_the_ghost_or_the_sulk_starts_its_minute_once_it_shows(self):
        self.m.note('claude.deleted')
        self.m.note('claude.word:Musing')
        self.m.shown(self.what(), self.clock.t)  # the ghost's BOO! in the readout, the word not yet
        self.at(self.clock.t + GHOST + 1)
        self.assertEqual(self.what(), ('state', None, False, 'MUSING'))
        shows = self.clock.t
        self.m.shown(self.what(), shows)  # now it shows
        self.at(shows + 5)
        self.assertFalse(self.m.note('claude.word:Herding'))  # a minute from when it showed, not from the ghost's
        self.at(shows + WORD_INTERVAL)
        self.assertEqual(self.what()[3], 'HERDING')

    def test_a_word_behind_slow_starts_its_minute_once_it_is_the_label(self):
        self.m.note('claude.word:Pondering')
        self.m.shown(self.what(), self.clock.t, readable=False)  # SLOW holds the readout: the word is not read
        self.at(self.clock.t + 5)
        self.assertTrue(self.m.note('claude.word:Brewing'))  # no minute started: it takes the word's place at once
        self.m.shown(self.what(), self.clock.t, readable=False)
        self.at(self.clock.t + 300)
        shows = self.clock.t
        self.m.shown(self.what(), shows)  # SLOW lifts: now it is read
        self.at(shows + 5)
        self.assertFalse(self.m.note('claude.word:Musing'))  # a minute from when it was read
        self.at(shows + WORD_INTERVAL)
        self.assertEqual(self.what()[3], 'MUSING')

    def test_a_newer_word_waiting_wakes_the_publisher_for_its_minutes_end(self):
        self.m.note('claude.word:Pondering')
        start = self.clock.t
        self.m.shown(self.what(), start)
        self.at(start + 32)
        woken = list(self.woken)
        self.assertFalse(self.m.note('claude.word:Musing'))  # nothing to show yet...
        self.assertEqual(self.woken, woken + [start + 32])  # ...but the publisher plans its next look again
        self.assertEqual(self.m.next_change(), start + WORD_INTERVAL)
        self.assertFalse(self.m.note('claude.word:Baking'))  # a newer one in its place comes no sooner
        self.assertEqual(self.woken, woken + [start + 32])

    def test_a_cut_turn_leaves_no_bow_and_nothing_queued(self):
        self.m.note('claude.word:Pondering')
        self.assertTrue(self.m.note('claude.stop'))
        self.assertIsNone(self.what())
        self.assertFalse(self.m.note('claude.stop'))
        self.assertIsNone(self.m.bow)

    def test_a_word_nobody_says_again_goes_stale(self):
        t0 = self.clock.t
        self.m.note('claude.word:Pondering')
        self.show()
        self.at(t0 + 600)
        self.m.note('claude.word:Pondering')  # said again: still on, and heard from now
        self.assertEqual(self.m.next_change(), t0 + 600 + WORD_STALE)
        self.at(t0 + 600 + WORD_STALE)
        self.assertEqual(self.m.wanted()[:2], (None, t0 + 600 + WORD_STALE))

    def test_waits_and_moments_hide_the_word_and_it_returns_after_them_with_its_own_start(self):
        self.m.note('claude.word:Pondering')
        start = self.clock.t
        self.m.shown(self.what(), start)
        self.m.note('claude.ask')
        self.assertEqual(self.show(), ('needs', 1))
        self.at(start + 300)
        self.m.note('claude.answered')
        self.assertEqual(self.what(), ('state', None, False, 'PONDERING'))
        self.m.shown(self.what(), start + 301)  # the same word again: not a new word's start
        self.at(start + 302)
        self.assertTrue(self.m.note('claude.word:Brewing'))  # its minute ran from its first start

    def test_only_one_word_of_letters_a_to_z_up_to_fourteen(self):
        for name in ('claude.word:PONDERING', 'claude.word:a', 'claude.word:WWWWWWWWWWWWWW', 'claude.word:Pondering'):
            self.assertIsNotNone(word_of(name), name)
        for name in ('claude.word:', 'claude.word:WWWWWWWWWWWWWWW', 'claude.word:two words', 'claude.word:Ponder1ng',
                     'claude.word:A:B', 'claude.word:Ponder_ing', 'claude.word:Ponder-ing', 'claude.word:Pondering\n',
                     'claude.word: Pondering', 'claude.word:Sautéing', 'claude.word:生각', 'Claude.word:A', 'claude.Word:A',
                     'claude.words:A', 'claude.word', 'codex.word:A', 'claude.word:<b>', 'claude.word:Ponde​ring',
                     None, 42, ['claude.word:A']):
            self.assertIsNone(word_of(name), name)
            if isinstance(name, str):
                with self.assertRaises(ValueError):
                    self.m.note(name)
        self.assertIsNone(self.what())


class EndpointTests(unittest.TestCase):
    def test_the_new_names_and_one_word_and_nothing_like_them(self):
        for name in ('claude.risky', 'claude.deleted', 'claude.rude', 'claude.calm', 'claude.failed', 'claude.compact',
                     'claude.stop', 'claude.word:Pondering', 'claude.word:A'):
            body = json.dumps({'moment': name}).encode()
            self.assertEqual(live.moment_of(body), name)
        for body in (b'{"moment":"claude.word:"}', b'{"moment":"claude.word:Two Words"}', b'{"moment":"claude.word:A:B"}',
                     b'{"moment":"claude.word:ABCDEFGHIJKLMNO"}', b'{"moment":"claude.Risky"}', b'{"moment":"claude.risky "}',
                     b'{"moment":"claude.risky","command":"rm -rf /"}', b'{"moment":"claude.word:Pondering","word":"x"}',
                     b'{"moment":["claude.risky"]}', b'{"moment":{"word":"A"}}', b'{"moment":"claude.word:P\\u00e9"}',
                     b'{"moment":"claude.risky","moment":"claude.rude"}', b'{"moment":"claude.sound"}',
                     b'{"moment":"claude.word:Pondering\\n"}', b'["claude.risky"]', b'{"moment":"claude.idle"}'):
            with self.assertRaises(ValueError, msg=body):
                live.moment_of(body)

    def test_the_states_are_no_moment_a_one_off_keeps_out_of_the_way_of(self):
        self.assertFalse(urgent(None))
        self.assertFalse(urgent(('state', 'drift', True, 'PONDERING')))
        for what in (('needs', 1), ('done', 'claude'), ('treat', 'pet'), ('risky', 'verdict'), ('break', 'drink'),
                     ('calm',), ('face', 'failed'), ('unsure',)):
            self.assertTrue(urgent(what), what)

    def test_drawing_a_state_copies_the_rows_and_changes_no_reading(self):
        data = snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', [('WEEK', 40, 3 * D)]),
                              ('claude_b', 'CLAUDE B', 'claude', [('WEEK', 50, 3 * D)])])
        before = json.dumps(data, sort_keys=True)
        what = ('state', 'wave', True, 'MUSING')
        mark = {'moment': {'kind': 'rude', 'ghost': 'wave'}, 'word': 'MUSING'}
        drawn = overlay(data, what, mark)
        self.assertEqual(json.dumps(data, sort_keys=True), before)
        for key in ('claude_a', 'claude_b'):  # every Claude account shows it (Claude Code says not which)
            self.assertEqual((drawn['accounts'][key]['moment'], drawn['accounts'][key]['word']),
                             ({'kind': 'rude', 'ghost': 'wave'}, 'MUSING'))
        self.assertIsNot(drawn['accounts']['claude_a']['moment'], drawn['accounts']['claude_b']['moment'])


if __name__ == '__main__':
    unittest.main()
