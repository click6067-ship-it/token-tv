"""v2 phase 3a, x9: the Claude Code mod's two sounds are short clips of its own, made again byte for byte from the
numbers in scripts/make_sounds.py."""
import sys
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOUNDS = ROOT / 'claude-plugin' / 'sounds'
LONGEST = 2.0  # seconds: a cue, never a tune


class SoundTests(unittest.TestCase):
    def test_two_short_mono_clips_the_mod_names(self):
        mod = (ROOT / 'claude-plugin' / 'hooks' / 'register.ts').read_text(encoding='utf-8')
        for name in ('wait.wav', 'done.wav'):
            self.assertIn(f"'sounds/{name}'", mod)
            with wave.open(str(SOUNDS / name)) as clip:
                seconds = clip.getnframes() / clip.getframerate()
                self.assertEqual((clip.getnchannels(), clip.getsampwidth()), (1, 2))
                self.assertGreater(seconds, .1)
                self.assertLess(seconds, LONGEST)
                samples = clip.readframes(clip.getnframes())
                self.assertGreater(len(set(samples)), 50)  # a sound, not silence

    def test_they_are_made_again_byte_for_byte(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        self.addCleanup(sys.path.remove, str(ROOT / 'scripts'))
        import make_sounds
        folder = temp_dir(self)
        make_sounds.make(folder)
        for name in ('wait.wav', 'done.wav'):
            self.assertEqual((folder / name).read_bytes(), (SOUNDS / name).read_bytes(), name)


if __name__ == '__main__':
    unittest.main()
