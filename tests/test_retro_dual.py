import time
import unittest

from token_tv.sample import D, H, snapshot
from token_tv.themes import ACCENT, render_retro_dual, rgb


def data(*accounts):
    return snapshot(time.time(), list(accounts))


def second_line(image, top):
    # One account renders one full card; its second window line sits from y+81 to y+110.
    return image.crop((0, top + 81, 240, top + 111)).tobytes()


class RetroDualTests(unittest.TestCase):
    def test_every_window_shape_renders_a_clock_frame(self):
        cases = [
            [('claude_a', 'CLAUDE A', 'claude', [('5H', 41, 2 * H), ('WEEK', 86, 3 * D)])],
            [('claude_a', 'CLAUDE A', 'claude', [('5H', 41, 2 * H)])],
            [('codex_a', 'CODEX A', 'codex', [('WINDOW', 30, 6 * D), ('WINDOW', 95, 3 * D)])],
            [('grok_a', 'GROK A', 'grok', [])],
        ]
        for accounts in cases:
            with self.subTest(accounts=accounts):
                self.assertEqual(render_retro_dual(data(*accounts)).size, (240, 240))

    def test_a_second_reported_window_is_drawn_not_dashed(self):
        # Codex labels windows that are neither 5 hours nor a week as WINDOW; both must reach the screen.
        both = render_retro_dual(data(('codex_a', 'CODEX A', 'codex', [('WINDOW', 30, 6 * D), ('WINDOW', 95, 3 * D)])))
        first = render_retro_dual(data(('codex_a', 'CODEX A', 'codex', [('WINDOW', 30, 6 * D)])))
        top = (240 - 116) // 2
        self.assertNotEqual(second_line(both, top), second_line(first, top))

    def test_bars_leave_the_card_frame_intact(self):
        full = [('5H', 100, 2 * H), ('WEEK', 100, 3 * D)]
        layouts = (([('claude_a', 'CLAUDE A', 'claude', full)], 116, 4),
                   ([('claude_a', 'CLAUDE A', 'claude', full), ('codex_a', 'CODEX A', 'codex', full),
                     ('grok_a', 'GROK A', 'grok', full)], 76, 4))
        for accounts, card_h, gap in layouts:
            image = render_retro_dual(data(*accounts))
            top = (240 - len(accounts) * card_h - (len(accounts) - 1) * gap) // 2
            for index, (_, _, provider, _) in enumerate(accounts):
                y = top + index * (card_h + gap)
                accent = rgb(ACCENT['retro'][provider][0])
                for row in (y + card_h - 4, y + card_h - 3):  # the 2 px accent outline at the card's bottom
                    with self.subTest(card_h=card_h, provider=provider, row=row):
                        self.assertEqual({image.getpixel((x, row)) for x in range(14, 226, 7)}, {accent})


if __name__ == '__main__':
    unittest.main()
