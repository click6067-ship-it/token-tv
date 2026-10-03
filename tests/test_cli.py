import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from token_tv import cli, sources
from token_tv.display import STYLES


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = self.tmp / 'config.json'

    def test_setup_writes_metadata_only_and_never_overwrites(self):
        code, out, _ = run('setup', '--config', str(self.config), '--yes',
                           '--claude-email', 'a@example.com', '--device-url', 'http://10.0.0.9/')
        self.assertEqual(code, 0)
        data = json.loads(self.config.read_text())
        self.assertEqual(data['device_url'], 'http://10.0.0.9')
        self.assertEqual(data['accounts'][0], {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude',
                                               'email': 'a@example.com', 'source_home': '~/.claude'})
        sources.load_config(self.config)  # the daemon accepts what setup writes
        before = self.config.read_text()
        code, _, err = run('setup', '--config', str(self.config), '--yes', '--codex-email', 'b@example.com')
        self.assertEqual(code, 1)
        self.assertIn('never overwrites', err)
        self.assertEqual(self.config.read_text(), before)

    def test_setup_without_accounts_fails_and_writes_nothing(self):
        code, _, err = run('setup', '--config', str(self.config), '--yes')
        self.assertEqual(code, 1)
        self.assertFalse(self.config.exists())
        self.assertIn('--claude-email', err)

    def test_doctor_points_missing_logins_at_connect(self):
        home = self.tmp / 'codex-home'
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'b@example.com',
             'source_home': str(home)}]}))
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/codex'):
            code, out, _ = run('doctor', '--config', str(self.config))
            self.assertEqual(code, 1)
            self.assertIn('token-tv connect --config', out)
            home.mkdir()
            (home / 'auth.json').write_text('{}')  # existence only; doctor never opens it
            code, out, _ = run('doctor', '--config', str(self.config))
        self.assertEqual(code, 0)
        self.assertIn('not verified', out)
        self.assertNotIn('Ready', out)
        bad = {'status': 'identity_mismatch', 'identity_verified': False}
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/codex'), \
                mock.patch('token_tv.sources.fetch_account', return_value=bad):
            code, out, _ = run('doctor', '--config', str(self.config), '--live')
        self.assertEqual(code, 1)
        self.assertIn('IDENTITY_MISMATCH', out)
        good = {'status': 'ok', 'identity_verified': True}
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/codex'), \
                mock.patch('token_tv.sources.fetch_account', return_value=good):
            code, out, _ = run('doctor', '--config', str(self.config), '--live')
        self.assertEqual(code, 0)
        self.assertIn('Ready', out)

    def test_doctor_never_calls_an_unchecked_keychain_ready(self):
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'a@example.com',
             'source_home': str(self.tmp / 'empty')}]}))
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/claude'), \
                mock.patch.object(cli.sys, 'platform', 'darwin'):
            code, out, _ = run('doctor', '--config', str(self.config))
        self.assertEqual(code, 1)
        self.assertIn('Keychain unchecked', out)

    def test_broken_config_gets_a_sentence_not_a_traceback(self):
        self.config.write_text('{"accounts": [')
        for command in ('doctor', 'run'):
            code, _, err = run(command, '--config', str(self.config))
            self.assertEqual(code, 1)
            self.assertIn('not a valid TokenTV config', err)

    def test_setup_two_accounts_reuse_then_isolate(self):
        code, out, _ = run('setup', '--config', str(self.config), '--yes',
                           '--codex-email', 'a@example.com', '--codex-email', 'b@example.com')
        self.assertEqual(code, 0)
        a, b = json.loads(self.config.read_text())['accounts']
        self.assertEqual((a['key'], a['source_home']), ('codex_a', '~/.codex'))
        self.assertEqual((b['key'], b['alias'], b['source_home']),
                         ('codex_b', 'CODEX B', str(self.tmp / 'homes' / 'codex_b')))
        self.assertIn('separate login', out)
        sources.load_config(self.config)

    def test_setup_isolate_never_points_at_the_everyday_home(self):
        run('setup', '--config', str(self.config), '--yes', '--isolate', '--claude-email', 'a@example.com')
        self.assertNotEqual(json.loads(self.config.read_text())['accounts'][0]['source_home'], '~/.claude')

    def test_bad_clock_address_is_rejected_before_writing(self):
        for bad in ('192.168.0.50', 'ftp://clock', 'http://', 'http://clock/photo', 'http://clock:99999'):
            code, _, err = run('setup', '--config', str(self.config), '--yes',
                               '--claude-email', 'a@example.com', '--device-url', bad)
            self.assertEqual(code, 1, bad)
            self.assertFalse(self.config.exists())
        self.assertEqual(cli.device_address('http://10.0.0.9:8080/'), 'http://10.0.0.9:8080')

    def test_doctor_without_config_explains_setup(self):
        code, _, err = run('doctor', '--config', str(self.config))
        self.assertEqual(code, 1)
        self.assertIn('token-tv setup', err)

    def test_demo_renders_every_face_from_sample_data(self):
        code, out, _ = run('demo', '--out', str(self.tmp / 'demo'), '--scale', '2')
        self.assertEqual(code, 0)
        files = list((self.tmp / 'demo').iterdir())
        self.assertEqual(len([p for p in files if '@' not in p.name]), len(STYLES))
        self.assertIn('demo-space.gif', [p.name for p in files])
        signature = {'.jpg': b'\xff\xd8\xff', '.gif': b'GIF8', '.png': b'\x89PNG'}
        for path in files:  # every extension matches the bytes inside
            self.assertTrue(path.read_bytes().startswith(signature[path.suffix]), path.name)
        self.assertIn('Sample data only', out)


