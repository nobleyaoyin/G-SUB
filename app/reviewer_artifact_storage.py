"""Disconnected private artifact storage. No routes, DB writes or startup hooks.

The operator must supply an existing, application-owned private directory that
is not reachable by any static server. This module cannot inspect all deployment
mounts or protect against a privileged process modifying private files.
Validation checks structure only; it does not establish anonymity or safety.
"""
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from fastapi import HTTPException
from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file


class StorageError(ValueError):
    """Invalid or unavailable storage object; contains no document contents."""


class PublicationOutcomeUnknown(StorageError):
    """Publication may have succeeded; reconcile before any cleanup or retry."""

    def __init__(self, storage_id):
        self.storage_id = storage_id
        super().__init__('Artifact publication outcome is unknown')


@dataclass(frozen=True)
class StorageMetadata:
    storage_id: str
    sha256: str
    byte_size: int
    format: str


_ID = re.compile(r'^[0-9a-f]{32}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')
_FORMATS = frozenset(('pdf', 'docx', 'doc', 'txt'))
_FORBIDDEN_DIRS = frozenset(('public', 'static', 'dist', 'frontend', 'uploads'))


def _validate_format(fmt, content):
    if not isinstance(fmt, str) or fmt not in _FORMATS or not isinstance(content, bytes):
        raise StorageError('Unsupported artifact format or content')
    try:
        validate_manuscript_file('artifact.' + fmt, content)
    except HTTPException as error:
        raise StorageError('Artifact format or size is invalid') from error


def _check_expected(expected_sha256, expected_size, fmt):
    if not isinstance(expected_sha256, str) or not _SHA.fullmatch(expected_sha256):
        raise StorageError('Invalid expected digest')
    if type(expected_size) is not int or not 0 < expected_size <= MAX_MANUSCRIPT_FILE_SIZE or not isinstance(fmt, str) or fmt not in _FORMATS:
        raise StorageError('Invalid expected metadata')


def _snapshot_fd(fd, expected_size):
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size:
            raise StorageError('File unavailable or size mismatch')
        chunks, offset = [], 0
        while offset < expected_size:
            data = os.pread(fd, min(65536, expected_size - offset), offset)
            if not data: raise StorageError('File changed or was truncated')
            chunks.append(data); offset += len(data)
        if os.fstat(fd).st_size != expected_size:
            raise StorageError('File changed or size mismatch')
        return b''.join(chunks)
    except OSError as error:
        raise StorageError('File unavailable') from error


def inspect_source_fd(fd, fmt):
    """Return actual digest, length and snapshot of an already-open source.

    A digest computed here is not evidence of an earlier approval. The caller
    must authorize and safely open the descriptor; this function owns no path.
    """
    try: size = os.fstat(fd).st_size
    except OSError as error: raise StorageError('File unavailable') from error
    if not 0 < size <= MAX_MANUSCRIPT_FILE_SIZE: raise StorageError('File unavailable or size mismatch')
    content = _snapshot_fd(fd, size)
    _validate_format(fmt, content)
    return hashlib.sha256(content).hexdigest(), size, content


def read_verified_fd(fd, expected_sha256, expected_size, fmt):
    """Return the exact verified bounded snapshot from an already-open file.

    The caller must safely open and authorize source descriptors. No pathname is
    opened here and the caller owns fd; no subsequent reopen occurs.
    """
    _check_expected(expected_sha256, expected_size, fmt)
    content = _snapshot_fd(fd, expected_size)
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256):
        raise StorageError('File integrity check failed')
    _validate_format(fmt, content)
    return content


