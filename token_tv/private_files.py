"""What TokenTV writes is for its user alone: its folders 0700 and its files 0600 from the moment they exist, not
chmod-ed after the content is in. Windows keeps per-user rights on the profile folders itself; the modes matter on
Linux and macOS."""
import os
from pathlib import Path

POSIX = os.name != 'nt'


def private_dir(path, close=True):
    """`path` as a folder only this user can open, made if missing (missing parents are made as usual). With
    `close`, one left open is closed too: for TokenTV's own folders (the state folder), never a folder someone chose
    to keep a config in."""
    path = Path(path)
    made = not path.is_dir()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if POSIX and (made or close):
        os.chmod(path, 0o700)
    return path


def write_bytes_to(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def write_private(path, data):
    """Write `data` (text as UTF-8, or bytes) to `path` through a temporary file beside it that is 0600 before its
    first byte, then give it the name: a crash mid-write keeps the old file, and neither is readable by others."""
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        if POSIX:
            os.fchmod(fd, 0o600)  # one left wide open by a crash is closed before anything is written to it
        write_bytes_to(fd, data.encode('utf-8') if isinstance(data, str) else data)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def create_private(path, text):
    """A new file at `path`, 0600 from the start, holding `text`; FileExistsError if one is there already (made
    meanwhile, say)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        write_bytes_to(fd, text.encode('utf-8'))
    finally:
        os.close(fd)


def open_private(path, mode='a+'):
    """`path` opened as open() would, made 0600 if it is new (a lock file)."""
    return os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600), mode, encoding='utf-8')
