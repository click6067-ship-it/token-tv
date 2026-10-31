"""Start TokenTV with the computer and keep it running, so the clock does not stop when a terminal closes.

Linux: a systemd user service. macOS: a LaunchAgent. Windows: a hidden entry in the Startup folder. Each runs
`token-tv start --yes --no-browser` for one config. Only files TokenTV wrote are ever replaced or removed.
"""
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

MARK = 'Written by token-tv autostart'
LABEL = 'io.github.click6067-ship-it.token-tv'


def how():
    """How this person runs TokenTV, for the commands TokenTV tells them: `npx token-tv`, `uvx token-tv`,
    `token-tv`, or the full path of a venv's copy that is not on PATH."""
    prefix = Path(sys.prefix)
    if os.environ.get('TOKEN_TV_LAUNCHER') == 'npx' or (prefix.name == 'venv' and prefix.parent.name == 'token-tv'):
        return 'npx token-tv'
    if pipx_run():
        return 'pipx run token-tv'
    if throwaway():
        return 'uvx token-tv'
    if shutil.which('token-tv'):
        return 'token-tv'
    script = prefix / ('Scripts' if sys.platform == 'win32' else 'bin') / 'token-tv'
    return quoted(script) if script.exists() else f'{Path(sys.executable).name} -m token_tv'


def quoted(text):
    """`text` as one word for this person's shell: a path with a space in it stays one argument when pasted."""
    text = str(text)
    if sys.platform == 'win32':  # cmd and PowerShell both take double quotes
        return f'"{text}"' if any(c in text for c in ' \t&()[]{}^=;!\'+,`~$@#%') else text
    return shlex.quote(text)


def pipx_run():
    """Whether this is a `pipx run` copy, which pipx keeps in its cache for about two weeks."""
    parts = Path(sys.prefix).parts
    return 'pipx' in parts and '.cache' in parts


def throwaway():
    """Whether this is uvx's throwaway copy, which uv may clear."""
    parts = Path(sys.prefix).parts
    return 'uv' in parts and ('cache' in (p.lower() for p in parts) or any(p.startswith('archive-v') for p in parts))


def log_hint():
    _, kind = place()
    return {'systemd': 'journalctl --user -u token-tv', 'launchd': '~/Library/Logs/token-tv.log',
            'startup': 'none on Windows'}[kind]


def command(config, version=None):
    """How the computer starts TokenTV: this same Python (a pipx, pip or npx install keeps it), or uvx when this
    run is uvx's throwaway copy, which uv may clear. `version` (default: this one) for pipx run and uvx, which
    fetch a release; the others run what is installed."""
    from token_tv import __version__
    version = version or __version__
    tail = ['start', '--yes', '--no-browser', '--config', str(Path(config).expanduser().resolve())]
    if pipx_run() and shutil.which('pipx'):  # pipx fetches this release again when its cache has let it go
        return [shutil.which('pipx'), 'run', '--spec', f'token-tv=={version}', 'token-tv', *tail]
    if throwaway():
        uvx = own_uvx()
        if uvx:  # this release, not whatever is newest at the next boot
            return [uvx, f'token-tv@{version}', *tail]
    python = Path(sys.executable)
    if sys.platform == 'win32' and (python.parent / 'pythonw.exe').exists():
        python = python.parent / 'pythonw.exe'  # no console window
    return [str(python), '-m', 'token_tv', *tail]


def own_uvx():
    return os.environ.get('TOKEN_TV_UVX') or shutil.which('uvx')  # the npm launcher's own uv, if it fetched one


def pipx_venv():
    """Whether this copy is one `pipx install` keeps in its own venv."""
    parts = Path(sys.prefix).parts
    return 'pipx' in parts and 'venvs' in parts


