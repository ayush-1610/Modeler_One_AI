"""Atomic file writes: a concurrent reader sees the previous complete file or the new one, never a partial one.

The single-node tool writes JSON documents (``campaigns.json``, stage evidence, the package record) from the campaign
runner's thread while the API serves them. A plain ``write_text`` truncates the live file and then fills it, so a
reader can open it empty or half written (``JSONDecodeError: Expecting value``, seen in the T-56 kit test about 1 run
in 6). Every such write goes through here: the data goes to a temporary file in the same directory (so the final step
is a same-filesystem rename), is flushed and ``fsync``-ed, then ``os.replace`` swaps it in atomically.

`atomic_output` serves writers that are external programs (pandoc, typst): they write the temporary path, and it is
swapped in only when they succeed.

`file_lock` serializes a read-modify-write of one document across threads and processes (phase 8: two API workers, or
an agent job beside a request, upserting one collection would otherwise lose an update).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# The mode a plain open() would give a new file (0o666 minus the umask). mkstemp creates 0o600, which would make the
# replaced file unreadable to another user — read the umask once, at import, before any thread runs.
_UMASK = os.umask(0)
os.umask(_UMASK)
_FILE_MODE = 0o666 & ~_UMASK


def _fsync_dir(directory: Path) -> None:
    """Make the rename itself durable (best effort: not every platform lets a directory be opened)."""
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextlib.contextmanager
def atomic_output(path: str | Path) -> Iterator[Path]:
    """Yield a temporary path beside ``path``; when the block succeeds, fsync it and replace ``path`` with it. On an
    exception the temporary file is removed and ``path`` is left as it was."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        yield tmp
        with open(tmp, "rb+") as handle:
            os.fsync(handle.fileno())
        os.chmod(tmp, _FILE_MODE)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    _fsync_dir(target.parent)


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically (see the module docstring)."""
    with atomic_output(path) as tmp, open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Replace ``path`` with ``text`` atomically."""
    atomic_write_bytes(path, text.encode(encoding))


@contextlib.contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` (an ``flock`` on ``<path>.lock``) for the block, across threads and processes.

    Not reentrant: a block that already holds the lock on ``path`` must not take it again."""
    lock = Path(path)
    lock = lock.with_name(lock.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
