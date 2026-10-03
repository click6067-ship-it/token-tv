import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from token_tv import __version__, catalog
from token_tv.display import STYLES

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_theme_votes', ROOT / 'scripts' / 'update_theme_votes.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def entry(id, added, issue=None, min_version='0.1.0', **extra):
    return dict({'id': id, 'name': id.title(), 'author': 'tester', 'added_at': added, 'min_version': min_version,
                 'source_url': 'https://github.com/example/token-tv', 'license': 'MIT', 'like_issue': issue}, **extra)


CATALOG = {'schema_version': 1, 'themes': [
    entry('digital', '2026-10-01T00:00:00Z', issue=11),
    entry('neon', '2026-10-02T00:00:00Z', issue=12),
    entry('retro', '2026-10-03T00:00:00Z', issue=13),
    entry('hud', '2026-10-02T00:00:00Z', issue=14),
    entry('pixel', '2026-09-01T00:00:00Z'),
]}
OLD = '2026-10-01T09:00:00Z'
VOTES = {'schema_version': 1, 'last_attempt_at': '2026-10-03T12:00:00Z', 'counts': {
    '11': {'count': 8, 'status': 'fresh', 'fetched_at': '2026-10-03T12:00:00Z'},
    '12': {'count': 0, 'status': 'fresh', 'fetched_at': '2026-10-03T12:00:00Z'},
    '14': {'count': 8, 'status': 'stale', 'fetched_at': OLD},
}}


def listed(installed=('pixel', 'digital', 'neon', 'retro', 'hud', 'space'), cat=CATALOG, votes=VOTES, version='0.1.0'):
    return catalog.theme_list(installed=installed, catalog=cat, votes=votes, version=version)


