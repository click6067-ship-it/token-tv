"""v2 phase 3a, the drawings: Clawd's courtroom (two variants), the ghost of a deleted file (two), its back turned
and the turn back round, dizzy, the squeeze, and the thinking word in the readout, as the owner approved them
(drafts w17-w23). Each moves through its loop with its own props, says its own word, and is Clawd's alone."""
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from token_tv import arcade, readout, seasons
from token_tv import claude_moments as cm
from token_tv.sample import D, H, snapshot

ROOT = Path(__file__).resolve().parent.parent
NOW = 1793509260  # a fixed instant for the drawings (the page's own)
WINDOWS = [('5H', 42, 2 * H), ('WEEK', 64, 3 * D)]


def frames(image):
    gif = Image.open(io.BytesIO(image))
    out = []
    for n in range(gif.n_frames):
        gif.seek(n)
        out.append(gif.convert('RGB'))
    return out


def colours(image):
    return {c for _, c in image.getcolors(1 << 16)}


class Base(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(arcade, 'NIGHT_HOURS', ()), mock.patch.object(readout, 'STYLE', 'battery')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def data(self, mark=None, *others, **row):
        data = snapshot(NOW, [('claude_a', 'CLAUDE A', 'claude', WINDOWS)] + list(others))
        if mark:
            data['accounts']['claude_a']['moment'] = mark
        data['accounts']['claude_a'].update(row)
        return data

    def stages(self, moment=None, **row):
        shots = frames(arcade.render_arcade(self.data(moment, **row), NOW))
        return [shot.crop((0, 28, 240, 170)) for shot in shots], shots

    def label(self, moment=None, **row):
        """What the readout says for Claude's row, and whether that is drawn in Clawd's line."""
        data = self.data(moment, **row)
        line = dict(data['accounts']['claude_a'], key='claude_a')
        plan = arcade.scene_plan(line, NOW)
        return arcade.action_label(line, plan, None, 0, arcade.FRAMES)


class SceneTests(Base):
    CASES = (  # (moment, its word, an ink only its props bring)
        ({'kind': 'risky', 'style': 'verdict'}, 'ORDER!', cm.GOLD),
        ({'kind': 'risky', 'style': 'objection'}, 'OBJECTION!', cm.BURST_EDGE),
        ({'kind': 'deleted', 'style': 'drift'}, 'BOO!', cm.GHOST_INK['W']),
        ({'kind': 'deleted', 'style': 'wave'}, 'BOO!', cm.GHOST_INK['W']),
        ({'kind': 'rude'}, 'SULKING', cm.STEAM),
        ({'kind': 'rude', 'ghost': 'drift'}, 'SULKING', cm.GHOST_INK['W']),
        ({'kind': 'calm'}, 'FORGIVEN', (255, 92, 136)),
        ({'kind': 'failed'}, 'DIZZY', cm.STAR),
        ({'kind': 'compact'}, 'COMPACTING', (105, 154, 203)),
    )

    def test_each_moves_through_its_loop_with_its_own_props_and_says_its_own_word(self):
        usual = self.stages()[0]
        for moment, word, ink in self.CASES:
            with self.subTest(moment=moment):
                stages, _ = self.stages(moment)
                self.assertGreater(len({s.tobytes() for s in stages}), 15)  # moving, not a still with a label
                self.assertTrue(any(ink in colours(s) for s in stages))
                self.assertFalse(any(ink in colours(s) for s in usual))  # (none of the usual scene's inks)
                self.assertEqual(self.label(moment), word)

    def test_the_two_variants_differ_and_a_style_left_out_is_the_first(self):
        for kind, styles in (('risky', cm.COURTS), ('deleted', cm.GHOSTS)):
            first, second = (arcade.render_arcade(self.data({'kind': kind, 'style': s}), NOW) for s in styles)
            self.assertNotEqual(first, second)
            self.assertEqual(arcade.render_arcade(self.data({'kind': kind}), NOW), first)

    def test_clawd_from_behind_shows_no_eyes_and_turns_round_to_glare(self):
        ink = lambda grid: {c for row in grid for c in row}  # noqa: E731
        self.assertNotIn(cm.DARK, ink(cm.back()))  # its back to you: no eyes
        self.assertNotIn(cm.DARK, ink(cm.back_quarter()))
        self.assertIn(cm.DARK, ink(cm.edited(cm.grid('Turning', 20), 'frown')))  # the glare over its shoulder
        self.assertEqual(len(cm.back()), len(cm.grid('LookingAround', 0)))  # its own form, from behind
        self.assertEqual({c for c in ink(cm.back()) if c} - {None}, {c for c in ink(cm.grid('LookingAround', 0))
                                                                     if c and c != cm.DARK})

    def test_with_a_ghost_about_the_sulk_and_the_ghost_are_both_drawn(self):
        alone, _ = self.stages({'kind': 'rude'})
        haunted, _ = self.stages({'kind': 'rude', 'ghost': 'wave'})
        self.assertNotEqual([s.tobytes() for s in alone], [s.tobytes() for s in haunted])
        self.assertTrue(any(cm.STEAM in colours(s) for s in haunted))

    def test_the_ghost_floats_over_what_clawd_does_at_work_too(self):
        for active in (False, True):
            usual, _ = self.stages(active=active)
            ghost, _ = self.stages({'kind': 'deleted', 'style': 'drift'}, active=active)
            self.assertNotEqual([s.tobytes() for s in usual], [s.tobytes() for s in ghost])

    def test_only_clawd_does_them_another_pet_keeps_its_own_loop(self):
        other = ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])
        plain = self.data(None, other)
        for moment, _, _ in self.CASES:
            marked = self.data(moment, other)
            self.assertEqual([r['provider'] for r in arcade.shown_rows(marked, NOW)], ['claude', 'codex'])
            usual, shots = arcade.arcade_frames(plain, NOW), arcade.arcade_frames(marked, NOW)
            half = len(shots) // 2  # Clawd's turn, then the Codex cloud's
            stage = lambda frame: frame.crop((0, 28, 240, 170)).tobytes()  # noqa: E731
            self.assertEqual([stage(f) for f in shots[half:]], [stage(f) for f in usual[half:]])
            self.assertNotEqual([stage(f) for f in shots[:half]], [stage(f) for f in usual[:half]])

    def test_a_moment_or_a_word_brings_clawd_into_the_loop_beside_pets_at_work(self):
        busy = ('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])
        data = self.data(None, busy)
        data['accounts']['codex_a']['active'] = True
        self.assertEqual([r['provider'] for r in arcade.shown_rows(data, NOW)], ['codex'])  # Clawd resting: not shown
        for extra in ({'moment': {'kind': 'failed'}}, {'moment': {'kind': 'deleted', 'style': 'drift'}},
                      {'word': 'PONDERING'}, {'moment': {'kind': 'risky', 'style': 'verdict'}}):
            joined = self.data(None, busy, **extra)
            joined['accounts']['codex_a']['active'] = True
            self.assertEqual([r['provider'] for r in arcade.shown_rows(joined, NOW)], ['claude', 'codex'], extra)

    def test_the_drawings_are_the_approved_drafts_byte_for_byte(self):
        drafts = ROOT / 'docs' / 'design' / 'v2_phase3a_drafts.py'
        if not drafts.exists():
            self.skipTest('the drafts are kept in the private tree only')
        # The drafts as drawn, plugged into Arcade in a process of their own (they change it for that run); off season
        # on both sides, as they were drawn before the seasons (x8: NOW is Halloween's last day).
        script = f'''
import sys
sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(drafts.parent)!r})
from token_tv import arcade, readout, seasons
from token_tv.sample import D, H, snapshot
import v2_phase3a_drafts as drafts
readout.STYLE = 'battery'; arcade.NIGHT_HOURS = (); drafts.install(); seasons.season_at = lambda at=None: None
for kind, style, row in {[(m['kind'], m.get('style') if m.get('style') not in ('verdict', 'drift') else None, r)
                          for m, r in self.ITEMS]!r}:
    data = snapshot({NOW}, [('claude_a', 'CLAUDE A', 'claude', {WINDOWS!r})])
    if kind:
        data['accounts']['claude_a']['moment'] = dict({{'kind': kind, 'at': {NOW}}}, **({{'style': style}} if style else {{}}))
    data['accounts']['claude_a'].update(row)
    sys.stdout.write(arcade.render_arcade(data, {NOW}).hex() + '\\n')
'''
        drawn = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=600,
                               check=True).stdout.split()
        self.assertEqual(len(drawn), len(self.ITEMS))
        for (moment, row), ref in zip(self.ITEMS, drawn):
            with mock.patch.object(seasons, 'season_at', lambda at=None: None):
                built = arcade.render_arcade(self.data(moment if moment.get('kind') else None, **row), NOW)
            self.assertEqual(built.hex(), ref, (moment, row))

    ITEMS = (({'kind': 'risky', 'style': 'verdict'}, {}), ({'kind': 'risky', 'style': 'objection'}, {}),
             ({'kind': 'deleted', 'style': 'drift'}, {'active': True}), ({'kind': 'deleted', 'style': 'wave'}, {}),
             ({'kind': 'rude'}, {}), ({'kind': 'calm'}, {}), ({'kind': 'failed'}, {}), ({'kind': 'compact'}, {}),
             ({'kind': None}, {'active': True, 'word': 'PONDERING'}),
             ({'kind': None}, {'active': True, 'word': 'RETICULATING'}),
             ({'kind': None}, {'active': True, 'word': 'ACCOMPLISHING'}))


