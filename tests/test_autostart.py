import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from token_tv import __version__, autostart


class AutostartTests(unittest.TestCase):
    """TokenTV keeps running after the terminal closes, and comes back with the computer."""
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def placed(self, kind):
        names = {'systemd': 'token-tv.service', 'launchd': 'tokentv.plist', 'startup': 'TokenTV.vbs'}
        return mock.patch.object(autostart, 'place', return_value=(self.folder / names[kind], kind))

    def test_each_system_gets_an_entry_that_runs_start_for_this_config(self):
        argv = ['/home/me/.local/pipx/venvs/token-tv/bin/python', '-m', 'token_tv', 'start', '--yes', '--no-browser',
                '--config', '/home/me/.config/token-tv/config.json']
        unit = autostart.entry(argv, 'systemd')
        self.assertIn('ExecStart=/home/me/.local/pipx/venvs/token-tv/bin/python -m token_tv start --yes', unit)
        self.assertIn('WantedBy=default.target', unit)
        plist = autostart.entry(argv, 'launchd')
        self.assertIn('<string>--no-browser</string>', plist)
        self.assertIn('<key>RunAtLoad</key><true/>', plist)
        vbs = autostart.entry(['C:\\Py\\pythonw.exe', '-m', 'token_tv', 'start', '--config', 'C:\\Users\\me\\config.json'],
                              'startup', path='C:\\Program Files\\nodejs;C:\\Windows')
        self.assertIn('shell.Run """C:\\Py\\pythonw.exe"" ""-m""', vbs)
        self.assertIn(', 0, True', vbs)  # hidden, and waits for it to end before starting it again
        self.assertIn('Do While files.FileExists(WScript.ScriptFullName)', vbs)
        self.assertIn('shell.Environment("Process")("PATH") = "C:\\Program Files\\nodejs;C:\\Windows"', vbs)
        self.assertIn("' config: C:\\Users\\me\\config.json", vbs)
        for text in (unit, plist, vbs):
            self.assertIn(autostart.MARK, text)

    def test_the_entry_keeps_this_terminals_path_and_restarts(self):
        argv = ['/opt/py/bin/python', '-m', 'token_tv', 'start']
        unit = autostart.entry(argv, 'systemd', path='/home/me/.nvm/versions/node/v24/bin:/mnt/c/Program Files/x:/usr/bin')
        self.assertIn('Environment="PATH=/home/me/.nvm/versions/node/v24/bin:/mnt/c/Program Files/x:/usr/bin"', unit)
        self.assertIn('Restart=always', unit)  # waits out a copy running in a terminal, then takes over
        self.assertIn('Environment="PATH=50%%"', autostart.entry(argv, 'systemd', path='50%'))
        plist = autostart.entry(argv, 'launchd', path='/opt/homebrew/bin:/usr/bin')
        self.assertIn('<key>PATH</key><string>/opt/homebrew/bin:/usr/bin</string>', plist)
        self.assertIn('<key>KeepAlive</key><true/>', plist)

    def test_a_missing_systemctl_leaves_nothing_behind(self):
        with self.placed('systemd'), mock.patch('subprocess.run', side_effect=FileNotFoundError('systemctl')):
            with self.assertRaises(OSError):
                autostart.install(self.folder / 'config.json')
        self.assertFalse((self.folder / 'token-tv.service').exists())
        with self.placed('systemd'):
            self.assertEqual(autostart.status(), 'off')

    def test_a_failed_reinstall_puts_the_working_entry_back(self):
        working = autostart.entry(['/old/python', '-m', 'token_tv', 'start'], 'systemd')
        (self.folder / 'token-tv.service').write_text(working, encoding='utf-8')
        failed = mock.Mock(returncode=1, stdout='', stderr='no bus')
        with self.placed('systemd'), mock.patch.object(autostart, 'run', return_value=failed):
            with self.assertRaises(OSError):
                autostart.install(self.folder / 'config.json')
        self.assertEqual((self.folder / 'token-tv.service').read_text(encoding='utf-8'), working)

    def test_a_stop_that_fails_keeps_the_entry_so_off_can_be_tried_again(self):
        (self.folder / 'token-tv.service').write_text(autostart.entry(['/py', '-m', 'token_tv', 'start'], 'systemd'), encoding='utf-8')
        failed = mock.Mock(returncode=1, stdout='', stderr='Failed to stop')
        with self.placed('systemd'), mock.patch.object(autostart, 'run', return_value=failed):
            with self.assertRaises(OSError):
                autostart.remove()
            self.assertEqual(autostart.status(), 'on')

    def test_windows_off_ends_the_copy_running_now(self):
        config = self.folder / 'config.json'
        (self.folder / 'state').mkdir()
        (self.folder / 'state' / 'live.pid').write_text('4242', encoding='utf-8')
        (self.folder / 'TokenTV.vbs').write_text(autostart.entry(['pythonw', '-m', 'token_tv', 'start', '--config', str(config)], 'startup'), encoding='utf-8')
        python = mock.Mock(returncode=0, stdout='"pythonw.exe","4242","Console","1","40,000 K"', stderr='')
        with self.placed('startup'), mock.patch.object(autostart, 'run', return_value=python), mock.patch('os.kill') as kill:
            self.assertIn('stopped', autostart.remove())
        kill.assert_called_once_with(4242, autostart.signal.SIGTERM)
        self.assertFalse((self.folder / 'TokenTV.vbs').exists())

    def test_windows_off_never_ends_another_program_that_took_the_number(self):
        config = self.folder / 'config.json'
        (self.folder / 'state').mkdir()
        (self.folder / 'state' / 'live.pid').write_text('4242', encoding='utf-8')
        (self.folder / 'TokenTV.vbs').write_text(autostart.entry(['pythonw', '-m', 'token_tv', 'start', '--config', str(config)], 'startup'), encoding='utf-8')
        other = mock.Mock(returncode=0, stdout='"notepad.exe","4242","Console","1","9,000 K"', stderr='')
        with self.placed('startup'), mock.patch.object(autostart, 'run', return_value=other), mock.patch('os.kill') as kill:
            self.assertIn('Task Manager', autostart.remove())
        kill.assert_not_called()

    def test_the_npm_launchers_own_uv_starts_it_with_the_computer(self):
        env = {'TOKEN_TV_LAUNCHER': 'npx', 'TOKEN_TV_UVX': '/home/me/.cache/token-tv/uv/uvx'}
        with mock.patch.dict('os.environ', env), mock.patch('sys.prefix', '/home/me/.cache/uv/archive-v0/abc'), \
                mock.patch('shutil.which', return_value=None):
            self.assertEqual(autostart.command('/tmp/config.json')[:3], ['/home/me/.cache/token-tv/uv/uvx', f'token-tv@{__version__}', 'start'])
            self.assertEqual(autostart.how(), 'npx token-tv')

    def test_a_pipx_run_copy_is_started_through_pipx(self):
        with mock.patch('sys.prefix', '/home/me/.local/share/pipx/.cache/0a1b2c'), mock.patch('shutil.which', return_value='/usr/bin/pipx'):
            self.assertEqual(autostart.command('/tmp/config.json')[:5], ['/usr/bin/pipx', 'run', '--spec', f'token-tv=={__version__}', 'token-tv'])
            self.assertEqual(autostart.how(), 'pipx run token-tv')

    def test_the_stop_command_is_the_one_this_person_can_run(self):
        with mock.patch('sys.prefix', '/home/me/.cache/token-tv/venv'):
            self.assertEqual(autostart.how(), 'npx token-tv')
        with mock.patch('sys.prefix', '/home/me/.cache/uv/archive-v0/abc'):
            self.assertEqual(autostart.how(), 'uvx token-tv')
        with mock.patch('sys.prefix', '/home/me/.local/pipx/venvs/token-tv'), mock.patch('shutil.which', return_value='/home/me/.local/bin/token-tv'):
            self.assertEqual(autostart.how(), 'token-tv')
        with mock.patch('sys.prefix', '/proj/.venv'), mock.patch('shutil.which', return_value=None), \
                mock.patch.object(autostart.Path, 'exists', return_value=True):
            folder = 'Scripts' if sys.platform == 'win32' else 'bin'
            self.assertEqual(autostart.how(), str(Path('/proj/.venv') / folder / 'token-tv'))  # a venv not on PATH: its full path

    def test_on_status_off_with_systemd(self):
        config = self.folder / 'config.json'
        config.write_text('{}', encoding='utf-8')
        done = mock.Mock(returncode=0, stdout='', stderr='')
        with self.placed('systemd'), mock.patch.object(autostart, 'run', return_value=done) as run:
            self.assertEqual(autostart.status(), 'off')
            autostart.install(config)
            self.assertEqual(autostart.status(), 'on')
            self.assertIn(['systemctl', '--user', 'enable', '--now', 'token-tv.service'], [c.args[0] for c in run.call_args_list])
            self.assertIn(['systemctl', '--user', 'restart', 'token-tv.service'], [c.args[0] for c in run.call_args_list])
            self.assertIn('stopped', autostart.remove())
            self.assertEqual(autostart.status(), 'off')

    def test_an_entry_written_by_something_else_is_left_alone(self):
        foreign = self.folder / 'token-tv.service'
        foreign.write_text('[Service]\nExecStart=/opt/mine\n', encoding='utf-8')
        with self.placed('systemd'), mock.patch.object(autostart, 'run') as run:
            self.assertEqual(autostart.status(), 'other')
            with self.assertRaises(OSError):
                autostart.install(self.folder / 'config.json')
            self.assertIn('leaving it alone', autostart.remove())
            run.assert_not_called()
        self.assertEqual(foreign.read_text(encoding='utf-8'), '[Service]\nExecStart=/opt/mine\n')

    def test_a_failed_systemctl_leaves_no_entry(self):
        failed = mock.Mock(returncode=1, stdout='', stderr='Failed to connect to bus')
        with self.placed('systemd'), mock.patch.object(autostart, 'run', return_value=failed):
            with self.assertRaises(OSError) as raised:
                autostart.install(self.folder / 'config.json')
        self.assertIn('bus', str(raised.exception))
        self.assertFalse((self.folder / 'token-tv.service').exists())

    def test_uvx_throwaway_copy_is_started_through_uvx(self):
        with mock.patch('sys.prefix', '/home/me/.cache/uv/archive-v0/abc123'), \
                mock.patch('shutil.which', return_value='/home/me/.local/bin/uvx'):
            argv = autostart.command('/tmp/config.json')
        self.assertEqual(argv[:3], ['/home/me/.local/bin/uvx', f'token-tv@{__version__}', 'start'])  # this release, also offline
        with mock.patch('sys.prefix', '/home/me/.local/pipx/venvs/token-tv'):
            self.assertEqual(autostart.command('/tmp/config.json')[1:3], ['-m', 'token_tv'])


if __name__ == '__main__':
    unittest.main()
