import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.sample_storage import MAX_SAMPLE_BYTES, SampleStorage, SampleStorageError


@pytest.fixture
def storage(tmp_path):
    legacy = tmp_path / "legacy" / "uploads"
    legacy.mkdir(parents=True)
    return SampleStorage(tmp_path / "samples", legacy)


@pytest.mark.parametrize("extension", ["pdf", "docx", "doc", "txt"])
def test_sample_identity_round_trip_and_immutability(storage, extension):
    identity = f"sample:v1/manuscripts/123/original.{extension}"
    content = b"synthetic sample bytes"
    digest = storage.write_new(identity, content)
    assert digest == hashlib.sha256(content).hexdigest()
    assert storage.read(identity, digest=digest) == content
    with pytest.raises(FileExistsError):
        storage.write_new(identity, b"replacement")
    assert storage.read(identity, digest=digest) == content


@pytest.mark.parametrize("identity", ["uploads/manuscripts/1/a.pdf", "sample:v2/manuscripts/1/a.pdf",
    "sample:v1/manuscripts/../a.pdf", "sample:v1/manuscripts/1/../../a.pdf",
    "sample:v1/manuscripts/1/a.exe", "sample:v1/unknown/1/a.pdf",
    "sample:v1/manuscripts/01/a.pdf", "sample:v1/manuscripts/1/a..pdf"])
def test_invalid_identities_are_rejected(storage, identity):
    with pytest.raises(SampleStorageError):
        storage.write_new(identity, b"synthetic")


def test_size_missing_and_digest_failure(storage):
    identity = "sample:v1/manuscripts/1/file.txt"
    with pytest.raises(FileNotFoundError):
        storage.read(identity, digest="0" * 64)
    with pytest.raises(SampleStorageError):
        storage.write_new(identity, b"x" * (MAX_SAMPLE_BYTES + 1))
    storage.write_new(identity, b"original")
    with pytest.raises(SampleStorageError):
        storage.read(identity, digest="0" * 64)


def test_root_overlap_and_symlink_traversal_are_rejected(tmp_path, storage):
    legacy = tmp_path / "legacy" / "uploads"
    with pytest.raises(SampleStorageError):
        SampleStorage(legacy / "samples", legacy)
    storage.write_new("sample:v1/manuscripts/1/a.txt", b"safe")
    (storage.root / "manuscripts" / "2").symlink_to(legacy, target_is_directory=True)
    with pytest.raises(OSError):
        storage.read("sample:v1/manuscripts/2/a.txt", digest="0" * 64)


def test_hard_link_to_legacy_is_not_read(tmp_path, storage):
    old = tmp_path / "legacy" / "uploads" / "legacy.txt"
    old.write_bytes(b"private legacy content")
    storage.write_new("sample:v1/manuscripts/1/a.txt", b"sample")
    os.link(old, storage.root / "manuscripts" / "1" / "linked.txt")
    with pytest.raises(SampleStorageError):
        storage.read("sample:v1/manuscripts/1/linked.txt", digest="0" * 64)
    assert old.read_bytes() == b"private legacy content"


def test_tampered_sample_fails_digest_verification(storage):
    identity = "sample:v1/manuscripts/1/version.txt"
    digest = storage.write_new(identity, b"original")
    (storage.root / "manuscripts" / "1" / "version.txt").write_bytes(b"tampered")
    with pytest.raises(SampleStorageError):
        storage.read(identity, digest=digest)


def test_sample_survives_new_process(tmp_path, storage):
    identity = "sample:v1/manuscripts/123/version.txt"
    digest = storage.write_new(identity, b"persistent bytes")
    script = ("from pathlib import Path; from app.sample_storage import SampleStorage; "
              "s=SampleStorage(Path(__import__('sys').argv[1]),Path(__import__('sys').argv[2])); "
              "assert s.read(__import__('sys').argv[3],digest=__import__('sys').argv[4]) == b'persistent bytes'")
    result = subprocess.run([sys.executable, "-c", script, str(storage.root),
        str(tmp_path / "legacy" / "uploads"), identity, digest], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_concurrent_publication_never_overwrites(storage):
    identity = "sample:v1/manuscripts/4/version.txt"
    def write(data):
        try:
            return storage.write_new(identity, data)
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [b"first", b"second"]))
    assert sum(result is not None for result in results) == 1
    winning_digest = next(result for result in results if result is not None)
    assert hashlib.sha256(storage.read(identity, digest=winning_digest)).hexdigest() == winning_digest
