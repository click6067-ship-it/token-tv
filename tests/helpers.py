"""Test helpers: temporary folders that go away with their test."""
import os
import tempfile
from pathlib import Path
from unittest import mock


def temp_dir(test):
    """A new folder for `test`, removed when it ends, pass or fail."""
    folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows: a lock still open is no failure
    test.addCleanup(folder.cleanup)
    return Path(folder.name)


def own_tmp(test):
    """The system's temporary folder, for this test and the programs it starts, is a new one removed after it: for
    code that keeps files there by design (the clock locks)."""
    folder = temp_dir(test)
    test.addCleanup(setattr, tempfile, 'tempdir', tempfile.tempdir)
    tempfile.tempdir = str(folder)
    env = mock.patch.dict(os.environ, {'TMPDIR': str(folder), 'TEMP': str(folder), 'TMP': str(folder)})
    env.start()
    test.addCleanup(env.stop)
    return folder


def stepped_over(path, step):
    """Lines of a scene file whose effect the clock never shows when it sees only every `step`-th scene frame: a
    parity test of f (it freezes) or a window of a frame or two (a blink or a glint it steps over). Only the forms
    written in f itself: a timeline derived from f (a beat, a job's own counter) needs its own test."""
    import re
    whole = re.compile(r'\bf\s*%\s*(\d+)\s*(?:in\s*\(([^)]*)\)|==\s*(\d+))')
    turn = re.compile(r'\(?\bf\s*//\s*(\d+)\)?\s*%\s*(\d+)')
    found = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        code = line.split('#')[0]
        for m in whole.finditer(code):
            period, hits = int(m.group(1)), {int(v) for v in re.findall(r'\d+', m.group(2) or m.group(3))}
            if not any(step * k % period in hits for k in range(period)):
                found.append((number, line.strip()))
        for m in turn.finditer(code):
            every, kinds = int(m.group(1)), int(m.group(2))
            if len({step * k // every % kinds for k in range(4 * every * kinds)}) < 2:
                found.append((number, line.strip()))
        for m in re.finditer(r'\bf\s*%\s*(\d+)', code):
            if int(m.group(1)) > 1 and step % int(m.group(1)) == 0:  # f % 2 or f % 4: the same every picture
                found.append((number, line.strip()))
    return found
