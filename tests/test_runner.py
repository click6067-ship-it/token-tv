"""Exercise the cold runner in disposable repos, never recursively run this suite."""
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RUNNER = Path(__file__).with_name('run_all.py')


class RunnerTests(unittest.TestCase):
    def run_fixture(self, source=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo with spaces'
            tests = root / 'tests'
            tests.mkdir(parents=True)
            shutil.copyfile(RUNNER, tests / 'run_all.py')
            (root / 'project_module.py').write_text('VALUE = 42\n', encoding='utf-8')
            if source is not None:
                (tests / 'test_example.py').write_text(textwrap.dedent(source), encoding='utf-8')
            # The caller's cwd is deliberately outside the repo, as in a cold invocation.
            result = subprocess.run([sys.executable, str(tests / 'run_all.py')], cwd=folder,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=30)
            self.assertEqual(list(root.rglob('*.pyc')), [])
            return result

    def test_discovery_from_another_cwd_and_skips_do_not_inflate_passes(self):
        result = self.run_fixture('''
            import unittest
            import project_module
            from pathlib import Path
            class Checks(unittest.TestCase):
                def test_pass(self):
                    self.assertEqual(project_module.VALUE, 42)
                    self.assertTrue(Path('tests').is_dir())
                @unittest.skip('deliberately unavailable')
                def test_skip(self):
                    self.fail()
                @unittest.expectedFailure
                def test_expected(self):
                    self.fail()
        ''')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PASS test_example.Checks.test_pass\n', result.stdout)
        self.assertIn('1 passed, 0 failed\n', result.stdout)
        self.assertEqual(sum(line.startswith('PASS ') for line in result.stdout.splitlines()), 1)

    def test_failures_errors_and_unexpected_successes_are_named(self):
        result = self.run_fixture('''
            import unittest
            class Checks(unittest.TestCase):
                def test_failure(self):
                    self.fail('regression')
                def test_error(self):
                    raise RuntimeError('broken')
                @unittest.expectedFailure
                def test_unexpected(self):
                    pass
        ''')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for name in ('failure', 'error', 'unexpected'):
            self.assertIn(f'FAIL test_example.Checks.test_{name}\n', result.stdout)
        self.assertIn('0 passed, 3 failed\n', result.stdout)

    def test_body_and_teardown_failure_count_as_one_failed_check(self):
        result = self.run_fixture('''
            import unittest
            class Checks(unittest.TestCase):
                def tearDown(self):
                    raise RuntimeError('cleanup failed')
                def test_failure(self):
                    self.fail('body failed')
        ''')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.count('FAIL test_example.Checks.test_failure\n'), 1)
        self.assertIn('0 passed, 1 failed\n', result.stdout)
        self.assertIn('body failed', result.stdout)
        self.assertIn('cleanup failed', result.stdout)

    def test_failing_subtests_are_named_not_counted_as_success(self):
        result = self.run_fixture('''
            import unittest
            class Checks(unittest.TestCase):
                def test_subtests(self):
                    for number in (1, 2):
                        with self.subTest(number=number):
                            self.fail('subtest failure')
        ''')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for number in (1, 2):
            self.assertIn(f'FAIL test_example.Checks.test_subtests (number={number})\n', result.stdout)
        self.assertIn('0 passed, 2 failed\n', result.stdout)

    def test_import_error_is_named(self):
        result = self.run_fixture('raise ImportError("dependency absent")\n')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('FAIL unittest.loader._FailedTest.test_example\n', result.stdout)
        self.assertIn('0 passed, 1 failed\n', result.stdout)

    def test_class_setup_error_with_zero_tests_is_named(self):
        result = self.run_fixture('''
            import unittest
            class Checks(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise RuntimeError('fixture failed')
                def test_unreached(self):
                    pass
        ''')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('FAIL setUpClass (test_example.Checks)\n', result.stdout)
        self.assertIn('0 passed, 1 failed\n', result.stdout)

    def test_empty_or_entirely_skipped_suite_cannot_succeed(self):
        skipped = '''
            import unittest
            class Checks(unittest.TestCase):
                @unittest.skip('no environment')
                def test_skip(self):
                    pass
        '''
        expected = '''
            import unittest
            class Checks(unittest.TestCase):
                @unittest.expectedFailure
                def test_expected(self):
                    self.fail()
        '''
        for source in (None, skipped, expected):
            with self.subTest(source=source):
                result = self.run_fixture(source)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('0 passed, 0 failed\n', result.stdout)
                self.assertIn('  FAILED NO_TESTS:', result.stdout)
                self.assertFalse(any(line.startswith('FAIL ') for line in result.stdout.splitlines()))
                self.assertFalse(any(line.startswith('PASS ') for line in result.stdout.splitlines()))


if __name__ == '__main__':
    unittest.main()
