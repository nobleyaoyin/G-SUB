"""POSIX coordination primitive for explicitly participating operations.

Some HTTP and background operations participate when configured; this does not
protect writers that do not participate. All participants must use the same
trusted, private directory and cooperate.
The persistent flag fails closed after an interrupted maintenance owner. Never
remove or replace the lock files while processes may be using them.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


class MaintenanceActive(RuntimeError):
    pass


class MaintenanceBarrier:
    def __init__(self, directory):
        directory = Path(directory)
        if not directory.is_absolute() or directory.is_symlink():
            raise ValueError('Maintenance directory must be an absolute private directory')
        self.directory = directory

    def _open(self, name):
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0)
        directory_fd = os.open(self.directory, flags)
        try:
            info = os.fstat(directory_fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError('Maintenance directory must be private and owner-controlled')
            fd = os.open(name, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=directory_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                os.close(fd)
                raise ValueError('Unsafe maintenance lock file')
            return fd
        finally:
            os.close(directory_fd)

    @staticmethod
    def _state(gate):
        state = os.pread(gate, 2, 0)
        if state == b'':
            os.pwrite(gate, b'0', 0)
            os.fsync(gate)
            return b'0'
        if state not in (b'0', b'1'):
            raise RuntimeError('Invalid maintenance state')
        return state

    @staticmethod
    def _set_state(gate, state):
        if os.pwrite(gate, state, 0) != 1:
            raise OSError('Could not persist maintenance state')
        os.fsync(gate)

    @contextmanager
    def operation(self):
        gate = self._open('gate.lock')
        participant = None
        try:
            fcntl.flock(gate, fcntl.LOCK_EX)
            if self._state(gate) != b'0':
                raise MaintenanceActive('Maintenance is active')
            participant = self._open('participants.lock')
            fcntl.flock(participant, fcntl.LOCK_SH)
            fcntl.flock(gate, fcntl.LOCK_UN)
            yield
        finally:
            if participant is not None:
                os.close(participant)
            os.close(gate)

    @contextmanager
    def maintenance(self):
        gate = self._open('gate.lock')
        participant = None
        owner = None
        entered = False
        completed = False
        try:
            fcntl.flock(gate, fcntl.LOCK_EX)
            if self._state(gate) != b'0':
                raise MaintenanceActive('Maintenance is already active')
            owner = self._open('owner.lock')
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._set_state(gate, b'1')
            participant = self._open('participants.lock')
            fcntl.flock(gate, fcntl.LOCK_UN)
            fcntl.flock(participant, fcntl.LOCK_EX)
            entered = True
            yield
            completed = True
        finally:
            try:
                if entered and completed:
                    fcntl.flock(gate, fcntl.LOCK_EX)
                    self._set_state(gate, b'0')
            finally:
                if participant is not None:
                    os.close(participant)
                if owner is not None:
                    os.close(owner)
                os.close(gate)

    def recover_interrupted(self):
        """Clear the flag only when no cooperative operation holds the lock.

        Caller must independently authorize and verify that recovery is safe.
        """
        gate = self._open('gate.lock')
        participant = None
        owner = None
        try:
            fcntl.flock(gate, fcntl.LOCK_EX)
            if self._state(gate) != b'1':
                raise ValueError('Maintenance is not active')
            owner = self._open('owner.lock')
            try:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MaintenanceActive('Maintenance owner is still active') from None
            participant = self._open('participants.lock')
            try:
                fcntl.flock(participant, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MaintenanceActive('Operations are still active') from None
            self._set_state(gate, b'0')
        finally:
            if participant is not None:
                os.close(participant)
            if owner is not None:
                os.close(owner)
            os.close(gate)