class ReadoutTests(Base):
    def test_the_thinking_word_takes_the_place_of_what_clawd_does_and_nothing_else(self):
        for row, word in (({'word': 'PONDERING'}, 'PONDERING'), ({'word': 'PONDERING', 'active': True}, 'PONDERING'),
                          ({}, 'RESTING'), ({'active': True}, 'RUNNING')):
            self.assertEqual(self.label(**row), word, row)
        for moment, word in (({'kind': 'needs', 'level': 1}, 'NEEDS YOU'), ({'kind': 'done', 'at': 1}, 'DONE'),
                             ({'kind': 'pet'}, 'PETTED'), ({'kind': 'drink'}, 'DRINKING'), ({'kind': 'failed'}, 'DIZZY'),
                             ({'kind': 'deleted', 'style': 'drift'}, 'BOO!')):
            self.assertEqual(self.label(moment, word='PONDERING'), word, moment)  # a moment says its own word

    def test_slow_stays_readable_under_the_word_the_ghost_the_sulk_and_the_tool_faces(self):
        slow = {'slow': ['WEEK']}
        for moment in (None, {'kind': 'deleted', 'style': 'drift'}, {'kind': 'rude'}, {'kind': 'calm'},
                       {'kind': 'failed'}, {'kind': 'compact'}):
            self.assertEqual(self.label(moment, word='PONDERING', **slow), 'SLOW', moment)
        for moment, word in (({'kind': 'risky', 'style': 'verdict'}, 'ORDER!'), ({'kind': 'needs', 'level': 1}, 'NEEDS YOU'),
                             ({'kind': 'done', 'at': 1}, 'DONE'), ({'kind': 'snack'}, 'SNACKING')):
            self.assertEqual(self.label(moment, **slow), word, moment)  # (actions say theirs, as in phase 2)
        _, shots = self.stages({'kind': 'failed'}, slow=['WEEK'])
        warn = tuple(readout.WARN)
        self.assertTrue(any(warn in colours(s.crop((0, 171, 240, 240))) for s in shots))  # red SLOW, blinking
        self.assertTrue(any(warn not in colours(s.crop((0, 195, 240, 240))) for s in shots))

    def test_another_pets_row_never_says_claudes_word(self):
        data = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', [('WEEK', 30, 3 * D)])])
        row = dict(data['accounts']['codex_a'], key='codex_a', word='PONDERING')
        self.assertNotEqual(arcade.action_label(row, arcade.scene_plan(row, NOW), None, 0, arcade.FRAMES), 'PONDERING')

    def test_twelve_letters_in_the_readouts_own_size_thirteen_and_fourteen_smaller_on_the_same_line(self):
        def drawn(word):
            canvas = Image.new('RGB', (240, 240), readout.PANEL)
            from PIL import ImageDraw
            readout.draw_battery(canvas, ImageDraw.Draw(canvas), 'claude', word, [('5H', 40, NOW + H, False),
                                                                                  ('WEEK', 60, NOW + D, False)], NOW)
            ink = tuple(readout.MUTED)
            line = canvas.crop((80, 170, 240, 195))
            spots = [(x, y) for y in range(line.height) for x in range(line.width) if line.getpixel((x, y)) == ink]
            return min(x for x, _ in spots) + 80, max(x for x, _ in spots) + 80, max(y for _, y in spots) - min(y for _, y in spots) + 1
        for word, tall in (('PONDERING', 14), ('RETICULATING', 14), ('ACCOMPLISHING', 7), ('PHILOSOPHISING', 7),
                           ('WWWWWWWWWWWWWW', 7)):
            left, right, height = drawn(word)
            self.assertEqual(height, tall, word)  # 7 rows of the 5 x 7 font, doubled for the readout's own size
            self.assertGreaterEqual(left, 80)  # after CLAWD
            self.assertLessEqual(right, 230, word)  # whole, on the line, inside the screen's margin
            width = (len(word) * 6 - 1) * (2 if tall == 14 else 1)
            self.assertEqual(right - left + 1, width, word)  # every letter of it, none cut


if __name__ == '__main__':
    unittest.main()
