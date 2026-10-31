import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from token_tv import cli, sources
from token_tv.display import STYLES
sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    # Commands TokenTV prints follow how it was started; these tests read them as an installed `token-tv`.
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch('token_tv.autostart.how', return_value='token-tv'):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)
        self.config = self.tmp / 'config.json'

    def test_setup_writes_metadata_only_and_never_overwrites(self):
        code, out, _ = run('setup', '--config', str(self.config), '--yes',
                           '--claude-email', 'a@example.com', '--device-url', 'http://10.0.0.9/')
        self.assertEqual(code, 0)
        data = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(data['device_url'], 'http://10.0.0.9')
        self.assertEqual(data['accounts'][0], {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude',
                                               'email': 'a@example.com', 'source_home': '~/.claude'})
        sources.load_config(self.config)  # the daemon accepts what setup writes
        before = self.config.read_text(encoding='utf-8')
        code, _, err = run('setup', '--config', str(self.config), '--yes', '--codex-email', 'b@example.com')
        self.assertEqual(code, 1)
        self.assertIn('never overwrites', err)
        self.assertEqual(self.config.read_text(encoding='utf-8'), before)

    def test_setup_without_accounts_fails_and_writes_nothing(self):
        code, _, err = run('setup', '--config', str(self.config), '--yes')
        self.assertEqual(code, 1)
        self.assertFalse(self.config.exists())
        self.assertIn('--claude-email', err)

    def test_doctor_points_missing_logins_at_connect(self):
        home = self.tmp / 'codex-home'
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'b@example.com',
             'source_home': str(home)}]}), encoding='utf-8')
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/codex'):
            code, out, _ = run('doctor', '--config', str(self.config))
            self.assertEqual(code, 1)
            self.assertIn('token-tv connect --config', out)
            home.mkdir()
            (home / 'auth.json').write_text('{}', encoding='utf-8')  # existence only; doctor never opens it
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
             'source_home': str(self.tmp / 'empty')}]}), encoding='utf-8')
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/claude'), \
                mock.patch.object(cli.sys, 'platform', 'darwin'):
            code, out, _ = run('doctor', '--config', str(self.config))
        self.assertEqual(code, 1)
        self.assertIn('Keychain unchecked', out)

    def test_doctor_checks_codexbar_instead_of_a_login_file(self):
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'a@example.com',
             'codexbar_command': str(self.tmp / 'missing-codexbar'), 'codexbar_source': 'oauth'}]}), encoding='utf-8')
        code, out, _ = run('doctor', '--config', str(self.config))
        self.assertEqual(code, 1)
        self.assertIn('install the CodexBar CLI', out)
        self.assertNotIn('token-tv connect', out)
        unreported = {'status': 'ok', 'identity_verified': False}
        with mock.patch('token_tv.sources.fetch_account', return_value=unreported):
            code, out, _ = run('doctor', '--config', str(self.config), '--live')
        self.assertEqual(code, 0)
        self.assertIn('CodexBar did not report the email for CLAUDE A', out)
        failed = {'status': 'error', 'identity_verified': False}
        with mock.patch('token_tv.sources.fetch_account', return_value=failed):
            code, out, _ = run('doctor', '--config', str(self.config), '--live')
        self.assertEqual(code, 1)
        self.assertIn('live check ERROR', out)

    def test_doctor_live_names_each_failing_account_and_exits_non_zero(self):
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'secret-owner@example.com', 'source_home': '~/.claude'},
            {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'secret-owner@example.com', 'source_home': '~/.codex'},
            {'key': 'copilot_a', 'alias': 'COPILOT A', 'provider': 'copilot', 'email': 'secret-owner@example.com',
             'codexbar_command': 'codexbar'}]}), encoding='utf-8')
        rows = {'claude_a': {'status': 'stale', 'error_code': 'http_401', 'identity_verified': True},
                'codex_a': {'status': 'ok', 'identity_verified': True},
                'copilot_a': {'status': 'error', 'error_code': 'format_changed', 'identity_verified': False}}
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/x'), \
                mock.patch('token_tv.sources.fetch_account', side_effect=lambda a: dict(rows[a['key']], key=a['key'])):
            code, out, err = run('doctor', '--config', str(self.config), '--live')
        self.assertEqual(code, 1)
        failing = [line for line in out.splitlines() if line.startswith('failing: ')]
        self.assertEqual(failing, ['failing: provider=claude alias="CLAUDE A" status=stale error_code=http_401',
                                   'failing: provider=copilot alias="COPILOT A" status=error error_code=format_changed'])
        self.assertNotIn('example.com', out + err)
        rows.update(claude_a={'status': 'ok', 'identity_verified': True}, copilot_a={'status': 'ok', 'identity_verified': True})
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/x'), \
                mock.patch('token_tv.sources.fetch_account', side_effect=lambda a: dict(rows[a['key']], key=a['key'])):
            code, out, _ = run('doctor', '--config', str(self.config), '--live')
        self.assertEqual(code, 0)
        self.assertNotIn('failing: ', out)

    def test_broken_config_gets_a_sentence_not_a_traceback(self):
        self.config.write_text('{"accounts": [', encoding='utf-8')
        for command in ('doctor', 'run'):
            code, _, err = run(command, '--config', str(self.config))
            self.assertEqual(code, 1)
            self.assertIn('not a valid TokenTV config', err)

    def test_setup_two_accounts_reuse_then_isolate(self):
        code, out, _ = run('setup', '--config', str(self.config), '--yes',
                           '--codex-email', 'a@example.com', '--codex-email', 'b@example.com')
        self.assertEqual(code, 0)
        a, b = json.loads(self.config.read_text(encoding='utf-8'))['accounts']
        self.assertEqual((a['key'], a['source_home']), ('codex_a', '~/.codex'))
        self.assertEqual((b['key'], b['alias'], b['source_home']),
                         ('codex_b', 'CODEX B', str(self.tmp / 'homes' / 'codex_b')))
        self.assertIn('separate login', out)
        sources.load_config(self.config)

    def test_setup_isolate_never_points_at_the_everyday_home(self):
        run('setup', '--config', str(self.config), '--yes', '--isolate', '--claude-email', 'a@example.com')
        self.assertNotEqual(json.loads(self.config.read_text(encoding='utf-8'))['accounts'][0]['source_home'], '~/.claude')

    def test_bad_clock_address_is_rejected_before_writing(self):
        for bad in ('ftp://clock', 'http://', 'http://clock/photo', 'http://clock:99999'):
            code, _, err = run('setup', '--config', str(self.config), '--yes',
                               '--claude-email', 'a@example.com', '--device-url', bad)
            self.assertEqual(code, 1, bad)
            self.assertFalse(self.config.exists())
        self.assertEqual(cli.device_address('http://10.0.0.9:8080/'), 'http://10.0.0.9:8080')
        code, _, _ = run('setup', '--config', str(self.config), '--yes', '--claude-email', 'a@example.com',
                         '--device-url', '192.168.0.50')  # a bare address, as start takes it
        self.assertEqual((code, json.loads(self.config.read_text(encoding='utf-8'))['device_url']), (0, 'http://192.168.0.50'))

    def test_doctor_without_config_points_to_start(self):
        code, _, err = run('doctor', '--config', str(self.config))
        self.assertEqual(code, 1)
        self.assertIn('token-tv start', err)

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
        root = temp_dir(self)
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
        home = temp_dir(self)
        (home / '.codex').mkdir()
        (home / '.codex' / 'auth.json').write_text('{}', encoding='utf-8')
        config = home / 'config.json'
        config.write_text(json.dumps({'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex',
                                                     'email': 'a@example.com', 'source_home': '~/.codex'}]}), encoding='utf-8')
        with mock.patch.dict(os.environ, {'HOME': str(home), 'USERPROFILE': str(home)}), \
                mock.patch.object(connect.subprocess, 'run') as login, \
                mock.patch.object(connect.sys, 'argv', ['connect', '--config', str(config), '--account', 'codex_a']):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                connect.main()
        login.assert_not_called()
        self.assertIn('Kept the existing login', out.getvalue())

    def test_macos_keychain_login_is_protected_without_a_file(self):
        from token_tv import connect
        home = temp_dir(self)  # no ~/.claude/.credentials.json at all
        config = home / 'config.json'
        config.write_text(json.dumps({'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude',
                                                     'email': 'a@example.com', 'source_home': '~/.claude'}]}), encoding='utf-8')
        with mock.patch.dict(os.environ, {'HOME': str(home)}), \
                mock.patch.object(connect.sys, 'platform', 'darwin'), \
                mock.patch.object(connect.subprocess, 'run') as login, \
                mock.patch.object(connect.sys, 'argv', ['connect', '--config', str(config), '--account', 'claude_a']):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                connect.main()
        login.assert_not_called()
        self.assertIn('Keychain', out.getvalue())


