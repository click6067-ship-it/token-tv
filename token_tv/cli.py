"""token-tv: set up, check, preview and run TokenTV.

    token-tv start     find your signed-in CLIs and the clock, keep it running (the easy way)
    token-tv autostart start TokenTV with this computer (on), stop that (off), or check (status)
    token-tv setup     write a credential-free config (never overwrites one)
    token-tv doctor    check CLIs and login files (--live asks each provider)
    token-tv demo      render every clock face with sample data
    token-tv connect   sign an account in with its official CLI
    token-tv run       start the dashboard and drive the clock
"""
import argparse
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path
from http.client import HTTPException
from urllib.parse import urlparse

PROVIDERS = {
    # provider: (CLI command, default home, file the CLI writes after login, login hint)
    'claude': ('claude', '~/.claude', '.credentials.json', 'claude auth login'),
    'codex': ('codex', '~/.codex', 'auth.json', 'codex login'),
    'grok': ('grok', '~/.grok', 'auth.json', 'grok login'),
}


def default_config():
    base = os.environ.get('XDG_CONFIG_HOME') or '~/.config'
    return str(Path(base).expanduser() / 'token-tv' / 'config.json')


def cli_path(provider):
    command = os.environ.get('TOKEN_TV_GROK_BIN', 'grok') if provider == 'grok' else PROVIDERS[provider][0]
    return shutil.which(command)


def login_state(provider, home):
    """'yes', 'no' or 'keychain'. Only checks that the login file exists; never opens it."""
    root = Path(home).expanduser()
    if (root / PROVIDERS[provider][2]).is_file():
        return 'yes'
    if provider == 'claude' and sys.platform == 'darwin':
        return 'keychain'
    return 'no'


def ask(prompt, default=''):
    try:
        answer = input(f'{prompt}{f" [{default}]" if default else ""}: ').strip()
    except EOFError:
        answer = ''
    return answer or default


def device_address(text):
    """'http://host[:port]' with the trailing slash removed, or ValueError with a fix."""
    url = urlparse(text.strip())
    if url.scheme not in ('http', 'https') or not url.hostname or url.path.strip('/') or url.query:
        raise ValueError(f'{text!r} is not a clock address; use the form http://192.168.0.50')
    try:
        url.port
    except ValueError:
        raise ValueError(f'{text!r} has an invalid port') from None
    return f'{url.scheme}://{url.netloc}'


def setup(args):
    path = Path(args.config).expanduser()
    if path.exists():
        print(f'{path} already exists; TokenTV never overwrites a config.\n'
              f'Edit it, or choose another path with --config.', file=sys.stderr)
        return 1
    interactive = not args.yes and sys.stdin.isatty()
    homes = path.parent / 'homes'
    accounts = []
    for provider, (_, home, _, hint) in PROVIDERS.items():
        emails = list(getattr(args, f'{provider}_email') or [])
        if interactive and not emails:
            print(f'\n{provider.title()}: CLI {"found" if cli_path(provider) else "not found"}')
            for letter in 'ABC':
                email = ask(f'  {provider.title()} account {letter} email (blank to {"skip" if letter == "A" else "finish"})')
                if not email:
                    break
                emails.append(email)
        if len(emails) > 3:
            print(f'At most three {provider} accounts (A, B, C).', file=sys.stderr)
            return 1
        for index, email in enumerate(emails):
            letter = 'ABC'[index]
            key = f'{provider}_{letter.lower()}'
            reuse = index == 0 and not args.isolate
            if reuse and interactive:
                print(f'  {letter}: reuse the {provider} login in {home} (y), or keep a separate login '
                      f'for TokenTV in {homes / key} (n)?')
                reuse = ask('  Reuse', 'y').lower().startswith('y')
            accounts.append({'key': key, 'alias': f'{provider.upper()} {letter}', 'provider': provider,
                             'email': email, 'source_home': home if reuse else str(homes / key)})
    if not accounts:
        print('No accounts given. Pass --claude-email, --codex-email or --grok-email (repeat for B and C), '
              'or run setup in a terminal to be asked.', file=sys.stderr)
        return 1
    device = args.device_url
    while device is None and interactive:
        device = ask('\nClock address, e.g. http://192.168.0.50 (blank for dashboard only)')
        try:
            device = device and device_address(device)
        except ValueError as error:
            print(f'  {error}')
            device = None
    try:
        device = device and device_address(device)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    config = {'poll_seconds': 60, 'accounts': accounts, 'display_style': 'arcade'}
    if device:
        config['device_url'] = device
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'x') as handle:  # 'x' refuses to replace a file created meanwhile
            json.dump(config, handle, indent=2)
            handle.write('\n')
    except OSError as error:
        print(f'Could not write {path}: {error.strerror or error}', file=sys.stderr)
        return 1
    flag = '' if str(path) == default_config() else f' --config {path}'
    print(f'Wrote {path} ({len(accounts)} account{"s" * (len(accounts) != 1)}; emails and paths only, no secrets).')
    for account in accounts:
        shared = account['source_home'] == PROVIDERS[account['provider']][1]
        print(f'  {account["alias"]:<9} {"reuses your existing CLI login" if shared else "separate login"} '
              f'in {account["source_home"]}')
    print(f'Next: token-tv doctor{flag}   (separate logins need: token-tv connect{flag} --account <key>)')
    return 0


