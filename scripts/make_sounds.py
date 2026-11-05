"""The Claude Code mod's two short sounds (x9), made from numbers so they can be made again byte for byte:
`wait.wav`, two soft rising bell notes for a permission prompt that waits for you, and `done.wav`, three rising notes
for a turn done. Mono, 16 bit, 22,050 Hz, under half a second each.

    python3 scripts/make_sounds.py [folder]     # default: claude-plugin/sounds
"""
import math
import struct
import sys
import wave
from pathlib import Path

RATE = 22050
PEAK = .3  # of full scale: a cue, not an alarm
# (start s, length s, Hz): each note a bell, its overtone an octave up, struck and dying away
SOUNDS = {
    'wait.wav': ((0.0, .16, 880.0), (.17, .2, 1174.66)),
    'done.wav': ((0.0, .1, 659.26), (.1, .1, 783.99), (.2, .24, 1046.5)),
}


def note(t, length, hz):
    """One bell note at `t` seconds into it: a 4 ms rise, then dying away over its length, silent at its end."""
    if not 0 <= t < length:
        return 0.0
    rise = min(1.0, t / .004)
    fall = math.exp(-5 * t / length) * (1 - t / length)
    return rise * fall * (math.sin(2 * math.pi * hz * t) + .3 * math.sin(4 * math.pi * hz * t)) / 1.3


def samples(notes):
    end = max(start + length for start, length, _ in notes)
    out = []
    for n in range(round(end * RATE) + 1):
        t = n / RATE
        value = sum(note(t - start, length, hz) for start, length, hz in notes)
        out.append(max(-32767, min(32767, round(value * PEAK * 32767))))
    return out


def make(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, notes in SOUNDS.items():
        with wave.open(str(folder / name), 'wb') as clip:
            clip.setnchannels(1)
            clip.setsampwidth(2)
            clip.setframerate(RATE)
            data = samples(notes)
            clip.writeframes(struct.pack(f'<{len(data)}h', *data))


if __name__ == '__main__':
    make(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'claude-plugin' / 'sounds')
