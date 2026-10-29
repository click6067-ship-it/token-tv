"""Start TokenTV with the computer and keep it running, so the clock does not stop when a terminal closes.

Linux: a systemd user service. macOS: a LaunchAgent. Windows: a hidden entry in the Startup folder. Each runs
`token-tv start --yes --no-browser` for one config. Only files TokenTV wrote are ever replaced or removed.
"""
import os
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

MARK = 'Written by token-tv autostart'
LABEL = 'io.github.click6067-ship-it.token-tv'


def how():
    """How this person runs TokenTV, for the commands TokenTV tells them: `npx token-tv`, `uvx token-tv` or
    `token-tv`."""
    prefix = Path(sys.prefix)
    if throwaway():
        return 'uvx token-tv'
    if prefix.name == 'venv' and prefix.parent.name == 'token-tv':  # the npx launcher's own copy
        return 'npx token-tv'
    return 'token-tv'


def throwaway():
    """Whether this is uvx's throwaway copy, which uv may clear."""
    parts = Path(sys.prefix).parts
    return 'uv' in parts and ('cache' in (p.lower() for p in parts) or any(p.startswith('archive-v') for p in parts))


def log_hint():
    _, kind = place()
    return {'systemd': 'journalctl --user -u token-tv', 'launchd': '~/Library/Logs/token-tv.log',
            'startup': 'none on Windows'}[kind]


def command(config):
    """How the computer starts TokenTV: this same Python (a pipx, pip or npx install keeps it), or uvx when this
    run is uvx's throwaway copy, which uv may clear."""
    tail = ['start', '--yes', '--no-browser', '--config', str(Path(config).expanduser().resolve())]
    if throwaway():
        uvx = shutil.which('uvx')
        if uvx:
            return [uvx, 'token-tv', *tail]
    python = Path(sys.executable)
    if sys.platform == 'win32' and (python.parent / 'pythonw.exe').exists():
        python = python.parent / 'pythonw.exe'  # no console window
    return [str(python), '-m', 'token_tv', *tail]


def place():
    """Where the entry lives on this computer, and its kind."""
    if sys.platform == 'darwin':
        return Path('~/Library/LaunchAgents').expanduser() / f'{LABEL}.plist', 'launchd'
    if sys.platform == 'win32':
        startup = Path(os.environ.get('APPDATA', '~')).expanduser() / 'Microsoft/Windows/Start Menu/Programs/Startup'
        return startup / 'TokenTV.vbs', 'startup'
    base = Path(os.environ.get('XDG_CONFIG_HOME') or '~/.config').expanduser()
    return base / 'systemd/user/token-tv.service', 'systemd'


def entry(argv, kind, path=None):
    """The text of the entry that runs `argv`. It keeps this terminal's PATH, where the Claude, Codex and Grok CLIs
    (and Node, for some) were found, and it starts again whenever it stops: a copy already running in a terminal
    makes it wait, and it takes over once that copy is closed."""
    path = os.environ.get('PATH', '') if path is None else path
    if kind == 'systemd':
        quoted = path.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
        return (f'# {MARK}\n[Unit]\nDescription=TokenTV desk clock\nAfter=network-online.target\n\n'
                f'[Service]\nEnvironment="PATH={quoted}"\nExecStart={shlex.join(argv).replace("%", "%%")}\n'
                f'Restart=always\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n')
    if kind == 'launchd':
        args = ''.join(f'<string>{xml(a)}</string>' for a in argv)
        log = xml(str(Path('~/Library/Logs/token-tv.log').expanduser()))
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!-- {MARK} -->\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST '
                f'1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
                f'<key>Label</key><string>{LABEL}</string><key>ProgramArguments</key><array>{args}</array>'
                f'<key>EnvironmentVariables</key><dict><key>PATH</key><string>{xml(path)}</string></dict>'
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
        'Do While files.FileExists(WScript.ScriptFullName)', f'  shell.Run "{line}", 0, True', '  WScript.Sleep 30000',
        'Loop', ''])


def xml(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def ours(path):
    try:
        return MARK in path.read_text(errors='replace')
    except OSError:
        return False


def run(argv):
    """A system tool's result; a missing or hung tool reads as a failure, not an exception of another kind."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(argv, 1, '', f'{argv[0]}: {error}')


def status():
    """'on', 'off' or 'other' (an entry by that name that TokenTV did not write)."""
    path, _ = place()
    return 'off' if not path.exists() else 'on' if ours(path) else 'other'


def install(config):
    """Write the entry and start TokenTV now. Returns a line to show, or raises OSError with the reason."""
    path, kind = place()
    if path.exists() and not ours(path):
        raise OSError(f'{path} exists and was not written by TokenTV; leaving it alone')
    argv = command(config)
    before = path.read_text() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry(argv, kind))

    def undo(reason):  # put back what was there, so a failed try is not taken for a working entry
        path.write_text(before) if before is not None else path.unlink()
        raise OSError(reason)
    if kind == 'systemd':
        for step in (['systemctl', '--user', 'daemon-reload'], ['systemctl', '--user', 'enable', '--now', path.name],
                     ['systemctl', '--user', 'restart', path.name]):
            done = run(step)
            if done.returncode:
                undo((done.stderr or done.stdout).strip() or 'systemctl failed')
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
    text = path.read_text(errors='replace')
    path.unlink()
    if kind == 'systemd':
        run(['systemctl', '--user', 'daemon-reload'])
    if kind == 'startup':  # the loop sees its file gone; the copy running now is ended by the number it left
        config = next((line.split(':', 1)[1].strip() for line in text.splitlines() if line.startswith("' config:")), '')
        pid_file = Path(config).parent / 'state' / 'live.pid' if config else None
        try:
            pid = int(pid_file.read_text())
            shown = run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH']).stdout.lower()
            if 'python' not in shown:  # that number now belongs to another program, or to nothing
                raise ValueError(pid)
            os.kill(pid, signal.SIGTERM)
        except (AttributeError, OSError, ValueError):
            return 'TokenTV no longer starts with this computer; end pythonw.exe in Task Manager to stop it now.'
    return 'TokenTV stopped and no longer starts with this computer.'