def read_config(path):
    """The validated config, or None after printing a one-line reason."""
    from token_tv.sources import load_config
    path = Path(path).expanduser()
    if not path.is_file():
        print(f'No config at {path}. Run: token-tv start', file=sys.stderr)
        return None
    try:
        return load_config(path)
    except OSError as error:
        print(f'Could not read {path}: {error.strerror or error}', file=sys.stderr)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        print(f'{path} is not a valid TokenTV config ({error}). Compare it with config.example.json.', file=sys.stderr)
    return None


def doctor(args):
    config = read_config(args.config)
    if config is None:
        return 1
    flag = '' if str(Path(args.config).expanduser()) == default_config() else f' --config {args.config}'
    ready = True
    unreported = []
    for account in config['accounts']:
        provider = account['provider']
        if account.get('codexbar_command') or account.get('codexbar_url'):
            # CodexBar owns this login; TokenTV only checks that it answers.
            command = account.get('codexbar_command')
            line = f'{account["alias"]:<10} {provider:<6} CodexBar '
            if args.live:
                from token_tv.sources import fetch_account
                row = fetch_account(account)
                good = row['status'] in ('ok', 'quota_unavailable')
                line += f'live check {"ok" if good else row["status"].upper()}'
                if good and not row.get('identity_verified'):
                    line += ' (CodexBar reported no email)'
                    unreported.append(account['alias'])
                ready &= good
            elif command and not shutil.which(os.path.expanduser(command)):
                ready = False
                line += f'MISSING: {command} not found -> install the CodexBar CLI'
            else:
                line += f'{command or account["codexbar_url"]} (not checked yet)'
            print(line)
            continue
        home = account.get('source_home') or PROVIDERS[provider][1]
        found, state = cli_path(provider), login_state(provider, home)
        line = f'{account["alias"]:<10} {provider:<6} CLI {"ok" if found else "MISSING"}  '
        if args.live:
            from token_tv.sources import fetch_account
            row = fetch_account(account)
            good = row['status'] in ('ok', 'quota_unavailable') and row.get('identity_verified')
            line += f'live check {"ok" if good else row["status"].upper()}'
            ready &= bool(good)
            if not good:
                line += f' -> token-tv connect{flag} --account {account["key"]}'
        elif state == 'yes':
            line += 'login file present (not verified yet)'
        elif state == 'keychain':
            ready = False
            line += 'no login file; macOS Keychain unchecked (untested on real Macs) -> doctor --live'
        else:
            ready = False
            line += f'login MISSING -> token-tv connect{flag} --account {account["key"]}'
        if not found:
            ready = False
            line += f'\n{"":<18}install the {provider} CLI, then log in ({PROVIDERS[provider][3]})'
        print(line)
    print('Clock: ' + (config.get('device_url') or 'none (dashboard only)'))
    if not ready:
        print(f'Fix the lines above, then run token-tv doctor{flag} again.')
    elif args.live and unreported:
        print(f'Ready, but CodexBar did not report the email for {", ".join(unreported)}; '
              f'check it reads the account you expect. Start with: token-tv run{flag}')
    elif args.live:
        print(f'Ready: every account answered with the expected email. Start with: token-tv run{flag}')
    else:
        print(f'Files are in place, but logins are not verified. Check them with: token-tv doctor{flag} --live')
    return 0 if ready else 1