class AddTest(unittest.TestCase):
    def test_another_account_gets_its_own_login_and_is_signed_in(self):
        from token_tv import connect
        config = temp_dir(self) / 'config.json'
        config.write_text(json.dumps({'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex',
                                                    'email': 'a@example.com', 'source_home': '~/.codex'}]}), encoding='utf-8')
        with mock.patch.object(connect, 'main') as login:
            code, out, _ = run('add', 'codex', '--email', 'b@example.com', '--config', str(config))
        self.assertEqual(code, 0)
        added = json.loads(config.read_text(encoding='utf-8'))['accounts'][1]
        self.assertEqual((added['key'], added['alias'], added['email']), ('codex_b', 'CODEX B', 'b@example.com'))
        self.assertEqual(added['source_home'], str(config.parent / 'homes' / 'codex_b'))  # the everyday login untouched
        login.assert_called_once()
        code, _, err = run('add', 'codex', '--config', str(config))  # no email, not at a terminal
        self.assertEqual(code, 1)
        self.assertIn('--email', err)


class ConfigWriteTest(unittest.TestCase):
    def test_a_change_from_the_command_line_keeps_what_the_running_copy_saved_meanwhile(self):
        config = temp_dir(self) / 'config.json'
        stale = {'display_style': 'pixel', 'accounts': []}
        config.write_text(json.dumps(dict(stale, display_style='neon')), encoding='utf-8')  # the dashboard switched to neon
        with contextlib.redirect_stdout(io.StringIO()):
            cli.save_clock(config, dict(stale), '192.168.0.9')
        saved = json.loads(config.read_text(encoding='utf-8'))
        self.assertEqual((saved['display_style'], saved['device_url']), ('neon', 'http://192.168.0.9'))

    def test_printed_commands_carry_a_custom_config(self):
        with mock.patch('token_tv.autostart.how', return_value='npx token-tv'):
            cli.CONFIG = '/tmp/other/config.json'
            self.assertEqual(cli.cmd('doctor'), 'npx token-tv doctor --config /tmp/other/config.json')
            cli.CONFIG = cli.default_config()
            self.assertEqual(cli.cmd('doctor'), 'npx token-tv doctor')
            cli.CONFIG = None


