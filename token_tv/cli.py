"""token-tv: set up, check, preview and run TokenTV.

    token-tv start     find your signed-in CLIs and the clock, keep it running (the easy way)
    token-tv autostart  start with this computer (on), stop that (off), or check (status)
    token-tv add       add another account of a service (e.g. add codex), with its own login
    token-tv setup     write a credential-free config (never overwrites one)
    token-tv doctor    check CLIs and login files (--live asks each provider)
    token-tv demo      render every clock face with sample data
    token-tv connect   sign an account in with its official CLI
    token-tv run       start the dashboard and drive the clock
    token-tv update    put the newest release in the background copy's place
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from http.client import HTTPException
from urllib.parse import urlparse

from token_tv.private_files import create_private, private_dir, write_private

PROVIDERS = {
    # provider: (CLI command, default home, file the CLI writes after login, login hint)
    'claude': ('claude', '~/.claude', '.credentials.json', 'claude auth login'),
    'codex': ('codex', '~/.codex', 'auth.json', 'codex login'),
    'grok': ('grok', '~/.grok', 'auth.json', 'grok login'),
}


CODEXBAR = ('claude', 'codex', 'copilot', 'antigravity')  # what TokenTV reads through CodexBar, when it is installed


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
    shown = f' [{default}]' if default and not prompt.rstrip().endswith(']') else ''  # '[Y/n]' already shows it
    try:
        answer = input(f'{prompt}{shown}: ').strip()
    except EOFError:
        answer = ''
    return answer or default


CONFIG = None  # the config this run uses, when it is not the default one: commands TokenTV prints carry it


def cmd(rest):
    """A command to type, written the way this person runs TokenTV (npx, uvx, token-tv or a venv's path), with this
    run's --config when it is not the default."""
    from token_tv.autostart import how, quoted
    extra = f' --config {quoted(CONFIG)}' if CONFIG and str(Path(CONFIG).expanduser()) != default_config() else ''
    return f'{how()} {rest}{extra}'


def device_address(text):
    """'http://host[:port]' with the trailing slash removed, or ValueError with a fix."""
    url = urlparse(text.strip())
    if url.scheme not in ('http', 'https') or not url.hostname or url.path.strip('/') or url.query:
        raise ValueError(f'{text!r} is not a clock address; use the form http://192.168.0.50')
    try:
        url.port
    except ValueError:
        raise ValueError(f'{text!r} has an invalid port') from None
    return f'http://{url.netloc}'  # the clock speaks plain http, whatever was typed


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
        device = ask('\nClock address, e.g. 192.168.0.50 (blank for dashboard only)')
        try:
            device = device and device_address(device if device.startswith(('http://', 'https://')) else 'http://' + device)
        except ValueError as error:
            print(f'  {error}')
            device = None
    try:
        device = device and device_address(device if device.startswith(('http://', 'https://')) else 'http://' + device)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    config = {'poll_seconds': 60, 'accounts': accounts, 'display_style': 'arcade'}
    if device:
        config['device_url'] = device
    try:
        private_dir(path.parent, close=False)
        create_private(path, json.dumps(config, indent=2) + '\n')  # refuses to replace a file created meanwhile
    except OSError as error:
        print(f'Could not write {path}: {error.strerror or error}', file=sys.stderr)
        return 1
    print(f'Wrote {path} ({len(accounts)} account{"s" * (len(accounts) != 1)}; emails and paths only, no secrets).')
    for account in accounts:
        shared = account['source_home'] == PROVIDERS[account['provider']][1]
        print(f'  {account["alias"]:<9} {"reuses your existing CLI login" if shared else "separate login"} '
              f'in {account["source_home"]}')
    print(f'Next: {cmd("doctor")}   (separate logins need: {cmd("connect")} --account <key>)')
    return 0


def read_config(path):
    """The validated config, or None after printing a one-line reason."""
    from token_tv.sources import load_config
    path = Path(path).expanduser()
    if not path.is_file():
        print(f'No config at {path}. Run: {cmd("start")}', file=sys.stderr)
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
    ready = True
    unreported, failing = [], []
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
                if not good:
                    line += f' ({row.get("error_code") or row["status"]})'
                    failing.append((account, row))
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
                line += f' ({row.get("error_code") or ("identity_unverified" if row["status"] == "ok" else row["status"])})'
                line += f' -> {cmd("connect")} --account {account["key"]}' if found else ''
                failing.append((account, row))
        elif state == 'yes':
            line += 'login file present (not verified yet)'
        elif state == 'keychain':
            ready = False
            line += 'no login file; macOS Keychain unchecked (untested on real Macs) -> doctor --live'
        else:
            ready = False
            line += 'login MISSING' + (f' -> {cmd("connect")} --account {account["key"]}' if found else '')
        if not found:
            ready = False
            line += f'\n{"":<18}install the {provider} CLI, then log in ({PROVIDERS[provider][3]})'
        print(line)
    for account, row in failing:  # one line each, the same shape every time, for a canary to read: no emails
        code = row.get('error_code') or ('identity_unverified' if row['status'] == 'ok' else row['status'])
        print(f'failing: provider={account["provider"]} alias={json.dumps(account["alias"], ensure_ascii=False)} status={row["status"]} error_code={code}')
    print('Clock: ' + (config.get('device_url') or 'none (dashboard only)'))
    if not ready:
        print(f'Fix the lines above, then run {cmd("doctor")} again.')
    elif args.live and unreported:
        print(f'Ready, but CodexBar did not report the email for {", ".join(unreported)}; '
              f'check it reads the account you expect. Start with: {cmd("start")}')
    elif args.live:
        print(f'Ready: every account answered with the expected email. Start with: {cmd("start")}')
    else:
        print(f'Files are in place, but logins are not verified. Check them with: {cmd("doctor")} --live')
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
    from token_tv.autostart import how
    print(f'Sample data only (DEMO). For your own usage on your clock: {how()} start')
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
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as the dashboard's own server does
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
        print(f'No clock found on this Wi-Fi: the dashboard runs without one. Once the clock is on the Wi-Fi, run\n'
              f'{cmd("start")} again to find it, or give its address: {cmd("start --device-url 192.168.0.50")}')
        return ''
    print('No clock found on this Wi-Fi. Its address shows on the clock screen when it starts.')
    return ask('Clock address, e.g. 192.168.0.50 (blank = dashboard only)')


def clock_now(path, config, interactive):
    """A config made without a clock, started again by hand: look for the clock now and keep the one chosen. Never
    on its own (`--yes`, as the computer starts it): a lone clock on a shared Wi-Fi may be someone else's."""
    if config.get('device_url') or not interactive:
        return True
    found = pick_clock(interactive)
    return not found or save_clock(path, config, found) is not None


def start(args):
    """One command: find signed-in CLIs and the clock, write the config, keep it running, open the dashboard."""
    from token_tv.sources import logged_in_email
    port, already = dashboard_port()
    url = f'http://127.0.0.1:{port}'
    only = [p.strip().lower() for p in (args.only or '').split(',') if p.strip()]
    if set(only) - set(PROVIDERS) - set(CODEXBAR):
        print(f'--only takes {", ".join(dict.fromkeys([*PROVIDERS, *CODEXBAR]))}', file=sys.stderr)
        return 1
    path = Path(args.config).expanduser()
    if already:
        if path.exists():
            config = read_config(path)
            if config is None or refuses_only(path, config, only):
                return 1
            if args.face and config.get('display_style') != args.face:
                show_face(port, args.face)
            if args.device_url and save_clock(path, config, args.device_url) is None:
                return 1
            if not args.device_url and not clock_now(path, config, not args.yes and sys.stdin.isatty()):
                return 1
        print(f'TokenTV is already running on this computer: {url}')
        if only:
            print(f'It reads its accounts when it starts: after changing them, restart it (Ctrl+C where it runs, '
                  f'or {cmd("autostart off")} then {cmd("autostart on")} if it starts with the computer).')
        if not args.no_browser:
            import webbrowser
            webbrowser.open(url)
        return 0
    if port is None:
        print(f'Ports {PORTS[0]}-{PORTS[-1]} are all taken on this computer; free one and run {cmd("start")} again.',
              file=sys.stderr)
        return 1
    interactive = not args.yes and sys.stdin.isatty()
    existed = path.exists()
    if not existed:
        accounts, reasons = [], []
        for provider, (_, home, _, hint) in PROVIDERS.items():
            if only and provider not in only:
                continue
            if not cli_path(provider):
                reasons.append(f'{provider.title()}: not installed')
                continue
            if login_state(provider, home) == 'no':
                reasons.append(f'{provider.title()}: installed, not signed in ({hint})')
                continue
            why = []
            email = logged_in_email(provider, home, why)
            if not email:
                reasons.append(f'{provider.title()}: ' + {
                    'refused': f'signed in, but the saved login was refused (expired?); open `{PROVIDERS[provider][0]}` once',
                    'busy': 'signed in, but the service asked to wait; try again in a minute',
                    'offline': 'signed in, but the service could not be reached; check the internet connection',
                    'not_chatgpt': 'signed in with an API key; TokenTV reads a ChatGPT sign-in (`codex login`)',
                }.get(why[0] if why else '', f'signed in, but its login could not be read; open `{PROVIDERS[provider][0]}` once'))
                continue
            if interactive and not ask(f'Found {provider.title()} signed in as {email}. Use it? [Y/n]', 'y').lower().startswith('y'):
                continue
            accounts.append({'key': f'{provider}_a', 'alias': f'{provider.upper()} A', 'provider': provider,
                             'email': email, 'source_home': home})
            print(f'{provider.title()}: {email}')
        accounts += codexbar_accounts(only, {a['provider'] for a in accounts}, interactive)
        if not accounts:
            wanted = ' or '.join(p.title() for p in only) if only else 'Claude, Codex or Grok'
            guides = {'claude': '  Claude Code: install it (https://code.claude.com/docs/en/quickstart), run `claude` and log in\n',
                      'codex': '  Codex:       npm install -g @openai/codex, then run `codex login`\n',
                      'grok': '  Grok:        install the Grok CLI, then run `grok login`\n',
                      'copilot': '  Copilot:     install CodexBar and sign it in (docs/codexbar.md)\n',
                      'antigravity': '  Antigravity: install CodexBar and sign it in (docs/codexbar.md)\n'}
            codexbar = ('  CodexBar: installed, but it reported no signed-in account (`codexbar usage --format json` '
                        'shows why)\n' if shutil.which('codexbar') else
                        '  Claude in the browser only, on a Mac: CodexBar can read it for TokenTV (experimental):\n'
                        '    brew install --cask codexbar, open it, Settings > Advanced > Install CLI, then\n'
                        '    codexbar cookie refresh --provider claude --allow-keychain-prompt (docs/codexbar.md)\n'
                        if sys.platform == 'darwin' and (not only or 'claude' in only) else '')
            print(f'No signed-in {wanted} CLI found on this computer:\n' + ''.join(f'  {r}\n' for r in reasons) +
                  'TokenTV reads your limits through the official command-line tools; signing in on claude.ai or\n'
                  'chatgpt.com in a browser is not enough.\n' +
                  ''.join(guides[p] for p in (only or ('claude', 'codex'))) + codexbar +
                  f'Then run this again. To see the faces first: {cmd("demo")}', file=sys.stderr)
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
        private_dir(path.parent, close=False)
        create_private(path, json.dumps(config, indent=2) + '\n')
        print(f'Saved {path} (emails and paths only, no secrets).')
    config = read_config(path)
    if config is None:
        return 1
    if existed and args.device_url and save_clock(path, config, args.device_url) is None:
        return 1
    if existed and not args.device_url and not clock_now(path, config, interactive):
        return 1
    if existed and refuses_only(path, config, only):
        return 1
    if args.face and config.get('display_style') != args.face:  # the face picked on the web demo, kept from now on
        config['display_style'] = args.face
        update_config(path, display_style=args.face)
    if config.get('device_url'):
        say_clock(config['device_url'])
    from token_tv import autostart
    if interactive and not existed and autostart.status() == 'off' and \
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


def say_clock(url):
    """The clock's model and firmware, as the clock says them; for a pair not checked yet, where to report how it
    goes. Nothing when it does not answer: a model is never made up."""
    from token_tv import device
    info = device.clock_info(url)
    if not info:
        return
    print(f'Clock: {info["model"]}, firmware {info["firmware"] or "not reported by the clock"}')
    if not device.verified(info):
        print(f'This clock and firmware are not checked with TokenTV yet. Tell us how it goes (no Wi-Fi names or '
              f'passwords): {device.REPORT_URL}')


def codexbar_accounts(only, have, interactive):
    """Accounts CodexBar reads on this computer, for the services no official CLI gave: how `start` sets up a
    CodexBar user, and the only way to Copilot and Antigravity. CodexBar keeps the logins; TokenTV reads its JSON."""
    from concurrent.futures import ThreadPoolExecutor
    from token_tv.sources import SourceError, codexbar_emails, codexbar_payload
    wanted = [p for p in CODEXBAR if p not in have and (p in only if only else True)]
    if not wanted or not shutil.which('codexbar'):
        return []

    def ask_codexbar(provider):
        account = {'provider': provider, 'codexbar_command': 'codexbar'}
        if provider == 'claude' and sys.platform != 'darwin':
            account['codexbar_source'] = 'oauth'  # its default fails on Linux; on a Mac it reads the browser first
        try:
            data = codexbar_payload(account)
        except (SourceError, OSError, subprocess.SubprocessError):
            return None
        found = [e for e in data if isinstance(e, dict) and e.get('provider') == provider and isinstance(e.get('usage'), dict)
                 and not e.get('error')] if isinstance(data, list) else []
        return (account, (codexbar_emails(found[0]) or [''])[0]) if found else None
    print('Asking CodexBar...')
    with ThreadPoolExecutor(len(wanted)) as pool:
        answers = [answer for answer in pool.map(ask_codexbar, wanted) if answer]
    accounts = []
    for account, email in answers:
        provider = account['provider']
        name = 'Antigravity' if provider == 'antigravity' else provider.title()
        seen = f' as {email}' if email else ''
        if interactive and not ask(f'Found {name} through CodexBar{seen}. Use it? [Y/n]', 'y').lower().startswith('y'):
            continue
        # CodexBar reports no email for some services: then there is none to check, and the config says so.
        accounts.append({'key': f'{provider}_a', 'alias': 'ANTI A' if provider == 'antigravity' else f'{provider.upper()} A',
                         'email': email or 'not reported by CodexBar', **account})
        print(f'{name}: through CodexBar{seen}')
    return accounts


def save_clock(path, config, address):
    """Keep the clock address given on the command line in the config, saying so; a running TokenTV takes it up
    within a minute. None, having said why, when it is not an address."""
    wanted = address if address.startswith(('http://', 'https://')) else 'http://' + address
    try:
        wanted = device_address(wanted)
    except ValueError as error:
        print(error, file=sys.stderr)
        return None
    if wanted != config.get('device_url'):
        config['device_url'] = wanted
        update_config(path, device_url=wanted)
        print(f'The clock is at {wanted} from now on (saved in {path}).')
    return wanted


def update_config(path, **changes):
    """Write these keys into the config as it is on disk now: a running TokenTV may have just saved another key
    (the face picked on its dashboard, say), and an older copy here must not undo it."""
    current = json.loads(path.read_text(encoding='utf-8'))
    current.update(changes)
    write_private(path, json.dumps(current, indent=2) + '\n')


def refuses_only(path, config, only):
    """True, having said why, when a saved config shows services that --only leaves out: --only picks the services
    when the config is made; it never quietly drops accounts from one."""
    extra = sorted({a.get('provider') for a in config.get('accounts', [])} - set(only)) if only else []
    if extra:
        print(f'{path} already lists {", ".join(extra)} as well, and --only is only used when that file is made.\n'
              f'To keep only {", ".join(only)}, remove the others from that file (or move it away and run this '
              f'again), then run {cmd("start")}.', file=sys.stderr)
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


def add(args):
    """Add another account of one service to the config, with a login of its own, and sign it in."""
    path = Path(args.config).expanduser()
    config = read_config(path)
    if config is None:
        return 1
    keys = {a['key'] for a in config.get('accounts', [])}
    letter = next((l for l in 'ABCDE' if f'{args.provider}_{l.lower()}' not in keys), None)
    if letter is None:
        print(f'{path} already has five {args.provider} accounts.', file=sys.stderr)
        return 1
    email = args.email or (ask(f'{args.provider.title()} account {letter}: its email') if sys.stdin.isatty() else '')
    if '@' not in email:
        print(f'Give the account\'s email: {cmd(f"add {args.provider} --email you@example.com")}', file=sys.stderr)
        return 1
    key = f'{args.provider}_{letter.lower()}'
    config.setdefault('accounts', []).append({
        'key': key, 'alias': f'{args.provider.upper()} {letter}', 'provider': args.provider, 'email': email,
        'source_home': str(path.parent / 'homes' / key)})  # its own login; the everyday one stays as it is
    write_private(path, json.dumps(config, indent=2) + '\n')
    print(f'Added {args.provider.upper()} {letter} ({email}) to {path}.')
    if args.no_login:
        print(f'Sign it in later with: {cmd(f"connect --account {key}")}')
    else:
        from token_tv import connect
        sys.argv = ['token-tv connect', '--config', str(path), '--account', key]
        try:
            connect.main()
        except SystemExit as stop:
            if stop.code not in (0, None):
                print(f'Not signed in yet; try again with: {cmd(f"connect --account {key}")}', file=sys.stderr)
                return 1
    print(f'A TokenTV already running shows it after a restart (Ctrl+C where it runs, or {cmd("autostart off")} '
          f'then {cmd("autostart on")}).')
    return 0


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


def running_version(port):
    """The release of the TokenTV whose dashboard answers on this port of this computer, or None."""
    from urllib.request import ProxyHandler, build_opener
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            version = json.loads(response.read(65536)).get('version')
    except (OSError, ValueError, TypeError, AttributeError, HTTPException):
        return None
    return version if isinstance(version, str) else None


def update(args):
    """Stop the background copy, register it again with the newest release on PyPI and start it; the config and the
    logins are left as they are. The copy that runs is what is compared, not this one: `npx token-tv@latest update`
    is the newest itself while the background copy may not be. A TokenTV running in a terminal is told what to type
    instead."""
    from token_tv import __version__, autostart
    from token_tv import update as releases
    try:
        latest = releases.newest()
    except (OSError, ValueError, HTTPException):
        latest = None
    if not latest:
        print('Could not read the newest release from PyPI; nothing was changed. Try again later.', file=sys.stderr)
        return 1
    path = Path(args.config).expanduser()
    tail = 'start' + (f' --config {autostart.quoted(path)}' if str(path) != default_config() else '')
    state = autostart.status()
    if state == 'other':
        place, _ = autostart.place()
        print(f'{place} was not written by TokenTV; leaving it alone. TokenTV {latest} is out: '
              f'{autostart.by_hand(latest, tail)}', file=sys.stderr)
        return 1
    if state == 'off':
        port, here = dashboard_port()
        running = running_version(port) if here else __version__
        if running and not releases.newer(latest, running):
            print(f'TokenTV {running} is the newest release; nothing to do.')
            return 0
        where = 'TokenTV runs in a terminal here: stop it there (Ctrl+C), then run' if here else 'Start it with'
        print(f'TokenTV {latest} is out (this is {running or "an older one"}). {where}: {autostart.by_hand(latest, tail)}')
        return 0
    place, kind = autostart.place()
    before, saved = autostart.entry_argv(place, kind), place.read_bytes()
    config = autostart.entry_config(place, kind) or str(path)
    path_env = autostart.entry_path(place, kind)  # where the CLIs were found when it was set up, kept
    port, here = dashboard_port()
    running = autostart.entry_version(before) or (running_version(port) if here else None)
    if running and not releases.newer(latest, running):
        print(f'The background copy runs TokenTV {running}, the newest release; nothing to do.')
        return 0
    try:
        steps = autostart.fetch_steps(latest)
        autostart.remove()  # the background copy stops first, so nothing it has open is replaced under it
    except OSError as error:
        print(f'Could not stop the background copy: {error}. Nothing was changed.', file=sys.stderr)
        return 1
    stopped = time.monotonic()
    print(f'Fetching TokenTV {latest}...', flush=True)
    for step in steps:
        done = autostart.run(step, timeout=900)
        if done.returncode:
            break
    good = not done.returncode and f'token-tv {latest}' in (done.stdout or '')
    if kind == 'startup':  # Windows: the old loop sleeps 30 s after its copy ends, then ends itself if its file is gone
        wait = 32 - (time.monotonic() - stopped)
        if wait > 0:
            print('Waiting for the old background loop to end...', flush=True)
            time.sleep(wait)
    try:
        if not good:  # what ran before runs again, exactly as it was
            autostart.install(config, exact=saved)
            print(f'Could not get TokenTV {latest} ({(done.stderr or done.stdout or "no version printed").strip()[:200]}); '
                  f'the background copy runs {running or "its previous release"} again.', file=sys.stderr)
            return 1
        autostart.install(config, latest, path_env)
    except OSError as error:
        print(f'Could not start the background copy again ({error}). Start it with: {cmd("autostart on")}', file=sys.stderr)
        return 1
    print(f'TokenTV {latest} now runs in the background (was {running or "an older copy"}), for {config}; the config '
          f'and the logins are as they were.')
    return 0


def passthrough(module, args, extra):
    sys.argv = [f'token-tv {args.command}', '--config', str(Path(args.config).expanduser()), *extra]
    if not {'-h', '--help'} & set(extra) and read_config(args.config) is None:
        return 1
    module.main()
    return 0


def main(argv=None):
    from token_tv.display import STYLES
    from token_tv import __version__
    parser = argparse.ArgumentParser(prog='token-tv', description=__doc__,
                                     formatter_class=lambda prog: argparse.RawDescriptionHelpFormatter(prog, max_help_position=30))
    parser.add_argument('--version', action='version', version=f'token-tv {__version__}')
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
    ad = commands.add_parser('add', parents=[config], help='add another account of a service, with its own login')
    ad.add_argument('provider', choices=tuple(PROVIDERS))
    ad.add_argument('--email', help="the account's email")
    ad.add_argument('--no-login', action='store_true', help='only add it to the config; sign in later with connect')
    a = commands.add_parser('autostart', parents=[config], help='start TokenTV with this computer, or stop that')
    a.add_argument('action', choices=('on', 'off', 'status'))
    o = commands.add_parser('doctor', parents=[config], help='check CLIs and logins')
    o.add_argument('--live', action='store_true', help='ask each provider now and compare the email; the CLI may refresh an expired login; prints status only')
    d = commands.add_parser('demo', help='render every clock face with sample data')
    d.add_argument('--out', default='token-tv-demo', help='output folder (default: %(default)s)')
    d.add_argument('--scale', type=int, default=3, help='extra enlarged PNG copy (1 = none)')
    commands.add_parser('update', parents=[config], help="put the newest release in the background copy's place")
    commands.add_parser('connect', parents=[config], help='log an account in with its official CLI',
                        add_help=False)
    commands.add_parser('run', parents=[config], help='start the dashboard and drive the clock',
                        add_help=False)

    args, extra = parser.parse_known_args(argv)
    global CONFIG
    CONFIG = getattr(args, 'config', None)
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
    return {'setup': setup, 'doctor': doctor, 'demo': demo, 'start': start, 'add': add,
            'autostart': autostart_command, 'update': update}[args.command](args)


def entry():
    """The installed `token-tv` command: Ctrl+C at a question stops quietly."""
    try:
        return main()
    except KeyboardInterrupt:
        print('\nStopped.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(entry())
