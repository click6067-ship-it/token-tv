"""v2 phase 3a, a mixed virtual run: two hours of Claude and Codex with risky commands, bursts of deletions, rude and
calm prompts, failures and compactions close together, thinking words changing fast, a wait, bows, a pat and a cut
turn, through live.main on the fake SD_PRO. Every picture goes on at a real loop end of the one before it, one
courtroom in the day, tool faces and new words at least a minute apart, and the usual face at the end."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_claude_3a import Turns  # noqa: E402
from test_moments import Rig, physical  # noqa: E402

from token_tv import moments  # noqa: E402
from token_tv.moments import FACE_COOLDOWN, WORD_INTERVAL, Moments  # noqa: E402
from token_tv.sample import H  # noqa: E402

APPLY_SLACK = .25


class MixedRunTests(unittest.TestCase):
    def test_two_hours_of_phase_3a_moments_among_the_others(self):
        shows = []  # (what, when, its word read?) as each picture went on the clock (the publisher tells Moments.shown)
        real = Moments.shown

        def shown(self, what, at, wall=None, readable=True):
            shows.append((what, at, readable))
            return real(self, what, at, wall, readable)
        for patcher in (mock.patch.object(moments, 'RANDOM', Turns()), mock.patch.object(Moments, 'shown', shown)):
            patcher.start()
            self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('claude', 'codex'), wall=True,
                  windows={'claude': [('5H', 20, 5 * H)], 'codex': [('5H', 20, 5 * H)]})
        minute = lambda m: rig.t0 + 60 * m  # noqa: E731
        script = {
            2: ['claude.word:Pondering', 'claude.word:Brewing', 'claude.word:Musing'],  # fast words
            3: ['claude.risky', 'claude.deleted', 'claude.deleted'],  # rm -rf: the courtroom, then the ghost
            4: ['claude.word:Herding', 'claude.failed', 'claude.compact'],
            5: ['claude.failed', 'claude.end'],
            8: ['claude.rude', 'claude.calm', 'claude.rude'],
            9: ['claude.deleted', 'claude.word:Baking'],
            10: ['claude.calm', 'claude.ask'],
            12: ['claude.risky', 'claude.compact', 'claude.word:Sauteing'],  # (the day's courtroom is used up)
            14: ['claude.answered', 'codex.end'],
            15: ['claude.pet', 'claude.failed', 'claude.deleted'],
            20: ['claude.rude', 'claude.word:Accomplishing'],
            21: ['claude.stop'],
            30: ['claude.word:Pondering', 'claude.compact'],
            31: ['claude.end', 'claude.failed'],
            45: ['claude.risky', 'claude.rude', 'claude.deleted', 'claude.word:Musing'],
            46: ['claude.calm', 'claude.stop'],
        }
        for m in range(1, 121):
            rig.write(rig.now())
            rig.clock.to(minute(m) + .5)
            for name in script.get(m, []):
                rig.say(name)
                rig.clock.advance(.7)
        rig.clock.advance(120)
        played = rig.played
        self.assertGreater(len(played), 15)
        # every picture on at a real loop end of the one before it: its own pictures, counted from its own start
        for (began, image), (then, _) in zip(played, played[1:]):
            loop = physical(image)
            k = max(1, int((then - began) / loop))
            self.assertTrue(began + k * loop <= then + 1e-6 < began + k * loop + APPLY_SLACK
                            or began + (k + 1) * loop <= then + 1e-6 < began + (k + 1) * loop + APPLY_SLACK,
                            (began - rig.t0, then - rig.t0, loop))
        on = [(what, at) for what, at, _ in shows if what not in (None, ('unsure',))]
        kinds = [what[0] for what, _ in on]
        self.assertEqual(kinds.count('risky'), 1)  # three risky commands, one courtroom in the day
        faces = [at for what, at in on if what[0] == 'face']
        self.assertGreaterEqual(len(faces), 2)
        self.assertTrue(all(b - a >= FACE_COOLDOWN - 1e-6 for a, b in zip(faces, faces[1:])), faces)
        starts, last = [], None  # a new word's start each time a picture shows another word in the readout
        for what, at, readable in shows:  # (behind BOO!, SULKING or SLOW it is in the picture, not read)
            word = what[3] if what and what[0] == 'state' and not (what[1] or what[2]) and readable else None
            if word and word != last:
                starts.append((word, at))
                last = word
        self.assertGreaterEqual(len(starts), 3)
        self.assertTrue(all(b[1] - a[1] >= WORD_INTERVAL - 1e-6 for a, b in zip(starts, starts[1:])), starts)
        self.assertIn('calm', kinds)  # the back turned round on the clock at least once
        self.assertIn('needs', kinds)
        self.assertIn('treat', kinds)
        self.assertEqual(rig.showing()[0], rig.picture())  # at the end the usual face: no word, ghost or back left


if __name__ == '__main__':
    unittest.main()
