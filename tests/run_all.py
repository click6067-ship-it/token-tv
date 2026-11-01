#!/usr/bin/env python3
"""Run unittest discovery with the PASS/FAIL records used by night-cold-verify."""
import os
import sys
import unittest
from pathlib import Path


class NightResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def main():
    # Match `python -B -m unittest discover -s tests -v`, even from another cwd.
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    result = unittest.TextTestRunner(verbosity=2, resultclass=NightResult).run(suite)

    # Errors include discovery/class-fixture errors and failing subtests. Unexpected
    # successes must also fail; skips and expected failures are not passing checks.
    failed = [test.id() for test, _ in result.failures + result.errors]
    failed.extend(test.id() for test in result.unexpectedSuccesses)
    failed = list(dict.fromkeys(failed))  # One failed check, even if tearDown also fails.
    for name in result.passed:
        print(f'PASS {name}')
    for name in failed:
        print(f'FAIL {name}')
    print(f'{len(result.passed)} passed, {len(failed)} failed')
    if not result.passed and not failed:
        print('  FAILED NO_TESTS: no passing checks (empty, skipped or expected failures only)')
    return 0 if result.wasSuccessful() and result.passed else 1


if __name__ == '__main__':
    sys.exit(main())