def demo(args):
    from PIL import Image
    from token_tv.display import STYLES, render_page
    from token_tv.sample import snapshot
    out = Path(args.out).expanduser()
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f'Could not create {out}: {error.strerror or error}', file=sys.stderr)
        return 1
    data = snapshot(time.time())
    for style in STYLES:
        image = render_page(data, style=style)
        kind = 'gif' if image[:4] == b'GIF8' else 'jpg' if image[:3] == b'\xff\xd8\xff' else 'png'
        name = out / f'demo-{style}.{kind}'
        name.write_bytes(image)
        if args.scale > 1 and kind != 'gif':
            big = Image.open(io.BytesIO(image)).resize((240 * args.scale,) * 2, Image.Resampling.NEAREST)
            big.save(out / f'demo-{style}@{args.scale}x.png')
        print(name)
    print('Sample data only (DEMO). Your real usage appears after setup, connect and run.')
    return 0


PORTS = range(8787, 8797)  # the dashboard's port: the first one free, when another program has 8787


def running(port):
    """Whether a TokenTV dashboard already answers on this port of this computer (in the background, say)."""
    from urllib.request import ProxyHandler, build_opener
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/display', timeout=2) as response:
            return 'styles' in json.loads(response.read(65536))
    except (OSError, ValueError, TypeError, HTTPException):  # nothing there, or another program (ssh, say)
        return False


def dashboard_port():
    """(port, True) where TokenTV already runs, else (the first free port, False), else (None, False)."""
    import socket
    for port in PORTS:  # a copy already running anywhere first, whichever port it took
        if running(port):
            return port, True
    for port in PORTS:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
        return port, False
    return None, False


