"""Run the offline unittest suite with the nightly cold verifier's result markers.

The cold verifier installs requirements.txt in a fresh venv before invoking this
file. No accounts, clock hardware, browser, or live provider checks are needed.
"""
import os
from pathlib import Path
import sys
import unittest


class ColdResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed += 1
        self.stream.writeln(f"PASS {test.id()}")


def main():
    root = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    os.chdir(root)
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    result = unittest.TextTestRunner(
        stream=sys.stdout, verbosity=0, resultclass=ColdResult, buffer=True,
    ).run(suite)
    for test, _ in result.failures + result.errors:
        print(f"FAIL {test.id()}")
    for test in result.unexpectedSuccesses:
        print(f"FAIL {test.id()} (unexpected success)")
    if not result.wasSuccessful():
        return 1
    if not result.passed:
        print("== NO_TESTS: no passing tests ==")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
