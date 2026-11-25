"""Basic alias checks for explicitly selected migration database targets.

This does not prove that a file is disposable or bind SQLite's subsequently
opened file to this inspection. Operators must still use trusted isolation.
"""
from pathlib import Path
import stat


def checked_database_target(database):
    candidate = Path(database)
    info = candidate.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('A standalone regular database file is required')
    return candidate.resolve(strict=True)