class PortTest(unittest.TestCase):
    def test_another_program_on_8787_moves_the_dashboard_to_the_next_free_port(self):
        import socket
        with socket.socket() as taken:
            try:
                taken.bind(('127.0.0.1', 8787))
            except OSError:
                self.skipTest('8787 is in use here already')
            taken.listen()
            with mock.patch.object(cli, 'running', return_value=False):
                port, already = cli.dashboard_port()
        self.assertEqual((port, already), (8788, False))

    def test_a_dashboard_already_answering_is_reused(self):
        with mock.patch.object(cli, 'running', side_effect=lambda port: port == 8789):
            with mock.patch('socket.socket.bind', side_effect=OSError):
                self.assertEqual(cli.dashboard_port(), (8789, True))


class StartTest(unittest.TestCase):
    def setUp(self):
        self.config = temp_dir(self) / 'config.json'

    def start(self, *extra, emails=None, found=(), already=False, yes=True):
        from token_tv import live
        emails = emails or {'claude': 'me@example.com', 'codex': None}
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/x'), \
                mock.patch.object(cli, 'login_state', side_effect=lambda p, h: 'yes' if p != 'grok' else 'no'), \
                mock.patch('token_tv.sources.logged_in_email', side_effect=lambda p, h, why=None: emails.get(p)) as detect, \
                mock.patch('token_tv.device.find_clocks', return_value=list(found)) as scan, \
                mock.patch('token_tv.device.clock_info', return_value=None), \
                mock.patch.object(cli, 'dashboard_port', return_value=(8787, already)), \
                mock.patch.object(live, 'main') as run:
            code, out, err = run_cli('start', '--config', str(self.config), *(['--yes'] if yes else []), '--no-browser', *extra)
        self.scan = scan
        return code, out, err, detect, run

    def test_finds_the_clock_on_the_wifi_and_defaults_to_arcade(self):
        code, out, _, _, run = self.start(found=['http://192.168.219.105'])
        self.assertEqual(code, 0)
        data = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual((data['device_url'], data['display_style']), ('http://192.168.219.105', 'arcade'))
        self.assertIn('Found a clock at 192.168.219.105', out)
        run.assert_called_once()

    def test_no_clock_found_runs_the_dashboard_alone(self):
        code, out, _, _, run = self.start()
        self.assertEqual(code, 0)
        self.assertNotIn('device_url', json.loads(self.config.read_text(encoding='utf-8')))
        self.assertIn('No clock found', out)

    def test_started_again_by_hand_it_looks_for_the_clock_but_never_on_its_own(self):
        self.start()  # set up with no clock
        self.assertNotIn('device_url', json.loads(self.config.read_text(encoding='utf-8')))
        self.start()  # --yes, as the computer starts it: a lone clock on a shared Wi-Fi may be someone else's
        self.scan.assert_not_called()
        with mock.patch('sys.stdin.isatty', return_value=True), mock.patch('builtins.input', return_value=''):
            code, out, _, _, _ = self.start(found=['http://192.168.0.77'], already=True, yes=False)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8'))['device_url'], 'http://192.168.0.77')
        self.assertIn('Found a clock at 192.168.0.77', out)

    def test_an_https_address_is_kept_as_the_http_the_clock_speaks(self):
        self.start('--device-url', 'https://192.168.0.50')
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8'))['device_url'], 'http://192.168.0.50')

    def test_an_address_given_is_not_searched_for(self):
        self.start('--device-url', '192.168.0.50')
        self.scan.assert_not_called()

    def test_only_and_face_from_the_web_demo(self):
        both = {'claude': 'me@example.com', 'codex': 'me@example.org'}
        code, _, _, _, _ = self.start('--only', 'codex', '--face', 'pixel', '--device-url', '10.0.0.5', emails=both)
        self.assertEqual(code, 0)
        data = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual([a['provider'] for a in data['accounts']], ['codex'])
        self.assertEqual(data['display_style'], 'pixel')

    @unittest.skipIf(sys.platform == 'win32', 'the stand-in codexbar is a script with a #! line')
    def test_a_codexbar_user_is_set_up_from_what_codexbar_reads(self):
        import os, stat, sys
        folder = temp_dir(self)
        fake = folder / 'codexbar'  # answers like `codexbar usage --provider <p> --format json`
        fake.write_text(f"""#!{sys.executable}
import json, sys
provider = sys.argv[sys.argv.index('--provider') + 1]
usage = {{'primary': {{'usedPercent': 12, 'windowMinutes': 300}}}}
if provider == 'codex':
    usage['accountEmail'] = 'me@example.org'
if provider == 'claude':
    print(json.dumps([{{'provider': 'claude', 'error': {{'message': 'not signed in'}}}}])); sys.exit(1)
print(json.dumps([{{'provider': provider, 'usage': usage}}]))
""", encoding='utf-8')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, {'PATH': f'{folder}{os.pathsep}{os.environ["PATH"]}'}):
            code, out, _, _, run = self.start('--device-url', '10.0.0.5', emails={'claude': None, 'codex': None})
        self.assertEqual(code, 0)
        accounts = json.loads(self.config.read_text(encoding='utf-8'))['accounts']
        self.assertEqual([(a['provider'], a['email'], a['codexbar_command']) for a in accounts],
                         [('codex', 'me@example.org', 'codexbar'), ('copilot', 'not reported by CodexBar', 'codexbar'),
                          ('antigravity', 'not reported by CodexBar', 'codexbar')])
        self.assertIn('Copilot: through CodexBar', out)
        run.assert_called_once()

    def test_only_a_codexbar_service_without_codexbar_says_how(self):
        with mock.patch('shutil.which', return_value=None):
            code, _, err, _, _ = self.start('--only', 'copilot')
        self.assertEqual(code, 1)
        self.assertIn('install CodexBar', err)

    def test_on_a_mac_a_browser_only_claude_user_is_told_about_codexbar(self):
        with mock.patch('sys.platform', 'darwin'), mock.patch('shutil.which', return_value=None):
            code, _, err, _, _ = self.start(emails={'claude': None, 'codex': None})
        self.assertEqual(code, 1)
        self.assertIn('Claude in the browser only, on a Mac', err)
        with mock.patch('sys.platform', 'linux'), mock.patch('shutil.which', return_value=None):
            _, _, err, _, _ = self.start(emails={'claude': None, 'codex': None})
        self.assertNotIn('on a Mac', err)

    def test_only_a_service_not_signed_in_says_which(self):
        code, _, err, _, run = self.start('--only', 'codex')
        self.assertEqual(code, 1)
        self.assertIn('No signed-in Codex CLI', err)
        run.assert_not_called()

    def test_only_naming_more_than_is_signed_in_still_sets_up(self):
        code, _, _, _, run = self.start('--only', 'claude,codex', '--device-url', '10.0.0.5')  # only Claude signed in
        self.assertEqual(code, 0)
        self.assertEqual([a['provider'] for a in json.loads(self.config.read_text(encoding='utf-8'))['accounts']], ['claude'])
        run.assert_called_once()

    def test_already_running_still_refuses_a_conflicting_only_and_switches_the_face(self):
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'a@example.com', 'source_home': '~/.claude'}]}), encoding='utf-8')
        code, _, err, _, _ = self.start('--only', 'codex', already=True)
        self.assertEqual(code, 1)
        self.assertIn('claude as well', err)
        with mock.patch.object(cli, 'show_face') as face:
            code, out, _, _, _ = self.start('--face', 'neon', already=True)
        self.assertEqual(code, 0)
        face.assert_called_once_with(8787, 'neon')

    def test_a_login_that_did_not_answer_says_why(self):
        def refused(p, h, why=None):
            why.append('refused' if p == 'claude' else 'not_chatgpt')
            return None
        from token_tv import live
        with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/x'), mock.patch.object(cli, 'login_state', return_value='yes'), \
                mock.patch('token_tv.sources.logged_in_email', side_effect=refused), mock.patch('token_tv.device.find_clocks', return_value=[]), \
                mock.patch.object(cli, 'dashboard_port', return_value=(8787, False)), mock.patch.object(live, 'main'):
            code, _, err = run_cli('start', '--config', str(self.config), '--yes', '--no-browser', '--only', 'claude,codex')
        self.assertEqual(code, 1)
        self.assertIn('Claude: signed in, but the saved login was refused', err)
        self.assertIn('Codex: signed in with an API key', err)
        self.assertNotIn('Grok:', err)  # only the tools asked for

    def test_only_rejects_unknown_services(self):
        code, _, err, _, _ = self.start('--only', 'gemini')
        self.assertEqual(code, 1)
        self.assertIn('--only takes', err)

    def test_a_face_given_again_is_kept_in_the_existing_config(self):
        self.saved_config('http://192.168.0.50')
        code, _, _, _, run = self.start('--face', 'neon')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8'))['display_style'], 'neon')
        run.assert_called_once()

    def test_already_running_opens_it_and_starts_no_second_copy(self):
        code, out, _, detect, run = self.start(already=True)
        self.assertEqual(code, 0)
        self.assertIn('already running', out)
        self.assertFalse(self.config.exists())
        run.assert_not_called()

    def test_the_background_question_is_asked_only_when_the_config_is_made(self):
        from token_tv import autostart, live
        self.saved_config('http://192.168.0.50')
        with mock.patch.object(cli, 'dashboard_port', return_value=(8787, False)), \
                mock.patch('sys.stdin.isatty', return_value=True), mock.patch.object(cli, 'ask', return_value='y') as ask, \
                mock.patch.object(autostart, 'status', return_value='off'), mock.patch.object(live, 'main'):
            run_cli('start', '--config', str(self.config), '--no-browser')
        self.assertFalse(any('computer' in c.args[0] for c in ask.call_args_list))

    def test_asked_once_to_start_with_the_computer(self):
        from token_tv import autostart, live
        for answer, background in (('y', True), ('n', False)):
            self.config.unlink(missing_ok=True)
            with mock.patch.object(cli, 'cli_path', return_value='/usr/bin/x'), \
                    mock.patch.object(cli, 'login_state', return_value='yes'), \
                    mock.patch('token_tv.sources.logged_in_email', side_effect=lambda p, h, why=None: 'me@example.com' if p == 'codex' else None), \
                    mock.patch('token_tv.device.find_clocks', return_value=[]), \
                    mock.patch.object(cli, 'dashboard_port', side_effect=[(8787, False), (8788, True)]), \
                    mock.patch('sys.stdin.isatty', return_value=True), \
                    mock.patch.object(cli, 'ask', side_effect=lambda prompt, default='': answer if 'computer' in prompt else 'y' if '[Y/n]' in prompt else ''), \
                    mock.patch.object(autostart, 'status', return_value='off'), \
                    mock.patch.object(autostart, 'install', return_value='Runs in the background now') as install, \
                    mock.patch.object(live, 'main') as run:
                code, out, _ = run_cli('start', '--config', str(self.config), '--no-browser')
            self.assertEqual(code, 0)
            self.assertEqual(install.called, background, answer)
            self.assertEqual(run.called, not background, answer)
            if background:
                self.assertIn('Dashboard: http://127.0.0.1:8788', out)  # where the background copy answered

    def test_a_background_copy_that_never_answers_is_reported(self):
        from token_tv import autostart, live
        with mock.patch.object(cli, 'dashboard_port', return_value=(8787, False)), \
                mock.patch.object(cli, 'cli_path', return_value='/usr/bin/x'), mock.patch.object(cli, 'login_state', return_value='yes'), \
                mock.patch('token_tv.sources.logged_in_email', side_effect=lambda p, h, why=None: 'me@example.com' if p == 'codex' else None), \
                mock.patch('token_tv.device.find_clocks', return_value=[]), \
                mock.patch('sys.stdin.isatty', return_value=True), mock.patch.object(cli, 'ask', return_value='y'), \
                mock.patch.object(autostart, 'status', return_value='off'), \
                mock.patch.object(autostart, 'install', return_value='ok'), mock.patch.object(cli.time, 'sleep'), \
                mock.patch.object(live, 'main') as run:
            code, _, err = run_cli('start', '--config', str(self.config), '--no-browser')
        self.assertEqual(code, 1)
        self.assertIn('autostart status', err)
        run.assert_not_called()

    def test_only_on_an_existing_config_with_other_services_is_refused(self):
        self.config.write_text(json.dumps({'accounts': [
            {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'email': 'a@example.com', 'source_home': '~/.claude'},
            {'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex', 'email': 'b@example.com', 'source_home': '~/.codex'}]}), encoding='utf-8')
        code, _, err, _, run = self.start('--only', 'codex')
        self.assertEqual(code, 1)
        self.assertIn('claude as well', err)
        run.assert_not_called()

    def test_detects_signed_in_email_and_runs(self):
        code, out, _, detect, run = self.start('--device-url', '192.168.0.50')
        self.assertEqual(code, 0)
        data = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual([(a['provider'], a['email']) for a in data['accounts']], [('claude', 'me@example.com')])
        self.assertEqual(data['device_url'], 'http://192.168.0.50')  # bare IP is accepted
        run.assert_called_once()

    def test_existing_config_skips_detection(self):
        self.config.write_text(json.dumps({'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex',
                                                         'email': 'b@example.com', 'source_home': '~/.codex'}]}), encoding='utf-8')
        code, _, _, detect, run = self.start()
        self.assertEqual(code, 0)
        detect.assert_not_called()
        run.assert_called_once()

    def saved_config(self, device_url):
        config = {'device_url': device_url, 'accounts': [{'key': 'codex_a', 'alias': 'CODEX A', 'provider': 'codex',
                                                          'email': 'b@example.com', 'source_home': '~/.codex'}]}
        self.config.write_text(json.dumps(config), encoding='utf-8')
        return config

    def test_a_clock_address_given_later_is_kept_in_the_config(self):
        # Reported in #7 (an address silently ignored) and by QA: a clock added after the first start.
        self.saved_config('http://192.168.0.50')
        code, out, _, _, run = self.start('--device-url', '192.168.0.77')
        self.assertEqual(code, 0)
        self.assertIn('http://192.168.0.77', out)
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8'))['device_url'], 'http://192.168.0.77')
        run.assert_called_once()
        self.config.write_text(json.dumps({'accounts': json.loads(self.config.read_text(encoding='utf-8'))['accounts']}))  # no clock yet
        code, _, _, _, run = self.start('--device-url', '10.0.0.9', already=True)  # while one runs: it takes it up
        self.assertEqual((code, json.loads(self.config.read_text(encoding='utf-8'))['device_url']), (0, 'http://10.0.0.9'))
        code, _, err, _, _ = self.start('--device-url', 'ftp://nope')
        self.assertEqual(code, 1)

    def test_same_clock_address_with_existing_config_runs(self):
        self.saved_config('http://192.168.0.50')
        code, _, err, _, run = self.start('--device-url', '192.168.0.50')
        self.assertEqual((code, err), (0, ''))
        run.assert_called_once()

    def test_nothing_signed_in_explains_next_step(self):
        from token_tv import live
        with mock.patch.object(cli, 'cli_path', return_value=None), mock.patch.object(live, 'main') as run:
            code, _, err = run_cli('start', '--config', str(self.config), '--yes', '--no-browser')
        self.assertEqual(code, 1)
        self.assertIn('token-tv demo', err)
        self.assertFalse(self.config.exists())
        run.assert_not_called()


def run_cli(*argv):
    return run(*argv)
