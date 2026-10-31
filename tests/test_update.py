"""Keeping TokenTV current: one look at PyPI a day for a quiet note, and `token-tv update` for the background copy."""
import contextlib
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir

from token_tv import __version__, autostart, cli, live, update
from token_tv.state import UsageStore

DAY = 86400
T = 1793000000


def done(stdout='', code=0):
    return mock.Mock(returncode=code, stdout=stdout, stderr='')


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.state = temp_dir(self)
        self.asked = []

    def pypi(self, answer):
        def fetch(timeout=10):
            self.asked.append(update.PYPI)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return fetch

    def test_pypi_is_asked_once_a_day_and_the_answer_kept_in_the_state_folder(self):
        fetch = self.pypi('99.0.0')
        self.assertEqual(update.check(self.state, '0.3.3', T, fetch), '99.0.0')
        self.assertEqual(update.check(self.state, '0.3.3', T + 3600, fetch), '99.0.0')  # the same day: the kept answer
        notice = update.UpdateNotice(self.state, enabled=True, fetch=fetch)  # a restart, the same day
        notice.refresh(T + 7200)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(notice.payload()['latest'], '99.0.0')
        update.check(self.state, '0.3.3', T + DAY, fetch)
        self.assertEqual(len(self.asked), 2)  # the next day, once more
        self.assertTrue(json.loads((self.state / 'update-check.json').read_text(encoding='utf-8'))['checked_at'])

    def test_only_a_newer_version_makes_a_note(self):
        for latest, shown in (('99.0.0', '99.0.0'), (__version__, None), ('0.0.1', None), ('1.0.0rc1', None), (None, None)):
            with self.subTest(latest=latest):
                state = temp_dir(self)
                notice = update.UpdateNotice(state, enabled=True, fetch=self.pypi(latest))
                notice.refresh(T)
                self.assertEqual((notice.payload() or {}).get('latest'), shown)

    def test_no_network_is_no_note_and_no_asking_again_every_minute(self):
        notice = update.UpdateNotice(self.state, enabled=True, fetch=self.pypi(OSError('offline')))
        for minute in range(5):
            notice.refresh(T + 60 * minute)
        self.assertIsNone(notice.payload())
        self.assertEqual(len(self.asked), 1)

    def test_turned_off_it_never_asks(self):
        notice = update.UpdateNotice(self.state, enabled=False, fetch=self.pypi('99.0.0'))
        notice.refresh(T)
        self.assertEqual((self.asked, notice.payload()), ([], None))

    def test_pypi_is_the_only_place_asked_and_nothing_is_sent(self):
        self.assertEqual(update.PYPI, 'https://pypi.org/pypi/token-tv/json')
        answer = io.BytesIO(json.dumps({'info': {'version': '99.0.0'}}).encode())
        with mock.patch('token_tv.update.urlopen', return_value=contextlib.nullcontext(answer)) as opened:
            self.assertEqual(update.newest(), '99.0.0')
        request = opened.call_args.args[0]
        self.assertEqual((request.full_url, request.get_method(), request.data), (update.PYPI, 'GET', None))

    def test_the_config_can_turn_it_off(self):
        from token_tv.sources import load_config
        path = self.state / 'config.json'
        account = {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'a@example.com'}
        path.write_text(json.dumps({'accounts': [account], 'update_check': False}), encoding='utf-8')
        self.assertIs(load_config(path)['update_check'], False)
        path.write_text(json.dumps({'accounts': [account], 'update_check': 'no'}), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_config(path)

    def test_the_dashboard_gets_the_note_with_the_command(self):
        notice = update.UpdateNotice(self.state, enabled=True, fetch=self.pypi('99.0.0'))
        notice.refresh(T)
        store = UsageStore([])
        from test_security import ask
        with mock.patch('token_tv.autostart.how', return_value='npx token-tv'):
            status, body = ask(live.handler(store, notice=notice), '/snapshot')
        note = json.loads(body)['update']
        self.assertEqual((note['current'], note['latest']), (__version__, '99.0.0'))
        self.assertIn('npx token-tv update', note['command'])
        status, body = ask(live.handler(store), '/snapshot')
        self.assertIsNone(json.loads(body).get('update'))
        web = Path(live.__file__).parent / 'web'
        self.assertIn('id="update-note"', (web / 'index.html').read_text(encoding='utf-8'))
        self.assertIn("$('#update-note').textContent", (web / 'app.js').read_text(encoding='utf-8'))

    def test_the_readmes_say_how_to_update(self):
        root = Path(live.__file__).resolve().parents[1]
        for name in ('README.md', 'README.ko.md'):
            self.assertIn('token-tv update', (root / name).read_text(encoding='utf-8'), name)


class CacheFolderTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX modes')
    def test_a_state_folder_made_for_the_cache_is_private_even_under_umask_0(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / 'new' / 'state'
            old = os.umask(0)
            try:
                update.check(state, current='0.3.3', now=1000.0, fetch=lambda: '0.3.4')
            finally:
                os.umask(old)
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((state / update.CACHE).stat().st_mode), 0o600)


class UpdateCommandTests(unittest.TestCase):
    """`token-tv update`: stop the background copy, register the newest release, start it; config and logins kept."""
    def setUp(self):
        self.folder = temp_dir(self)
        self.config = self.folder / 'Kim Minji' / 'config.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex',
                                                         'email': 'a@example.com'}]}), encoding='utf-8')
        login = self.folder / 'codex-home' / 'auth.json'
        login.parent.mkdir()
        login.write_text('{"synthetic": true}', encoding='utf-8')
        self.kept = [self.config, login]
        self.before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.kept]
        self.unit = self.folder / 'token-tv.service'
        self.steps = []

    def background(self, argv, path=None):
        self.unit.write_text(autostart.entry(argv + ['start', '--yes', '--no-browser', '--config', str(self.config)],
                                             'systemd', path=path), encoding='utf-8')

    def update(self, prefix, which, installed=True, newest='99.0.0', running=False, env=None, serving=None):
        def run(argv, timeout=60):
            self.steps.append(argv)
            if argv[:2] == ['systemctl', '--user'] or argv[0] == 'loginctl':
                return done()
            if '--version' in argv:
                return done(f'token-tv {newest}\n' if installed else '', 0 if installed else 1)
            return done('', 0 if installed else 1)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(autostart, 'place', return_value=(self.unit, 'systemd')), \
                mock.patch.object(autostart, 'run', side_effect=run), \
                mock.patch('sys.prefix', prefix), mock.patch('sys.executable', prefix + '/bin/python'), \
                mock.patch('shutil.which', side_effect=lambda name: which.get(name)), \
                mock.patch.dict('os.environ', env or {}, clear=False), \
                mock.patch.object(update, 'newest', return_value=newest), \
                mock.patch.object(cli, 'dashboard_port', return_value=(8787, running)), \
                mock.patch.object(cli, 'running_version', return_value=serving), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(['update', '--config', str(self.config)])
        return code, out.getvalue() + err.getvalue()

    def assert_kept(self):
        self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in self.kept], self.before)

    def order(self, fetch):
        """Where the stop, the fetch and the start come in the calls made."""
        flat = [' '.join(step) for step in self.steps]
        stop = flat.index('systemctl --user disable --now token-tv.service')
        got = next(i for i, step in enumerate(flat) if fetch in step)
        start = flat.index('systemctl --user enable --now token-tv.service')
        return stop < got < start

    def test_uvx_and_npx_with_uv_run_the_newest_release(self):
        for env, how in (({}, 'uvx'), ({'TOKEN_TV_LAUNCHER': 'npx', 'TOKEN_TV_UVX': '/c/token-tv/uv/uvx'}, 'npx')):
            with self.subTest(how=how):
                self.steps = []
                uvx = env.get('TOKEN_TV_UVX', '/usr/bin/uvx')
                self.background([uvx, f'token-tv@{__version__}'])
                code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, env=env)
                self.assertEqual(code, 0, said)
                self.assertTrue(self.order('token-tv@99.0.0 --version'))
                unit = self.unit.read_text(encoding='utf-8')
                self.assertIn(f'ExecStart={uvx} token-tv@99.0.0 start', unit)
                self.assertNotIn(f'token-tv@{__version__}', unit)
                self.assertIn(str(self.config), unit.replace('\\\\', '\\'))
                self.assertIn('99.0.0', said)
                self.assert_kept()

    def test_pipx_run_gets_the_newest_release(self):
        self.background(['/usr/bin/pipx', 'run', '--spec', f'token-tv=={__version__}', 'token-tv'])
        code, said = self.update('/home/me/.local/share/pipx/.cache/0a1b', {'pipx': '/usr/bin/pipx'})
        self.assertEqual(code, 0, said)
        self.assertTrue(self.order('pipx run --spec token-tv==99.0.0 token-tv --version'))
        self.assertIn('--spec token-tv==99.0.0 token-tv start', self.unit.read_text(encoding='utf-8'))
        self.assert_kept()

    def test_pip_and_the_npx_venv_upgrade_in_place(self):
        for prefix in ('/home/me/venvs/tt', '/home/me/.cache/token-tv/venv'):
            with self.subTest(prefix=prefix):
                self.steps = []
                self.background([prefix + '/bin/python', '-m', 'token_tv'])
                code, said = self.update(prefix, {'token-tv': prefix + '/bin/token-tv'})
                self.assertEqual(code, 0, said)
                self.assertTrue(self.order('-m pip install --upgrade'))
                self.assertIn('token-tv==99.0.0', ' '.join(' '.join(s) for s in self.steps))
                self.assertIn(f'ExecStart={prefix}/bin/python -m token_tv start', self.unit.read_text(encoding='utf-8'))
                self.assert_kept()

    def test_a_failed_install_starts_the_old_copy_again_and_says_so(self):
        self.background(['/usr/bin/uvx', f'token-tv@{__version__}'])
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, installed=False)
        self.assertEqual(code, 1)
        unit = self.unit.read_text(encoding='utf-8')
        self.assertIn(f'token-tv@{__version__} start', unit)  # the copy that worked, running again
        self.assertNotIn('99.0.0', unit)
        self.assertIn('Could not', said)
        self.assertNotIn('now runs', said)
        self.assert_kept()

    def test_in_a_terminal_it_says_what_to_run(self):
        for prefix, which, env, expected in (
                ('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, {}, 'uvx token-tv@latest start'),
                ('/home/me/.cache/token-tv/venv', {}, {'TOKEN_TV_LAUNCHER': 'npx'}, 'npx token-tv@latest start'),
                ('/home/me/.local/share/pipx/.cache/0a1b', {'pipx': '/usr/bin/pipx'}, {}, 'pipx run --spec token-tv==99.0.0 token-tv start'),
                ('/home/me/venvs/tt', {'token-tv': '/home/me/venvs/tt/bin/token-tv'}, {}, '-m pip install --upgrade token-tv')):
            with self.subTest(prefix=prefix):
                self.steps = []
                code, said = self.update(prefix, which, running=True, env=env)
                self.assertEqual(code, 0, said)
                self.assertIn(expected, said)
                self.assertIn('Ctrl+C', said)
                self.assertFalse([s for s in self.steps if s[0] == 'systemctl'])  # nothing registered
                self.assertFalse(self.unit.exists())

    def test_an_older_background_copy_is_updated_even_when_this_one_is_the_newest(self):
        # `npx token-tv@latest update` runs the newest release; the background copy still runs an older one.
        self.background(['/usr/bin/uvx', 'token-tv@0.0.1'])
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, newest=__version__)
        self.assertEqual(code, 0, said)
        self.assertIn(f'token-tv@{__version__} start', self.unit.read_text(encoding='utf-8'))
        self.assertIn('was 0.0.1', said)
        for serving, changed in ((__version__, False), ('0.0.1', True)):  # pip: the running copy's /health says
            with self.subTest(serving=serving):
                self.steps = []
                self.background(['/home/me/venvs/tt/bin/python', '-m', 'token_tv'])
                code, said = self.update('/home/me/venvs/tt', {'token-tv': '/home/me/venvs/tt/bin/token-tv'},
                                         newest=__version__, serving=serving, running=True)
                self.assertEqual(code, 0, said)
                self.assertEqual(bool(self.steps), changed, said)

    def test_a_failed_update_puts_back_exactly_what_ran(self):
        # Set up from a terminal that saw the provider CLIs; updated from one that does not.
        self.background(['/usr/bin/uvx', 'token-tv@0.0.1'], path='/home/me/.nvm/versions/node/v24/bin:/usr/bin')
        before = self.unit.read_text(encoding='utf-8')
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, installed=False)
        self.assertEqual(code, 1)
        self.assertEqual(self.unit.read_text(encoding='utf-8'), before)
        self.assertIn('0.0.1 again', said)

    def test_an_update_keeps_the_paths_the_background_copy_was_set_up_with(self):
        self.background(['/usr/bin/uvx', f'token-tv@{__version__}'], path='/home/me/.nvm/versions/node/v24/bin:/usr/bin')
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'})
        self.assertEqual(code, 0, said)
        unit = self.unit.read_text(encoding='utf-8')
        self.assertIn('Environment="PATH=/home/me/.nvm/versions/node/v24/bin:/usr/bin"', unit)
        self.assertIn('token-tv@99.0.0 start', unit)

    def test_on_windows_the_old_loop_ends_before_the_new_entry_is_written(self):
        vbs = self.folder / 'TokenTV.vbs'
        (self.config.parent / 'state').mkdir()
        (self.config.parent / 'state' / 'live.pid').write_text('4242', encoding='utf-8')
        vbs.write_text(autostart.entry(['C:\\uv\\uvx.exe', f'token-tv@{__version__}', 'start', '--config', str(self.config)],
                                       'startup', path='C:\\Tools'), encoding='utf-16')
        clock, events = [0.0], []
        def sleep(seconds):
            events.append(('sleep', seconds, clock[0]))
            clock[0] += seconds
        def run(argv, timeout=60):
            events.append(('run', argv[0], clock[0]))
            clock[0] += 3  # a cached release answers in seconds
            if argv[0] == 'powershell':
                return done(f'"C:\\uv\\uvx.exe" token-tv@{__version__} start --config "{self.config}"')
            return done('token-tv 99.0.0\n')
        with mock.patch.object(autostart, 'place', return_value=(vbs, 'startup')), \
                mock.patch.object(autostart, 'run', side_effect=run), mock.patch('os.kill'), \
                mock.patch('subprocess.Popen', side_effect=lambda *a, **k: events.append(('start', a[0][0], clock[0]))), \
                mock.patch('time.sleep', side_effect=sleep), mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                mock.patch('sys.prefix', 'C:/Users/me/AppData/Local/uv/cache/archive-v0/abc'), \
                mock.patch('shutil.which', return_value='C:\\uv\\uvx.exe'), mock.patch.object(update, 'newest', return_value='99.0.0'), \
                mock.patch.object(cli, 'dashboard_port', return_value=(8787, False)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['update', '--config', str(self.config)]), 0)
        stopped = next(at for kind, *rest, at in events if kind == 'run' and rest[0] == 'powershell')
        started = next(at for kind, *rest, at in events if kind == 'start')
        self.assertGreaterEqual(started - stopped, 31)  # the old loop sleeps 30 s, finds its file gone and ends
        self.assertIn('token-tv@99.0.0', autostart.read(vbs))

    def test_the_command_to_type_keeps_the_config(self):
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, running=True)
        self.assertEqual(code, 0, said)
        self.assertIn(f"uvx token-tv@latest start --config '{self.config}'", said)

    def test_the_newest_already_and_pypi_out_of_reach(self):
        self.background(['/usr/bin/uvx', f'token-tv@{__version__}'])
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, newest=__version__)
        self.assertEqual(code, 0)
        self.assertIn('newest', said)
        self.assertEqual(self.steps, [])
        code, said = self.update('/home/me/.cache/uv/archive-v0/abc', {'uvx': '/usr/bin/uvx'}, newest=None)
        self.assertEqual(code, 1)
        self.assertIn('nothing was changed', said)
        self.assertEqual(self.steps, [])


if __name__ == '__main__':
    unittest.main()