def _open_private_directory(root):
    if not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'pread')):
        raise StorageError('Required filesystem protections unavailable')
    path = Path(root)
    if not path.is_absolute() or '..' in path.parts or any(part.lower() in _FORBIDDEN_DIRS for part in path.parts):
        raise StorageError('An existing private storage directory is required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = next_fd
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise StorageError('Storage directory must be private and owned by the application user')
        return fd
    except Exception:
        os.close(fd)
        raise


class ArtifactStorage:
    """Explicitly invoked storage with a trusted pre-provisioned directory."""

    @staticmethod
    def new_storage_id():
        """Generate an opaque ID; the caller must persist its reservation."""
        return uuid4().hex

    def __init__(self, root):
        try: self._dir = _open_private_directory(root)
        except OSError as error: raise StorageError('Private storage directory unavailable') from error

    def close(self):
        if self._dir is not None:
            os.close(self._dir); self._dir = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def _require_open(self):
        if self._dir is None: raise StorageError('Storage is closed')
        return self._dir

    def inspect_entries(self, limit=10000):
        """List private entry names/types without opening, modifying, or deleting them."""
        if type(limit) is not int or not 0 < limit <= 10000:
            raise StorageError('Invalid inventory limit')
        entries = {}
        try:
            with os.scandir(self._require_open()) as iterator:
                for entry in iterator:
                    if len(entries) >= limit:
                        raise StorageError('Inventory limit exceeded')
                    info = entry.stat(follow_symlinks=False)
                    entries[entry.name] = 'regular' if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 else 'unsafe'
            return entries
        except OSError as error:
            raise StorageError('Storage inventory unavailable') from error

    def publish_reserved(self, storage_id, content, fmt):
        """Publish a server-reserved ID. Caller must durably reserve it first.

        This primitive does not authenticate a caller or verify DB reservation.
        Uncertain published/staging files are retained for reconciliation.
        """
        directory = self._require_open()
        if not isinstance(storage_id, str) or not _ID.fullmatch(storage_id):
            raise StorageError('Invalid storage identifier')
        _validate_format(fmt, content)
        metadata = StorageMetadata(storage_id, hashlib.sha256(content).hexdigest(), len(content), fmt)
        staging = '.stage-' + storage_id
        fd = None
        link_attempted = False
        try:
            fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            view = memoryview(content)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError('Unable to write staging file')
                view = view[count:]
            os.fchmod(fd, 0o400)
            os.fsync(fd)
            os.fsync(directory)
            os.close(fd)
            fd = None
            link_attempted = True
            os.link(staging, storage_id, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
            if self.read_verified(metadata) != content:
                raise StorageError('Published bytes do not match')
            os.unlink(staging, dir_fd=directory)
            os.fsync(directory)
            return metadata
        except FileExistsError as error:
            raise StorageError('Reserved identifier or staging file already exists') from error
        except (OSError, StorageError) as error:
            if link_attempted:
                raise PublicationOutcomeUnknown(storage_id) from error
            raise StorageError('Artifact staging failed; inspect reserved staging') from error
        finally:
            if fd is not None:
                os.close(fd)

    def reconcile_reserved(self, metadata):
        """Read the exact expected object; absence or conflict is an error."""
        return self.read_verified(metadata)

    def cleanup_reserved_stage(self, storage_id):
        """Remove only an inspected, unpublished regular staging file.

        Caller must establish exclusive operation ownership and a confirmed
        unpublished outcome; this method cannot establish DB/commit status.
        """
        directory = self._require_open()
        if not isinstance(storage_id, str) or not _ID.fullmatch(storage_id):
            raise StorageError('Invalid storage identifier')
        try:
            try:
                os.stat(storage_id, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise StorageError('Published object exists; staging retained')
            staging = '.stage-' + storage_id
            info = os.stat(staging, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise StorageError('Staging file is not exclusively owned')
            os.unlink(staging, dir_fd=directory)
            os.fsync(directory)
        except OSError as error:
            raise StorageError('Staging cleanup unavailable') from error

    def publish(self, content, fmt):
        """Stage and publish without replacement; never delete a published object."""
        directory = self._require_open()
        _validate_format(fmt, content)
        storage_id, staging = uuid4().hex, '.stage-' + uuid4().hex
        fd, created, link_attempted = None, False, False
        try:
            fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            created = True
            view = memoryview(content)
            while view:
                count = os.write(fd, view)
                if count <= 0: raise OSError('Unable to write staging file')
                view = view[count:]
            os.fchmod(fd, 0o400); os.fsync(fd); os.close(fd); fd = None
            link_attempted = True
            os.link(staging, storage_id, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
            os.unlink(staging, dir_fd=directory); created = False
            os.fsync(directory)
            return StorageMetadata(storage_id, hashlib.sha256(content).hexdigest(), len(content), fmt)
        except FileExistsError as error:
            # A collision at the final name never permits overwriting it.
            if link_attempted: raise StorageError('Artifact identifier already exists') from error
            raise StorageError('Staging identifier already exists') from error
        except OSError as error:
            if link_attempted: raise PublicationOutcomeUnknown(storage_id) from error
            raise StorageError('Artifact staging failed') from error
        finally:
            if fd is not None: os.close(fd)
            if created:
                try: os.unlink(staging, dir_fd=directory)
                except OSError: pass  # An orphaned staging file needs manual reconciliation.

    def read_verified(self, metadata):
        directory = self._require_open()
        if not isinstance(metadata, StorageMetadata) or not isinstance(metadata.storage_id, str) or not _ID.fullmatch(metadata.storage_id):
            raise StorageError('Invalid storage identifier')
        try:
            fd = os.open(metadata.storage_id, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try: return read_verified_fd(fd, metadata.sha256, metadata.byte_size, metadata.format)
            finally: os.close(fd)
        except OSError as error:
            raise StorageError('Artifact unavailable') from error
