"""The cold runner must expose failures and empty/skip-only runs to its caller."""
import importlib.util
import io
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('cold_runner', Path(__file__).with_name('run_all.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def run_one(self, body, decorate=lambda f: f):
        case = type('Fixture', (unittest.TestCase,), {'test_case': decorate(body)})
        out = io.StringIO()
        code = runner.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(case), out)
        return code, out.getvalue()

    def test_success_has_a_countable_line(self):
        code, text = self.run_one(lambda t: t.assertTrue(True))
        self.assertEqual(code, 0)
        self.assertRegex(text, r'(?m)^PASS .*Fixture.test_case$')

    def test_assertion_and_import_error_are_named_failures(self):
        def broken_import(t):
            raise ModuleNotFoundError('fixture_dependency')
        for body in (lambda t: t.fail('fixture'), broken_import):
            code, text = self.run_one(body)
            self.assertEqual(code, 1)
            self.assertRegex(text, r'(?m)^FAIL .*Fixture.test_case$')
            self.assertNotRegex(text, r'(?m)^PASS ')

    def test_failed_subtest_is_not_success(self):
        def subtest(t):
            with t.subTest(example=1):
                t.fail('fixture')
        code, text = self.run_one(subtest)
        self.assertEqual(code, 1)
        self.assertRegex(text, r'(?m)^FAIL .*example=1')
        self.assertNotRegex(text, r'(?m)^PASS ')

    def test_skip_only_and_empty_are_not_green(self):
        code, text = self.run_one(lambda t: None, unittest.skip('fixture'))
        self.assertEqual(code, 1)
        self.assertIn('FAIL discovery.no_runnable_tests', text)
        out = io.StringIO()
        self.assertEqual(runner.run_suite(unittest.TestSuite(), out), 1)
        self.assertIn('FAIL discovery.no_runnable_tests', out.getvalue())

    def test_unexpected_success_fails(self):
        code, text = self.run_one(lambda t: None, unittest.expectedFailure)
        self.assertEqual(code, 1)
        self.assertIn('unexpected success', text)


if __name__ == '__main__':
    unittest.main()
