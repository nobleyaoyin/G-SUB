"""Isolated, immutable byte storage for development samples.

This primitive is not an authorization service. Callers must independently
authorize the manuscript and operation before using it. Sample-document,
initial-editing and stage-artifact workflows use this storage through their
respective ledger helpers.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from app.config import DATA_ROOT, IS_DEMO

MAX_SAMPLE_BYTES = 10 * 1024 * 1024
_KINDS = frozenset({"manuscripts", "initial_editing", "final_editing", "formatting", "reviewed", "onlyoffice", "snapshots"})
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
_EXTENSIONS = frozenset({".pdf", ".docx", ".doc", ".txt"})
_PREFIX = "sample:v1/"


class SampleStorageError(ValueError):
    """Invalid storage identity, configuration, or content."""


def _parts(identity: str) -> tuple[str, str, str]:
    if not isinstance(identity, str) or not identity.startswith(_PREFIX):
        raise SampleStorageError("Invalid sample storage identity")
    parts = identity[len(_PREFIX):].split("/")
    if len(parts) != 3:
        raise SampleStorageError("Invalid sample storage identity")
    kind, manuscript_id, name = parts
    if (kind not in _KINDS or not manuscript_id.isascii() or not manuscript_id.isdecimal()
            or manuscript_id.startswith("0") or len(manuscript_id) > 18
            or not _FILE.fullmatch(name) or ".." in name
            or Path(name).suffix.lower() not in _EXTENSIONS):
        raise SampleStorageError("Invalid sample storage identity")
    return kind, manuscript_id, name


class SampleStorage:
    """Store server-generated sample identities in one private fixed root."""

    def __init__(self, root: Path, legacy_uploads: Path):
        self.root = Path(root)
        legacy = Path(legacy_uploads)
        if not self.root.is_absolute() or not legacy.is_absolute() or self.root.is_symlink() or legacy.is_symlink():
            raise SampleStorageError("Unsafe sample storage configuration")
        resolved, old = self.root.resolve(), legacy.resolve()
        if resolved == old or resolved.is_relative_to(old) or old.is_relative_to(resolved):
            raise SampleStorageError("Sample and legacy storage must not overlap")
        self.root = resolved
        self.legacy_uploads = legacy

    @classmethod
    def for_development(cls) -> "SampleStorage":
        if IS_DEMO:
            raise SampleStorageError("Sample storage is unavailable in this mode")
        return cls(DATA_ROOT / ".gsub_sample_storage", DATA_ROOT / "uploads")

    def _root_fd(self, create: bool) -> int:
        if create:
            try:
                os.mkdir(self.root, 0o700)
            except FileExistsError:
                pass
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.root, flags)
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            os.close(fd)
            raise SampleStorageError("Sample storage must be private and owner-controlled")
        return fd

    def _parent_fd(self, parts: tuple[str, str, str], create: bool) -> int:
        fd = self._root_fd(create)
        try:
            for part in parts[:2]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                new_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            return fd
        except Exception:
            os.close(fd)
            raise

    def write_new(self, identity: str, data: bytes) -> str:
        """Create a new immutable file and return its SHA-256 digest."""
        # Recheck at each write: configuration or either root may have changed
        # since this instance was constructed.
        if self.root.is_symlink() or self.legacy_uploads.is_symlink():
            raise SampleStorageError("Unsafe sample storage configuration")
        resolved, legacy = self.root.resolve(), self.legacy_uploads.resolve()
        if resolved != self.root or resolved == legacy or resolved.is_relative_to(legacy) or legacy.is_relative_to(resolved):
            raise SampleStorageError("Sample and legacy storage must not overlap")
        parts = _parts(identity)
        if not isinstance(data, bytes) or not data or len(data) > MAX_SAMPLE_BYTES:
            raise SampleStorageError("Invalid sample document size")
        parent = self._parent_fd(parts, create=True)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            # The caller records the identity only after this completes. A failed
            # write stays unreferenced; it must not be deleted on an uncertain
            # transaction outcome or overwrite any existing historical file.
            fd = os.open(parts[2], flags, 0o600, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(parent)
        return hashlib.sha256(data).hexdigest()

    def read(self, identity: str, *, digest: str) -> bytes:
        """Read bounded sample bytes and verify a caller-supplied trusted digest."""
        parts = _parts(identity)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SampleStorageError("Invalid sample document digest")
        parent = self._parent_fd(parts, create=False)
        try:
            fd = os.open(parts[2], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_size > MAX_SAMPLE_BYTES):
                    raise SampleStorageError("Invalid sample document")
                data = stream.read(MAX_SAMPLE_BYTES + 1)
        finally:
            os.close(parent)
        if len(data) > MAX_SAMPLE_BYTES or hashlib.sha256(data).hexdigest() != digest:
            raise SampleStorageError("Sample document integrity check failed")
        return data
