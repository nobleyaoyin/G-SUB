"""Synthetic reserved-storage and UTC checks; no configured database."""
from datetime import datetime, timezone
import hashlib
import os
import subprocess
import sys

import pytest

from app import reviewer_artifact_storage as storage
from app.strict_utc import canonical_utc


def test_reserved_ids_are_opaque_and_distinct():
    first = storage.ArtifactStorage.new_storage_id()
    second = storage.ArtifactStorage.new_storage_id()
    assert len(first) == 32 and int(first, 16) >= 0 and first != second


def test_process_death_after_publish_preserves_object(private_store):
    instance, root = private_store
    sid = 'f' * 32
    script = '''
import os, sys
from app import reviewer_artifact_storage as module
real_link = module.os.link
def stop_after_link(*args, **kwargs):
    real_link(*args, **kwargs)
    os._exit(37)
module.os.link = stop_after_link
module.ArtifactStorage(sys.argv[1]).publish_reserved(sys.argv[2], b"process crash", "txt")
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(root), sid], timeout=20, capture_output=True)
    assert result.returncode == 37, result.stderr.decode(errors='replace')
    assert (root / sid).read_bytes() == b'process crash'
    assert (root / ('.stage-' + sid)).exists()


@pytest.fixture
def private_store(tmp_path, monkeypatch):
    from app.database import engine as configured_engine
    def deny(*args, **kwargs):
        raise AssertionError('Configured database forbidden')
    monkeypatch.setattr(configured_engine, 'connect', deny)
    monkeypatch.setattr(configured_engine, 'raw_connection', deny)
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    with storage.ArtifactStorage(root) as instance:
        yield instance, root


def test_reserved_publish_exact_bytes_and_conflict(private_store):
    instance, root = private_store
    content = b'synthetic artifact bytes'
    sid = 'a' * 32
    result = instance.publish_reserved(sid, content, 'txt')
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.byte_size == len(content)
    assert instance.reconcile_reserved(result) == content
    assert (root / sid).read_bytes() == content
    with pytest.raises(storage.StorageError):
        instance.publish_reserved(sid, b'different content', 'txt')
    assert (root / sid).read_bytes() == content
    with pytest.raises(storage.StorageError, match='Published object'):
        instance.cleanup_reserved_stage(sid)


def test_partial_stage_requires_explicit_cleanup(private_store, monkeypatch):
    instance, root = private_store
    sid = 'b' * 32
    good = instance.publish_reserved('c' * 32, b'positive control', 'txt')
    assert instance.reconcile_reserved(good) == b'positive control'
    real_write = os.write
    count = 0
    def partial_then_fail(fd, data):
        nonlocal count
        count += 1
        if count == 1:
            return real_write(fd, data[:2])
        raise OSError('synthetic interruption')
    with monkeypatch.context() as patch:
        patch.setattr(storage.os, 'write', partial_then_fail)
        with pytest.raises(storage.StorageError, match='staging failed'):
            instance.publish_reserved(sid, b'synthetic text', 'txt')
    assert (root / ('.stage-' + sid)).read_bytes() == b'sy'
    instance.cleanup_reserved_stage(sid)
    assert not (root / ('.stage-' + sid)).exists()
    assert not (root / sid).exists()


def test_lost_publish_ack_retains_object_and_stage(private_store, monkeypatch):
    instance, root = private_store
    sid, content = 'd' * 32, b'private synthetic artifact'
    real_link = os.link
    def linked_then_error(*args, **kwargs):
        real_link(*args, **kwargs)
        raise OSError('synthetic lost acknowledgement')
    with monkeypatch.context() as patch:
        patch.setattr(storage.os, 'link', linked_then_error)
        with pytest.raises(storage.PublicationOutcomeUnknown) as unknown:
            instance.publish_reserved(sid, content, 'txt')
    assert unknown.value.storage_id == sid
    metadata = storage.StorageMetadata(sid, hashlib.sha256(content).hexdigest(), len(content), 'txt')
    assert instance.reconcile_reserved(metadata) == content
    assert (root / ('.stage-' + sid)).exists()
    with pytest.raises(storage.StorageError, match='Published object'):
        instance.cleanup_reserved_stage(sid)


@pytest.mark.parametrize('bad', ['../unsafe', 'F' * 32, '', 'a' * 31])
def test_bad_storage_id_rejected_with_valid_control(private_store, bad):
    instance, _ = private_store
    assert instance.publish_reserved('e' * 32, b'safe', 'txt').storage_id == 'e' * 32
    with pytest.raises(storage.StorageError, match='identifier'):
        instance.publish_reserved(bad, b'synthetic', 'txt')


def test_utc_normalization_and_leap_year():
    assert canonical_utc('2024-02-29T10:11:12.123456+02:30') == '2024-02-29T07:41:12.123456Z'
    assert canonical_utc(datetime(2026, 1, 1, tzinfo=timezone.utc)) == '2026-01-01T00:00:00.000000Z'


@pytest.mark.parametrize('bad', ['2026-02-31T00:00:00Z', '2025-02-29T00:00:00Z', '2026-01-01T00:00:00', 'nonsense', '2026-01-01T00:00:00.1234567Z', None])
def test_invalid_utc_rejected_with_positive_control(bad):
    assert canonical_utc('2024-02-29T00:00:00Z') == '2024-02-29T00:00:00.000000Z'
    with pytest.raises(ValueError):
        canonical_utc(bad)
