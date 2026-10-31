#!/usr/bin/env python3
"""Offline unittest entry point with machine-readable PASS/FAIL lines.

Run from any working directory. Requirements are installed by the caller (the
nightly cold verifier creates a fresh venv from requirements.txt).
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ColdResult(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        self.stream.writeln(f"PASS {test.id()}")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.stream.writeln(f"FAIL {test.id()}")

    def addError(self, test, err):
        super().addError(test, err)
        self.stream.writeln(f"FAIL {test.id()}")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.stream.writeln(f"FAIL {subtest.id()}")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.stream.writeln(f"FAIL {test.id()} (unexpected success)")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.stream.writeln(f"SKIP {test.id()}: {reason}")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.stream.writeln(f"SKIP {test.id()}: expected failure")


def run_suite(suite, stream):
    result = unittest.TextTestRunner(stream=stream, verbosity=0, resultclass=ColdResult).run(suite)
    if result.testsRun <= len(result.skipped) + len(result.expectedFailures):
        stream.write("FAIL discovery.no_runnable_tests\n")
        return 1
    return 0 if result.wasSuccessful() else 1


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    return run_suite(suite, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
