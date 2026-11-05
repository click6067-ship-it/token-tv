"""v2 phase 2, a mixed virtual run (v2p2-43): hours of two services' work with a short gap, a full break and a wait
across the hour's end, pets and snacks with repeats, bows, through live.main on the fake SD_PRO. Every picture goes
on at a real loop end of the one before it (its own pictures, each for its delay but at least 142 ms), the breaks
come once an hour of work each and both kinds show, and nothing pressed or asked comes back later."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from test_moments import Rig, physical  # noqa: E402

from token_tv import moments  # noqa: E402
from token_tv.moments import BREAK, WORK  # noqa: E402
from token_tv.sample import H  # noqa: E402
from token_tv.state import ACTIVE_SECONDS  # noqa: E402

APPLY_SLACK = .25


class Picks:
    def __init__(self, *kinds):
        self.kinds = list(kinds)

    def choice(self, options):
        return self.kinds.pop(0)


class MixedRunTests(unittest.TestCase):
    def test_hours_of_mixed_work_and_moments(self):
        patcher = mock.patch.object(moments, 'RANDOM', Picks('drink', 'stretch', 'drink', 'stretch'))
        patcher.start()
        self.addCleanup(patcher.stop)
        rig = Rig(self, providers=('claude', 'codex'), wall=True,
                  windows={'claude': [('5H', 20, 5 * H)], 'codex': [('5H', 20, 5 * H)]})
        minute = lambda m: rig.t0 + 60 * m  # noqa: E731
        idle = set(range(70, 85)) | set(range(140, 165))  # a short gap, then a whole break with nobody at work
        moments_at = {30: ['claude.pet', 'claude.pet', 'claude.snack'], 40: ['claude.end'], 41: ['claude.end'],
                      55: ['claude.ask'], 64: ['claude.answered'], 100: ['claude.snack', 'claude.snack'],
                      120: ['codex.end'], 121: ['claude.pet']}
        used = {'claude_a': 20.0, 'codex_a': 20.0}
        first_rise = None
        for m in range(1, 231):
            if m not in idle:
                used['codex_a'] += .002  # (never enough to change the picture)
                rig.set('codex_a', '5H', used['codex_a'])
                if first_rise is None:
                    first_rise = minute(m)
                if m % 5 == 0:
                    used['claude_a'] += .002
                    rig.set('claude_a', '5H', used['claude_a'])
            rig.write(rig.now() + minute(m) - rig.clock.now())
            rig.clock.to(minute(m) + .5)
            for name in moments_at.get(m, []):
                rig.say(name)
                rig.clock.advance(.3)
        rig.clock.advance(60)
        played = rig.played
        self.assertGreater(len(played), 10)
        # every picture on at a real loop end of the one before it: its own pictures, counted from its own start
        for (began, image), (then, _) in zip(played, played[1:]):
            loop = physical(image)
            loops = (then - began) / loop
            k = max(1, int(loops))
            self.assertTrue(began + k * loop <= then + 1e-6 < began + k * loop + APPLY_SLACK
                            or began + (k + 1) * loop <= then + 1e-6 < began + (k + 1) * loop + APPLY_SLACK,
                            (began - rig.t0, then - rig.t0, loop))
        drawn = {}  # which moment each played picture is, drawn independently from the readings TokenTV holds
        held = rig.held()
        for what in (('break', 'drink'), ('break', 'stretch'), ('treat', 'pet'), ('treat', 'snack'),
                     ('done', 'claude'), ('done', 'codex'), ('needs', 1)):
            drawn[rig.picture(what, snapshot=held)] = what
        seen = [(t - rig.t0, drawn.get(image)) for t, image in played if drawn.get(image)]
        kinds = [what for _, what in seen]
        self.assertIn(('break', 'drink'), kinds)
        self.assertIn(('break', 'stretch'), kinds)
        self.assertEqual([what for what in kinds if what[0] == 'treat'],
                         [('treat', 'pet'), ('treat', 'snack'), ('treat', 'pet')])  # one each time, repeats dropped
        self.assertEqual([what for what in kinds if what[0] == 'done'], [('done', 'claude'), ('done', 'codex')])
        breaks = [t + rig.t0 for t, what in seen if what[0] == 'break']
        self.assertEqual(len(breaks), 3)
        # an independent oracle of the hour of work, from the rises this test made (Codex's, every working minute)
        rises = [minute(m) for m in range(1, 231) if m not in idle]

        def due(start):
            """When WORK of work since `start` is done: the union of [rise, rise + ACTIVE) after it."""
            t, credit = start, 0.0
            for r, nxt in zip(rises, rises[1:] + [float('inf')]):
                if r + ACTIVE_SECONDS <= start:
                    continue
                begin, end = max(r, start, t), min(r + ACTIVE_SECONDS, nxt)
                if end > begin:
                    if credit + end - begin >= WORK:
                        return begin + WORK - credit
                    credit += end - begin
                t = max(t, end)
            return None
        answered = minute(64)
        self.assertLess(due(first_rise), answered)  # the first hour came due while Claude waited (55-64 min)
        self.assertTrue(answered <= breaks[0] < answered + 10)  # so its break came at the wait's end, not before
        self.assertTrue(due(breaks[0]) <= breaks[1] < due(breaks[0]) + 10)  # an hour of work from its showing
        back = min(r for r in rises if r > minute(140))  # the first rise after the break with nobody at work
        self.assertGreaterEqual(back - (minute(139) + ACTIVE_SECONDS), BREAK)
        self.assertTrue(due(back) <= breaks[2] < due(back) + 10)  # a new hour from it: no credit from before


if __name__ == '__main__':
    unittest.main()