def pick_clock(interactive):
    """The clock's address: found on this Wi-Fi, chosen when there are several, else asked; '' = dashboard only."""
    from token_tv.device import find_clocks
    print('Looking for your clock on this Wi-Fi...', flush=True)
    found = find_clocks()
    if len(found) == 1:
        print(f'Found a clock at {urlparse(found[0]).hostname}')
        return found[0]
    if found and interactive:
        for n, url in enumerate(found, 1):
            print(f'  {n}. {urlparse(url).hostname}')
        choice = ask('Which clock? Number', '1')
        return found[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(found) else found[0]
    if found:
        print(f'Found {len(found)} clocks; using {urlparse(found[0]).hostname} (pass --device-url to choose)')
        return found[0]
    if not interactive:
        print('No clock found on this Wi-Fi: the dashboard runs without one (pass --device-url to add it).')
        return ''
    print('No clock found on this Wi-Fi. Its address shows on the clock screen when it starts.')
    return ask('Clock address, e.g. 192.168.0.50 (blank = dashboard only)')


def start(args):
    """One command: find signed-in CLIs and the clock, write the config, keep it running, open the dashboard."""
    from token_tv.sources import logged_in_email
    port, already = dashboard_port()
    url = f'http://127.0.0.1:{port}'
    only = [p.strip().lower() for p in (args.only or '').split(',') if p.strip()]
    if set(only) - set(PROVIDERS):
        print(f'--only takes {", ".join(PROVIDERS)}', file=sys.stderr)
        return 1
    path = Path(args.config).expanduser()
    if already:
        if path.exists():
            config = read_config(path)
            if config is None or refuses_only(path, config, only):
                return 1
            if args.face and config.get('display_style') != args.face:
                show_face(port, args.face)
        print(f'TokenTV is already running on this computer: {url}')
        if only:
            from token_tv import autostart
            print(f'It reads its accounts when it starts: after changing them, restart it '
                  f'({autostart.how()} autostart off, then {autostart.how()} start).')
        if not args.no_browser:
            import webbrowser
            webbrowser.open(url)
        return 0
    if port is None:
        print(f'Ports {PORTS[0]}-{PORTS[-1]} are all taken on this computer; free one and run token-tv start again.',
              file=sys.stderr)
        return 1
    interactive = not args.yes and sys.stdin.isatty()
    existed = path.exists()
    if not existed:
        accounts = []
        for provider, (_, home, _, _) in PROVIDERS.items():
            if only and provider not in only:
                continue
            if not cli_path(provider) or login_state(provider, home) == 'no':
                continue
            email = logged_in_email(provider, home)
            if not email:
                continue
            if interactive and not ask(f'Found {provider.title()} signed in as {email}. Use it? [Y/n]', 'y').lower().startswith('y'):
                continue
            accounts.append({'key': f'{provider}_a', 'alias': f'{provider.upper()} A', 'provider': provider,
                             'email': email, 'source_home': home})
            print(f'{provider.title()}: {email}')
        if not accounts:
            wanted = ' or '.join(p.title() for p in only) if only else 'Claude, Codex or Grok'
            print(f'No signed-in {wanted} CLI found. Sign in to one (for example `codex`, then log in),\n'
                  'or look around first with: token-tv demo', file=sys.stderr)
            return 1
        device = args.device_url
        if device is None:
            device = pick_clock(interactive)
        if device and not device.startswith(('http://', 'https://')):
            device = 'http://' + device
        try:
            device = device and device_address(device)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        config = {'poll_seconds': 60, 'accounts': accounts, 'display_style': args.face or 'arcade'}
        if device:
            config['device_url'] = device
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'x') as handle:
            json.dump(config, handle, indent=2)
            handle.write('\n')
        print(f'Saved {path} (emails and paths only, no secrets).')
    config = read_config(path)
    if config is None:
        return 1
    if args.device_url and path.exists():
        # --device-url only fills a new config; say so rather than quietly using the saved clock.
        wanted = args.device_url if args.device_url.startswith(('http://', 'https://')) else 'http://' + args.device_url
        try:
            wanted = device_address(wanted)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        if wanted != config.get('device_url'):
            print(f'{path} already sets the clock to {config.get("device_url") or "none (dashboard only)"}, '
                  f'and --device-url is only used when that file is created.\n'
                  f'To use {wanted}, change device_url in that file, then run token-tv start again.', file=sys.stderr)
            return 1
    if existed and refuses_only(path, config, only):
        return 1
    if args.face and config.get('display_style') != args.face:  # the face picked on the web demo, kept from now on
        config['display_style'] = args.face
        path.write_text(json.dumps(config, indent=2) + '\n')
    from token_tv import autostart
    if interactive and autostart.status() == 'off' and \
            ask('Start TokenTV with this computer and keep it running? [Y/n]', 'y').lower().startswith('y'):
        try:
            print(autostart.install(path))
        except OSError as error:
            print(f'Could not set that up ({error}); running here instead (Ctrl+C to stop).')
        else:
            for _ in range(60):  # the background copy needs a moment to open its dashboard
                port, up = dashboard_port()
                if up:
                    break
                time.sleep(.5)
            if not up:
                print(f'The background copy has not opened its dashboard after 30 seconds. Check it with: '
                      f'{autostart.how()} autostart status (its log: {autostart.log_hint()})', file=sys.stderr)
                return 1
            url = f'http://127.0.0.1:{port}'
            if not args.no_browser:
                import webbrowser
                webbrowser.open(url)
            print(f'Dashboard: {url}')
            return 0
    if not args.no_browser:
        import threading
        import webbrowser
        threading.Timer(1.5, webbrowser.open, [url]).start()
    print(f'Dashboard: {url}  (Ctrl+C to stop)')
    from token_tv import live
    sys.argv = ['token-tv start', '--config', str(path), '--state-dir', str(path.parent / 'state'), '--port', str(port)]
    live.main()
    return 0


def refuses_only(path, config, only):
    """True, having said why, when a saved config shows services that --only leaves out: --only picks the services
    when the config is made; it never quietly drops accounts from one."""
    extra = sorted({a.get('provider') for a in config.get('accounts', [])} - set(only)) if only else []
    if extra:
        print(f'{path} already lists {", ".join(extra)} as well, and --only is only used when that file is made.\n'
              f'To keep only {", ".join(only)}, remove the others from that file (or move it away and run this '
              f'again), then run token-tv start.', file=sys.stderr)
    return bool(extra)