class KeychainTest(unittest.TestCase):
    def test_service_names_follow_claude_code(self):
        root = Path('/Users/me/.token-tv/claude-b')
        self.assertEqual(sources.keychain_services(root), ['Claude Code-credentials-' + __import__('hashlib')
                                                           .sha256(str(root).encode()).hexdigest()[:8]])
        default = Path('~/.claude').expanduser()
        self.assertEqual(sources.keychain_services(default)[-1], 'Claude Code-credentials')

    def test_keychain_is_used_only_on_macos_without_a_file(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(sources.sys, 'platform', 'linux'):
            with self.assertRaises(FileNotFoundError):
                sources.claude_token(root)
        found = mock.Mock(returncode=0, stdout=json.dumps({'claudeAiOauth': {'accessToken': 'synthetic'}}))
        with mock.patch.object(sources.sys, 'platform', 'darwin'), \
                mock.patch.object(sources.subprocess, 'run', return_value=found) as call, \
                mock.patch.dict(os.environ, {'USER': 'me'}):
            self.assertEqual(sources.claude_token(root), 'synthetic')
        self.assertEqual(call.call_args[0][0][:5], ['security', 'find-generic-password', '-a', 'me', '-w'])
        missing = mock.Mock(returncode=44, stdout='')
        with mock.patch.object(sources.sys, 'platform', 'darwin'), \
                mock.patch.object(sources.subprocess, 'run', return_value=missing):
            with self.assertRaises(sources.SourceError):
                sources.claude_token(root)


if __name__ == '__main__':
    unittest.main()


class ConnectGuardTest(unittest.TestCase):
    def test_everyday_login_is_kept_without_explicit_replace(self):
        from token_tv import connect
        home = Path(tempfile.mkdtemp())
        (home / '.codex').mkdir()
        (home / '.codex' / 'auth.json').write_text('{}')
        config = home / 'config.json'
        config.write_text(json.dumps({'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex',
                                                     'email': 'a@example.com', 'source_home': '~/.codex'}]}))
        with mock.patch.dict(os.environ, {'HOME': str(home)}), \
                mock.patch.object(connect.subprocess, 'run') as login, \
                mock.patch.object(connect.sys, 'argv', ['connect', '--config', str(config), '--account', 'codex_a']):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                connect.main()
        login.assert_not_called()
        self.assertIn('Kept the existing login', out.getvalue())

    def test_macos_keychain_login_is_protected_without_a_file(self):
        from token_tv import connect
        home = Path(tempfile.mkdtemp())  # no ~/.claude/.credentials.json at all
        config = home / 'config.json'
        config.write_text(json.dumps({'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude',
                                                     'email': 'a@example.com', 'source_home': '~/.claude'}]}))
        with mock.patch.dict(os.environ, {'HOME': str(home)}), \
                mock.patch.object(connect.sys, 'platform', 'darwin'), \
                mock.patch.object(connect.subprocess, 'run') as login, \
                mock.patch.object(connect.sys, 'argv', ['connect', '--config', str(config), '--account', 'claude_a']):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                connect.main()
        login.assert_not_called()
        self.assertIn('Keychain', out.getvalue())