def fetch_steps(version):
    """How this copy gets release `version`: the commands to run in order, the last printing the version that
    will run. uvx and pipx run fetch it; pip (and the npm launcher's venv) installs it over this one."""
    if pipx_run() and shutil.which('pipx'):
        return [[shutil.which('pipx'), 'run', '--spec', f'token-tv=={version}', 'token-tv', '--version']]
    if throwaway():
        uvx = own_uvx()
        if not uvx:
            raise OSError('uvx is not on PATH here, so TokenTV cannot fetch the new release')
        return [[uvx, f'token-tv@{version}', '--version']]
    check = [sys.executable, '-m', 'token_tv', '--version']
    if pipx_venv() and shutil.which('pipx'):
        return [[shutil.which('pipx'), 'install', '--force', f'token-tv=={version}'], check]
    return [[sys.executable, '-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', f'token-tv=={version}'], check]


def by_hand(version, tail='start'):
    """What to type to run release `version` in a terminal, the way this person runs TokenTV; `tail` the command
    and its options (start --config ...)."""
    if how() == 'npx token-tv':
        return f'npx token-tv@latest {tail}'
    if pipx_run():
        return f'pipx run --spec token-tv=={version} token-tv {tail}'
    if throwaway():
        return f'uvx token-tv@latest {tail}'
    return f'{quoted(sys.executable)} -m pip install --upgrade token-tv, then {how()} {tail}'


def entry_argv(path, kind):
    """The command the entry at `path` runs, as a list, or None."""
    try:
        text = read(path)
    except OSError:
        return None
    if kind == 'startup':  # shell.Run "<""a"" ""b"">", 0, True
        line = next((line.strip() for line in text.splitlines() if line.strip().startswith('shell.Run "')), '')
        inner = line[len('shell.Run "'):line.rfind('", 0')] if '", 0' in line else ''
        return re.findall(r'""(.*?)""', inner) or None
    if kind == 'launchd':
        import html
        array = text.split('<key>ProgramArguments</key>', 1)[-1].split('</array>', 1)[0]
        return [html.unescape(a) for a in re.findall(r'<string>(.*?)</string>', array)] or None
    line = next((line for line in text.splitlines() if line.startswith('ExecStart=')), '')
    try:
        return shlex.split(line[len('ExecStart='):].replace('%%', '%')) or None
    except ValueError:
        return None


def entry_config(path, kind):
    """The config the entry at `path` runs TokenTV for, or None."""
    if kind == 'startup':
        try:
            text = read(path)
        except OSError:
            return None
        return next((line.split(':', 1)[1].strip() for line in text.splitlines() if line.startswith("' config:")), None)
    argv = entry_argv(path, kind) or []
    return argv[argv.index('--config') + 1] if '--config' in argv[:-1] else None


def entry_path(path, kind):
    """The PATH the entry at `path` gives TokenTV (where the CLIs were found when it was set up), or None."""
    try:
        text = read(path)
    except OSError:
        return None
    if kind == 'startup':
        found = re.search(r'^shell\.Environment\("Process"\)\("PATH"\) = "(.*)"\s*$', text, re.M)
        return found.group(1).replace('""', '"') if found else None
    if kind == 'launchd':
        import html
        found = re.search(r'<key>PATH</key><string>(.*?)</string>', text)
        return html.unescape(found.group(1)) if found else None
    found = re.search(r'^Environment="PATH=(.*)"\s*$', text, re.M)
    return re.sub(r'\\(.)', r'\1', found.group(1)).replace('%%', '%') if found else None


def entry_version(argv):
    """The release an entry's command pins (uvx token-tv@X, pipx --spec token-tv==X), or None when it runs what is
    installed."""
    for arg in argv or ():
        found = re.fullmatch(r'token-tv(?:@|==)(\d+(?:\.\d+)*)', arg)
        if found:
            return found.group(1)
    return None


def place():
    """Where the entry lives on this computer, and its kind."""
    if sys.platform == 'darwin':
        return Path('~/Library/LaunchAgents').expanduser() / f'{LABEL}.plist', 'launchd'
    if sys.platform == 'win32':
        startup = Path(os.environ.get('APPDATA', '~')).expanduser() / 'Microsoft/Windows/Start Menu/Programs/Startup'
        return startup / 'TokenTV.vbs', 'startup'
    base = Path(os.environ.get('XDG_CONFIG_HOME') or '~/.config').expanduser()
    return base / 'systemd/user/token-tv.service', 'systemd'


