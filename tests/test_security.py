"""A dashboard open to the network answers only by this computer's names; `autostart off` ends only TokenTV;
what TokenTV writes is readable by its user alone."""
import io
import json
import os
import stat
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir

from token_tv import autostart, cli, live, lockbox
from token_tv.state import UsageStore


def ask(handler, path, method='GET', host='127.0.0.1:8787', body=None, origin=None):
    """One request through the real handler, in memory: (status, body)."""
    request = handler.__new__(handler)
    request.path, request.command, request.request_version = path, method, 'HTTP/1.1'
    request.requestline = f'{method} {path} HTTP/1.1'
    request.headers = Message()
    if host is not None:
        request.headers['Host'] = host
    data = json.dumps(body).encode() if body is not None else b''
    if body is not None:
        request.headers['Content-Type'] = 'application/json'
        request.headers['Content-Length'] = str(len(data))
    if origin:
        request.headers['Origin'] = origin
    request.rfile, request.wfile = io.BytesIO(data), io.BytesIO()
    getattr(request, 'do_' + method)()
    head, answer = request.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(head.split()[1]), answer


class LanHostTests(unittest.TestCase):
    def setUp(self):
        folder = temp_dir(self)
        self.config = folder / 'config.json'
        config = {'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'a@example.com'}],
                  'display_style': 'pixel'}
        self.config.write_text(json.dumps(config), encoding='utf-8')
        self.store = UsageStore(config['accounts'])
        self.prefs = live.DisplayPreferences(self.config, config)

    def test_only_this_computers_names_and_addresses_are_answered(self):
        handler = live.handler(self.store, self.prefs, local_only=False, names={'192.168.0.20', 'mini', 'mini.local'})
        for host in ('192.168.0.20:8787', 'mini:8787', 'MINI.local:8787', 'localhost:8787', '127.0.0.1:8787', '[::1]:8787'):
            self.assertEqual(ask(handler, '/snapshot', host=host)[0], 200, host)
        for host in ('evil.invalid:8787', 'localhost.evil.invalid:8787', 'mini.evil.invalid', '', None):
            status, answer = ask(handler, '/snapshot', host=host)
            self.assertEqual(status, 403, host)
            self.assertNotIn(b'CODEX A', answer)  # nothing read

    def test_a_renamed_page_cannot_change_the_face(self):
        host = 'untrusted.example:8787'
        handler = live.handler(self.store, self.prefs, local_only=False, names={'192.168.0.20'})
        status, _ = ask(handler, '/display/style', 'POST', host, {'style': 'digital'}, 'http://' + host)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8'))['display_style'], 'pixel')
        status, _ = ask(handler, '/display/style', 'POST', '192.168.0.20:8787', {'style': 'digital'}, 'http://192.168.0.20:8787')
        self.assertEqual(status, 200)

    def test_this_computers_names_are_found_on_their_own(self):
        with mock.patch('socket.gethostname', return_value='Mini'), mock.patch('socket.getfqdn', return_value='mini.lan'), \
                mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('192.168.0.20', 0))]), \
                mock.patch('token_tv.device.local_addresses', return_value=['10.0.0.5']):
            names = live.lan_names('192.168.0.20')
        self.assertTrue({'mini', 'mini.lan', 'mini.local', '192.168.0.20', '10.0.0.5', 'localhost'} <= names)
        self.assertNotIn('0.0.0.0', live.lan_names('0.0.0.0'))
        handler = live.handler(self.store, self.prefs, local_only=False)  # names found when none are given
        self.assertEqual(ask(handler, '/snapshot', host='evil.invalid')[0], 403)