class CatalogTest(unittest.TestCase):
    def ids(self, data, mode):
        return [t['id'] for t in catalog.sort_themes(data['themes'], mode)]

    def test_popular_and_new_order(self):
        data = listed()
        # counted (8, 8 stale, 0) first; then never-counted and Local, newest first.
        self.assertEqual(self.ids(data, 'popular'), ['hud', 'digital', 'neon', 'retro', 'pixel', 'space'])
        self.assertEqual(self.ids(data, 'new'), ['retro', 'hud', 'neon', 'digital', 'pixel', 'space'])

    def test_ties_break_by_newest_then_id(self):
        cat = {'schema_version': 1, 'themes': [entry('neon', '2026-10-02T00:00:00Z', 1), entry('hud', '2026-10-02T00:00:00Z', 2)]}
        stamp = '2026-10-03T00:00:00Z'
        votes = {'schema_version': 1, 'last_attempt_at': stamp, 'counts': {
            '1': {'count': 3, 'status': 'fresh', 'fetched_at': stamp}, '2': {'count': 3, 'status': 'fresh', 'fetched_at': stamp}}}
        data = listed(installed=('neon', 'hud'), cat=cat, votes=votes)
        self.assertEqual(self.ids(data, 'popular'), ['hud', 'neon'])
        self.assertEqual(self.ids(data, 'new'), ['hud', 'neon'])

    def test_unknown_likes_are_not_zero(self):
        themes = {t['id']: t for t in listed()['themes']}
        self.assertEqual((themes['retro']['likes'], themes['retro']['likes_state']), (None, 'unavailable'))
        self.assertEqual((themes['pixel']['likes'], themes['pixel']['likes_state']), (None, 'not_open'))
        self.assertIsNone(themes['pixel']['like_url'])
        self.assertEqual((themes['hud']['likes'], themes['hud']['likes_state']), (8, 'stale'))
        self.assertEqual(themes['hud']['likes_counted_at'], OLD)  # an old count keeps its own time

    def test_zero_likes_stay_zero(self):
        neon = next(t for t in listed()['themes'] if t['id'] == 'neon')
        self.assertEqual((neon['likes'], neon['likes_state']), (0, 'counted'))
        self.assertTrue(neon['like_url'].endswith('/issues/12'))

    def test_blank_snapshot_is_still_useful(self):
        data = listed(votes=catalog.BLANK_VOTES)
        self.assertIsNone(data['last_attempt_at'])
        self.assertEqual(len(data['themes']), 6)
        self.assertTrue(all(t['likes'] is None for t in data['themes']))
        self.assertEqual(self.ids(data, 'popular'), self.ids(data, 'new'))

    def test_local_face_without_catalog_entry_is_listed_as_local(self):
        space = next(t for t in listed()['themes'] if t['id'] == 'space')
        self.assertTrue(space['local'] and space['installed'])
        self.assertEqual(space['likes_state'], 'local')
        self.assertFalse(space['needs_update'])

    def test_newer_theme_needs_update_and_is_not_installed(self):
        cat = {'schema_version': 1, 'themes': CATALOG['themes'] + [entry('vapor', '2026-10-04T00:00:00Z', min_version='0.3.0')]}
        vapor = next(t for t in listed(cat=cat)['themes'] if t['id'] == 'vapor')
        self.assertEqual((vapor['installed'], vapor['needs_update']), (False, True))
        self.assertEqual(vapor['min_version'], '0.3.0')

    def test_version_compare(self):
        self.assertTrue(catalog.version_at_least('0.10.0', '0.9.1'))
        self.assertFalse(catalog.version_at_least('0.1.0', '0.2.0'))
        self.assertTrue(catalog.version_at_least('1.0', '1.0.0'))

    def test_bad_catalog_is_rejected(self):
        for broken in ({'schema_version': 2, 'themes': []},
                       {'schema_version': 1, 'themes': [entry('digital', 'x'), entry('digital', 'x')]},
                       {'schema_version': 1, 'themes': [dict(entry('digital', '2026-10-01T00:00:00Z'), like_issue='12')]},
                       {'schema_version': 1, 'themes': [dict(entry('Bad Id', '2026-10-01T00:00:00Z'))]},
                       {'schema_version': 1, 'themes': [dict(entry('digital', '2026-10-01T00:00:00Z'), source_url='javascript:x')]}):
            with self.assertRaises(ValueError):
                catalog.validate_catalog(broken)

    def test_corrupt_vote_file_means_unavailable_not_zero(self):
        path = Path(tempfile.mkdtemp()) / 'votes.json'
        path.write_text('{"counts": ')
        votes = catalog.load_votes(path)
        self.assertEqual(votes['counts'], {})
        self.assertIsNone(votes['last_attempt_at'])

    def test_bad_or_missing_count_times_are_unknown_not_new(self):
        path = Path(tempfile.mkdtemp()) / 'votes.json'
        path.write_text(json.dumps({'last_attempt_at': 'yesterday', 'counts': {
            '11': {'count': 5, 'status': 'fresh', 'fetched_at': 'not a time'},  # unreadable -> unavailable
            '12': {'count': 5, 'status': 'fresh'},                              # fresh without time -> unavailable
            '14': {'count': 7, 'status': 'stale'}}}))                           # old count, time unknown
        votes = catalog.load_votes(path)
        self.assertIsNone(votes['last_attempt_at'])
        themes = {t['id']: t for t in listed(votes=votes)['themes']}
        self.assertEqual([themes[i]['likes_state'] for i in ('digital', 'neon')], ['unavailable', 'unavailable'])
        self.assertIsNone(themes['digital']['likes'])
        self.assertEqual((themes['hud']['likes'], themes['hud']['likes_state'], themes['hud']['likes_counted_at']),
                         (7, 'stale', None))

    def test_installed_face_needing_newer_version_cannot_be_picked_from_catalog(self):
        cat = {'schema_version': 1, 'themes': [entry('neon', '2026-10-02T00:00:00Z', min_version='0.2.0')]}
        neon = next(t for t in listed(installed=('neon', 'mine'), cat=cat)['themes'] if t['id'] == 'neon')
        self.assertEqual((neon['installed'], neon['needs_update']), (True, True))
        mine = next(t for t in listed(installed=('neon', 'mine'), cat=cat)['themes'] if t['id'] == 'mine')
        self.assertEqual((mine['local'], mine['needs_update']), (True, False))

    def test_bundled_catalog_matches_installed_faces(self):
        data = catalog.validate_catalog(json.loads(catalog.CATALOG_PATH.read_text()))
        self.assertLessEqual({t['id'] for t in data['themes']}, set(STYLES))  # a fork may add Local faces
        # one public theme issue per built-in face (issues #1-#6 in the public repository)
        self.assertEqual({t['id']: t['like_issue'] for t in data['themes']},
                         {'pixel': 1, 'digital': 2, 'neon': 3, 'retro': 4, 'hud': 5, 'space': 6})
        votes = catalog.load_votes()
        self.assertTrue(set(votes['counts']) <= {str(t['like_issue']) for t in data['themes']})
        self.assertTrue(all(v['fetched_at'] for v in votes['counts'].values()))  # every count is dated

    def test_broken_bundled_catalog_still_lists_installed_faces(self):
        from unittest import mock
        with mock.patch.object(catalog, 'CATALOG_PATH', Path(tempfile.mkdtemp()) / 'missing.json'):
            data = catalog.payload()
        self.assertTrue(data['catalog_error'])
        self.assertEqual({t['id'] for t in data['themes'] if t['local']}, set(STYLES))

    def test_package_version_matches_pyproject(self):
        self.assertIn(f'version = "{__version__}"', (ROOT / 'pyproject.toml').read_text())