def entry(argv, kind, path=None, launcher=None):
    """The text of the entry that runs `argv`. It keeps this terminal's PATH, where the Claude, Codex and Grok CLIs
    (and Node, for some) were found, and it starts again whenever it stops: a copy already running in a terminal
    makes it wait, and it takes over once that copy is closed. `launcher` 'npx' tells that copy it came from npx, so
    the commands it shows read `npx token-tv ...`."""
    path = os.environ.get('PATH', '') if path is None else path
    if kind == 'systemd':
        quoted = path.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
        npx = 'Environment="TOKEN_TV_LAUNCHER=npx"\n' if launcher == 'npx' else ''
        return (f'# {MARK}\n[Unit]\nDescription=TokenTV desk clock\nAfter=network-online.target\n\n'
                f'[Service]\nEnvironment="PATH={quoted}"\n{npx}ExecStart={shlex.join(argv).replace("%", "%%")}\n'
                f'Restart=always\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n')
    if kind == 'launchd':
        args = ''.join(f'<string>{xml(a)}</string>' for a in argv)
        log = xml(str(Path('~/Library/Logs/token-tv.log').expanduser()))
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!-- {MARK} -->\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST '
                f'1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
                f'<key>Label</key><string>{LABEL}</string><key>ProgramArguments</key><array>{args}</array>'
                f'<key>EnvironmentVariables</key><dict><key>PATH</key><string>{xml(path)}</string>'
                f'{"<key>TOKEN_TV_LAUNCHER</key><string>npx</string>" if launcher == "npx" else ""}</dict>'
                f'<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>30</integer>'
                f'<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>'
                f'</dict></plist>\n')
    # Windows: a hidden loop that runs TokenTV, waits for it to end, and runs it again until this file is gone.
    line = ' '.join('""' + a.replace('"', '') + '""' for a in argv)
    config = argv[argv.index('--config') + 1] if '--config' in argv else ''
    return '\r\n'.join([
        f"' {MARK}", f"' config: {config}",
        'Set shell = CreateObject("WScript.Shell")', 'Set files = CreateObject("Scripting.FileSystemObject")',
        f'shell.Environment("Process")("PATH") = "{path.replace(chr(34), chr(34) * 2)}"',
        *(['shell.Environment("Process")("TOKEN_TV_LAUNCHER") = "npx"'] if launcher == 'npx' else []),
        'Do While files.FileExists(WScript.ScriptFullName)', f'  shell.Run "{line}", 0, True', '  WScript.Sleep 30000',
        'Loop', ''])