class WindowsStopTests(unittest.TestCase):
    """`autostart off` on Windows ends the process in live.pid only when it is TokenTV running this config."""
    def setUp(self):
        self.folder = temp_dir(self)
        self.config = self.folder / 'Kim Minji' / 'config.json'
        (self.config.parent / 'state').mkdir(parents=True)
        self.place = mock.patch.object(autostart, 'place', return_value=(self.folder / 'TokenTV.vbs', 'startup'))
        self.arm()

    def arm(self):
        """The entry and the number TokenTV left, as after a run (`off` removes the entry)."""
        (self.config.parent / 'state' / 'live.pid').write_text('4242', encoding='utf-8')
        (self.folder / 'TokenTV.vbs').write_text(autostart.entry(
            ['C:\\Py\\pythonw.exe', '-m', 'token_tv', 'start', '--config', str(self.config)], 'startup'), encoding='utf-8')

    def stop(self, command_line, code=0):
        shown = mock.Mock(returncode=code, stdout=command_line + '\r\n', stderr='')
        with self.place, mock.patch.object(autostart, 'run', return_value=shown) as asked, mock.patch('os.kill') as kill:
            said = autostart.remove()
        self.assertIn('4242', ' '.join(asked.call_args.args[0]))  # it asked about that process
        return kill, said

    def test_ends_tokentv_running_this_config(self):
        for line in (f'"C:\\Py\\pythonw.exe" "-m" "token_tv" "start" "--yes" "--no-browser" "--config" "{self.config}"',
                     f'"C:\\Users\\me\\.cache\\uv\\archive-v0\\x\\Scripts\\python.exe" "C:\\Users\\me\\.cache\\uv\\archive-v0\\x\\Scripts\\token-tv.exe" start --yes --config "{self.config}"'):
            with self.subTest(line=line):
                self.arm()
                kill, said = self.stop(line)
                kill.assert_called_once_with(4242, autostart.signal.SIGTERM)
                self.assertIn('stopped', said)

    def test_leaves_anything_else_running(self):
        other = self.config.parent.parent / 'Kim Minji2' / 'config.json'
        for line, code in (('"C:\\Python312\\python.exe" train.py --epochs 3', 0),  # another Python job took the number
                           (f'"C:\\Py\\pythonw.exe" -m token_tv start --config "{other}"', 0),  # TokenTV, another config
                           (f'"C:\\Py\\pythonw.exe" -m token_tv start --config "{self.config}.bak"', 0),  # a longer path
                           ('notepad.exe', 0),
                           ('', 0),  # gone, or not readable
                           ('', 1)):  # PowerShell missing or refused
            with self.subTest(line=line, code=code):
                self.arm()
                kill, said = self.stop(line, code)
                kill.assert_not_called()
                self.assertIn('Task Manager', said)


@unittest.skipIf(os.name == 'nt', 'Windows keeps its own per-user rights')
class FileModeTests(unittest.TestCase):
    """Under the loosest umask, folders are 0700 and files 0600 from the moment they exist, through the rename."""
    def setUp(self):
        self.folder = temp_dir(self)
        old = os.umask(0)
        self.addCleanup(os.umask, old)
        self.renamed = []
        real = os.replace
        def replace(source, target):
            self.renamed.append(stat.S_IMODE(os.stat(source).st_mode))
            return real(source, target)
        patcher = mock.patch('os.replace', side_effect=replace)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_the_config_and_its_folder(self):
        config = self.folder / 'new' / 'token-tv' / 'config.json'
        with mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(cli.main(['setup', '--yes', '--codex-email', 'a@example.com', '--config', str(config)]), 0)
        self.assertEqual((self.mode(config.parent), self.mode(config)), (0o700, 0o600))
        cli.update_config(config, display_style='neon')
        self.assertEqual(self.mode(config), 0o600)
        self.assertTrue(self.renamed and set(self.renamed) == {0o600})

    def test_history_snapshot_and_the_state_folder(self):
        state = self.folder / 'state'
        live.private_dir(state)
        self.assertEqual(self.mode(state), 0o700)
        history = lockbox.History(state / 'history.json')
        history.data['peaks'] = {'a': {'WEEK': {'2026-W44': 72}}}
        history.save()
        live.write_json(state / 'snapshot.json', {'accounts': {}})
        self.assertEqual((self.mode(state / 'history.json'), self.mode(state / 'snapshot.json')), (0o600, 0o600))
        self.assertEqual(set(self.renamed), {0o600})  # the temporary files too, before they take the name

    def test_a_file_left_wide_open_by_an_older_version_is_closed_on_its_next_write(self):
        path = self.folder / 'snapshot.json'
        path.write_text('{}', encoding='utf-8')
        os.chmod(path, 0o644)
        (self.folder / 'snapshot.json.tmp').write_text('{}', encoding='utf-8')
        os.chmod(self.folder / 'snapshot.json.tmp', 0o666)  # a leftover from a crash
        live.write_json(path, {'accounts': {}})
        self.assertEqual(self.mode(path), 0o600)
        self.assertEqual(set(self.renamed), {0o600})


if __name__ == '__main__':
    unittest.main()
