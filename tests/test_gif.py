import io
import time
import unittest

from PIL import Image, ImageDraw

from token_tv import arcade, gif
from token_tv.sample import H, snapshot


def timeline(data, step):
    """Each frame as shown, one entry per `step` ms."""
    image, out = Image.open(io.BytesIO(data)), []
    for n in range(image.n_frames):
        image.seek(n)
        out += [image.convert('RGB').tobytes()] * round(image.info['duration'] / step)
    return out


class GifTests(unittest.TestCase):
    def test_the_clock_gets_the_same_pixels_in_fewer_bytes(self):
        now = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))
        frames = arcade.arcade_frames(snapshot(now, [('a', 'A', 'codex', [('WEEK', 47, 3 * 86400)])]), now)
        indexed = gif.indexed(frames, 'Arcade')
        data = gif.encode(indexed, [70] * len(indexed))
        self.assertEqual(timeline(data, 70), [f.convert('RGB').tobytes() for f in indexed])
        pillow = io.BytesIO()  # Pillow's own best: its palette and transparency optimizing, interlaced
        indexed[0].save(pillow, format='GIF', save_all=True, append_images=indexed[1:], duration=70, loop=0,
                        disposal=1, optimize=True)
        self.assertLess(len(data), .9 * len(pillow.getvalue()))
        palette_bits = (data[10] & 7) + 1
        self.assertLess(palette_bits, 8)
        first = 13 + 3 * (1 << palette_bits) + 19 + 8  # header, table, loop extension, frame timing
        self.assertEqual(data[first], 0x2C)
        self.assertEqual(data[first + 10], palette_bits)  # LZW codes start as wide as the palette, not at 8

    def test_a_still_stretch_is_one_longer_frame_and_a_change_only_its_box(self):
        frames = [Image.new('RGB', (40, 40), (10, 20, 30)) for _ in range(4)]
        ImageDraw.Draw(frames[3]).rectangle((5, 6, 8, 9), fill=(200, 100, 0))
        data = gif.encode(gif.indexed(frames, 'Test'), [70] * 4)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.n_frames, 2)
        self.assertEqual(image.info['duration'], 210)
        self.assertEqual(image.info['loop'], 0)
        image.seek(1)
        self.assertEqual(image.dispose_extent, (5, 6, 9, 10))
        self.assertEqual(timeline(data, 70), [f.tobytes() for f in frames])

    def test_a_frame_where_every_pixel_changes_has_no_transparent_pixels_and_still_plays_right(self):
        import random
        rnd = random.Random(4)
        first, second = Image.new('RGB', (64, 64)), Image.new('RGB', (64, 64))
        first.putdata([(rnd.randrange(16) * 8, 0, 0) for _ in range(64 * 64)])
        second.putdata([(200 + rnd.randrange(2) * 40, 9, 9) for _ in range(64 * 64)])  # two colours, a short palette
        indexed = gif.indexed([first, second], 'Test')
        self.assertEqual(timeline(gif.encode(indexed, [70, 70]), 70), [f.convert('RGB').tobytes() for f in indexed])

    def test_a_full_palette_has_no_index_left_for_unchanged_and_still_plays_right(self):
        frames = []
        for shift in range(3):
            frame = Image.new('RGB', (16, 16))
            frame.putdata([((i + shift) % 256, 0, 0) for i in range(256)])
            frames.append(frame)
        indexed = gif.indexed(frames, 'Test')
        self.assertEqual(len(indexed[0].getpalette()) // 3, 256)
        self.assertEqual(timeline(gif.encode(indexed, [70] * 3), 70), [f.convert('RGB').tobytes() for f in indexed])


if __name__ == '__main__':
    unittest.main()