def xml(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def read(path):
    data = path.read_bytes()
    return data.decode('utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8', errors='replace')


def ours(path):
    try:
        return MARK in read(path)
    except OSError:
        return False


def run(argv, timeout=60):
    """A system tool's result; a missing or hung tool reads as a failure, not an exception of another kind."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(argv, 1, '', f'{argv[0]}: {error}')


def status():
    """'on', 'off' or 'other' (an entry by that name that TokenTV did not write)."""
    path, _ = place()
    return 'off' if not path.exists() else 'on' if ours(path) else 'other'


def install(config, version=None, path_env=None, exact=None):
    """Write the entry and start TokenTV (release `version`, default this one) now, with `path_env` as its PATH
    (default: this terminal's); or put back `exact`, the bytes of an entry as it was. Returns a line to show, or
    raises OSError with the reason."""
    path, kind = place()
    if path.exists() and not ours(path):
        raise OSError(f'{path} exists and was not written by TokenTV; leaving it alone')
    before = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    if exact is not None:
        path.write_bytes(exact)
    else:
        # wscript reads a script as UTF-16 when it starts with a byte-order mark, else in the system's code page,
        # which cannot hold every user name in a path; systemd and launchd read UTF-8.
        launcher = 'npx' if how() == 'npx token-tv' else None  # the copy it starts writes its commands the same way
        path.write_text(entry(command(config, version), kind, path_env, launcher),
                        encoding='utf-16' if kind == 'startup' else 'utf-8')

    def undo(reason):  # put back what was there, so a failed try is not taken for a working entry
        path.write_bytes(before) if before is not None else path.unlink()
        raise OSError(reason)
    if kind == 'systemd':
        for step in (['systemctl', '--user', 'daemon-reload'], ['systemctl', '--user', 'enable', '--now', path.name],
                     ['systemctl', '--user', 'restart', path.name]):
            done = run(step)
            if done.returncode:
                undo((done.stderr or done.stdout).strip() or 'systemctl failed')
        # A user service stops when its user's last session ends, unless the user lingers: ask for that.
        if run(['loginctl', 'enable-linger']).returncode:
            return (f'TokenTV now runs in the background and starts when you log in (this system did not allow it '
                    f'to keep running after you log out). Stop it with: {how()} autostart off')
    elif kind == 'launchd':
        domain = f'gui/{os.getuid()}'
        run(['launchctl', 'bootout', domain, str(path)])
        done = run(['launchctl', 'bootstrap', domain, str(path)])
        if done.returncode:
            undo((done.stderr or done.stdout).strip() or 'launchctl failed')
    else:
        try:  # the same loop the next sign-in starts, started now
            subprocess.Popen(['wscript.exe', str(path)], creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0),
                             close_fds=True)
        except OSError as error:
            undo(str(error))
    return f'TokenTV now runs in the background and starts with this computer. Stop it with: {how()} autostart off'


def windows_args(line):
    """A Windows command line split into its arguments, as programs read them (quotes group, and go)."""
    args, word, quoted, any_ = [], [], False, False
    for char in line:
        if char == '"':
            quoted, any_ = not quoted, True
        elif char in ' \t' and not quoted:
            if word or any_:
                args.append(''.join(word))
            word, any_ = [], False
        else:
            word.append(char)
    if word or any_:
        args.append(''.join(word))
    return args


def runs_tokentv(pid, config):
    """Whether process `pid` is TokenTV started for `config`: its command line, as Windows reports it, runs token_tv
    (or the token-tv command) with exactly this --config. Anything else, or no answer, is not ours to end."""
    import ntpath
    asked = run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                 f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'])
    args = windows_args(asked.stdout.strip()) if asked.returncode == 0 else []
    names = [ntpath.basename(a).lower() for a in args]
    tokentv = 'token_tv' in names or any(n in ('token-tv', 'token-tv.exe') or n.startswith('token-tv@') for n in names)
    same = lambda path: ntpath.normcase(ntpath.normpath(path)) == ntpath.normcase(ntpath.normpath(config))
    return tokentv and any(a == '--config' and i + 1 < len(args) and same(args[i + 1]) for i, a in enumerate(args))


def remove():
    """Stop TokenTV and remove the entry. Returns a line to show; raises OSError, keeping the entry, if TokenTV
    could not be stopped (so `off` can be tried again)."""
    path, kind = place()
    if not path.exists():
        return 'TokenTV does not start with this computer.'
    if not ours(path):
        return f'{path} was not written by TokenTV; leaving it alone.'
    if kind == 'systemd':
        done = run(['systemctl', '--user', 'disable', '--now', path.name])
        if done.returncode:
            raise OSError((done.stderr or done.stdout).strip() or 'systemctl failed')
    elif kind == 'launchd':
        done = run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(path)])
        gone = 'No such process' in done.stderr or 'Could not find' in done.stderr  # already stopped
        if done.returncode and not gone:
            raise OSError((done.stderr or done.stdout).strip() or 'launchctl failed')
    text = read(path)
    path.unlink()
    if kind == 'systemd':
        run(['systemctl', '--user', 'daemon-reload'])
    if kind == 'startup':  # the loop sees its file gone; the copy running now is ended by the number it left
        config = next((line.split(':', 1)[1].strip() for line in text.splitlines() if line.startswith("' config:")), '')
        pid_file = Path(config).parent / 'state' / 'live.pid' if config else None
        try:
            pid = int(pid_file.read_text(encoding='utf-8'))
            if not runs_tokentv(pid, config):  # that number now belongs to another program, or to nothing
                raise ValueError(pid)
            os.kill(pid, signal.SIGTERM)
        except (AttributeError, OSError, ValueError):
            return 'TokenTV no longer starts with this computer; end pythonw.exe in Task Manager to stop it now.'
    return 'TokenTV stopped and no longer starts with this computer.'
