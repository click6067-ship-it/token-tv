"""The tests leave nothing behind in the temporary folder."""
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


class HygieneTests(unittest.TestCase):
    def test_every_temporary_folder_is_removed_after_its_test(self):
        # A bare mkdtemp() outlives its test; helpers.temp_dir() registers the removal, pass or fail.
        bare = [f'{path.name}:{n}' for path in sorted(TESTS.glob('*.py')) if path.name not in ('helpers.py', 'test_hygiene.py')
                for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
                if re.search(r'\bmkdtemp\(', line) and 'noqa: mkdtemp' not in line]
        self.assertEqual(bare, [])


if __name__ == '__main__':
    unittest.main()
