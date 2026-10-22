"""Prevent two local watch processes from changing the same search state."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


def _lock(handle) -> None:
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def watch_locks(data_dir: Path, names: list[str]):
    """Lock each search in sorted order so overlapping watches fail safely."""
    handles = []
    try:
        for name in sorted(set(names)):
            directory = data_dir / name
            directory.mkdir(parents=True, exist_ok=True)
            handle = (directory / "watch.lock").open("a+b")
            try:
                _lock(handle)
            except OSError:
                handle.close()
                raise RuntimeError(f"Поиск «{name}» уже наблюдается другим процессом") from None
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles):
            handle.close()