class RefreshTest(unittest.TestCase):
    def test_refresh_keeps_last_count_on_failure(self):
        def fetch(issue):
            if issue == 11:
                return 9
            raise OSError('timeout')
        now = '2026-10-04T00:00:00Z'
        out = updater.refresh(CATALOG, VOTES, fetch, now=now)
        self.assertEqual(out['counts']['11'], {'count': 9, 'status': 'fresh', 'fetched_at': now})
        # kept, marked stale, and still dated when it was really counted
        self.assertEqual(out['counts']['12'], {'count': 0, 'status': 'stale', 'fetched_at': '2026-10-03T12:00:00Z'})
        self.assertEqual(out['counts']['14']['fetched_at'], OLD)
        self.assertNotIn('13', out['counts'])  # never counted stays unknown, not 0
        self.assertEqual(out['last_attempt_at'], now)
        themes = {t['id']: t for t in listed(votes=out)['themes']}
        self.assertEqual((themes['neon']['likes_state'], themes['neon']['likes_counted_at']), ('stale', '2026-10-03T12:00:00Z'))

    def test_refresh_without_issue_skips_network(self):
        calls = []
        cat = {'schema_version': 1, 'themes': [entry('pixel', '2026-09-01T00:00:00Z')]}
        out = updater.refresh(cat, catalog.BLANK_VOTES, lambda n: calls.append(n), now='2026-10-04T00:00:00Z')
        self.assertEqual((calls, out['counts']), ([], {}))

    def test_refresh_counts_issue_body_thumbs_only(self):
        payload = {'reactions': {'+1': 4, 'heart': 9, 'total_count': 13}, 'comments': 7}
        self.assertEqual(updater.thumbs_up(payload), 4)
        for bad in ({}, {'reactions': {'+1': -1}}, {'reactions': {'+1': '4'}}, [], {'reactions': None}):
            with self.assertRaises(ValueError):
                updater.thumbs_up(bad)

    def test_all_failures_keep_every_count_time(self):
        def fail(issue):
            raise ValueError('bad json')
        out = updater.refresh(CATALOG, VOTES, fail, now='2026-10-04T00:00:00Z')
        self.assertTrue(all(v['status'] == 'stale' for v in out['counts'].values()))
        self.assertEqual({k: v['fetched_at'] for k, v in out['counts'].items()},
                         {k: v['fetched_at'] for k, v in VOTES['counts'].items()})


if __name__ == '__main__':
    unittest.main()