def show_face(port, face):
    """Switch the TokenTV running on this computer to `face`, as its dashboard's own button does."""
    from urllib.request import ProxyHandler, Request, build_opener
    request = Request(f'http://127.0.0.1:{port}/display/style', data=json.dumps({'style': face}).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        build_opener(ProxyHandler({})).open(request, timeout=5).close()
        print(f'The clock switches to {face}.')
    except (OSError, HTTPException):
        print(f'Could not switch the running TokenTV to {face}; pick it on its dashboard.', file=sys.stderr)


def autostart_command(args):
    from token_tv import autostart
    if args.action == 'on':
        if read_config(args.config) is None:
            return 1
        try:
            print(autostart.install(Path(args.config).expanduser()))
        except OSError as error:
            print(f'Could not set it up: {error}', file=sys.stderr)
            return 1
    elif args.action == 'off':
        try:
            print(autostart.remove())
        except OSError as error:
            print(f'Could not stop it: {error}. Nothing was removed; try again.', file=sys.stderr)
            return 1
    else:
        state = autostart.status()
        print({'on': 'TokenTV starts with this computer.', 'off': 'TokenTV does not start with this computer.',
               'other': 'Another program owns the TokenTV entry; TokenTV leaves it alone.'}[state])
    return 0


def passthrough(module, args, extra):
    sys.argv = [f'token-tv {args.command}', '--config', str(Path(args.config).expanduser()), *extra]
    if not {'-h', '--help'} & set(extra) and read_config(args.config) is None:
        return 1
    module.main()
    return 0


def main(argv=None):
    from token_tv.display import STYLES
    parser = argparse.ArgumentParser(prog='token-tv', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', metavar='command')
    config = argparse.ArgumentParser(add_help=False)
    config.add_argument('--config', default=default_config(), help='config path (default: %(default)s)')

    s = commands.add_parser('setup', parents=[config], help='write a config; never overwrites one')
    for provider in PROVIDERS:
        s.add_argument(f'--{provider}-email', action='append',
                       help=f'{provider.title()} account email; repeat for accounts B and C')
    s.add_argument('--isolate', action='store_true',
                   help='give every account its own login home instead of reusing your existing CLI login')
    s.add_argument('--device-url', help='clock address, e.g. http://192.168.0.50')
    s.add_argument('--yes', action='store_true', help='do not ask; use only the flags given')
    st = commands.add_parser('start', parents=[config], help='find your signed-in CLIs and the clock, and run')
    st.add_argument('--device-url', help='clock address, e.g. 192.168.0.50 (default: found on this Wi-Fi)')
    st.add_argument('--face', choices=STYLES, help='clock face (default: arcade)')
    st.add_argument('--only', metavar='SERVICES', help='only these, comma-separated: claude,codex,grok')
    st.add_argument('--yes', action='store_true', help='accept every signed-in account without asking')
    st.add_argument('--no-browser', action='store_true', help='do not open the dashboard in a browser')
    a = commands.add_parser('autostart', parents=[config], help='start TokenTV with this computer, or stop that')
    a.add_argument('action', choices=('on', 'off', 'status'))
    o = commands.add_parser('doctor', parents=[config], help='check CLIs and logins')
    o.add_argument('--live', action='store_true', help='ask each provider now and compare the email; the CLI may refresh an expired login; prints status only')
    d = commands.add_parser('demo', help='render every clock face with sample data')
    d.add_argument('--out', default='token-tv-demo', help='output folder (default: %(default)s)')
    d.add_argument('--scale', type=int, default=3, help='extra enlarged PNG copy (1 = none)')
    commands.add_parser('connect', parents=[config], help='log an account in with its official CLI',
                        add_help=False)
    commands.add_parser('run', parents=[config], help='start the dashboard and drive the clock',
                        add_help=False)

    args, extra = parser.parse_known_args(argv)
    if args.command in ('connect', 'run'):
        if args.command == 'run':
            from token_tv import live as module
            extra = extra or []
            state = Path(args.config).expanduser().parent / 'state'
            if '--state-dir' not in extra:
                extra += ['--state-dir', str(state)]
        else:
            from token_tv import connect as module
        return passthrough(module, args, extra)
    if extra:
        parser.error('unrecognized arguments: ' + ' '.join(extra))
    if args.command is None:
        parser.print_help()
        return 0
    return {'setup': setup, 'doctor': doctor, 'demo': demo, 'start': start,
            'autostart': autostart_command}[args.command](args)


if __name__ == '__main__':
    raise SystemExit(main())
