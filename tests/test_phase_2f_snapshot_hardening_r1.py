"""Descriptor safety checks with synthetic temporary files and in-memory DB."""
import os

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models, review_files
from tests.test_phase_2f_reviewer_projections import api_factory
from tests.test_phase_2f_reviewer_document_release import setup_file


def test_symlinked_ancestor_is_denied(api_factory, monkeypatch, tmp_path):
    client, _, _, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    directory = path.parent
    target = directory.with_name('real-directory')
    directory.rename(target)
    directory.symlink_to(target, target_is_directory=True)
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content


def test_missing_dirfd_platform_support_fails_closed(api_factory, monkeypatch, tmp_path):
    client, _, _, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    monkeypatch.setattr(review_files.os, 'supports_dir_fd', set())
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content


def test_all_opened_descriptors_close_on_read_failure(api_factory, monkeypatch, tmp_path):
    _, _, engine, _, _ = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    actual_open, actual_close = os.open, os.close
    opened, closed = [], []
    def tracked_open(*args, **kwargs):
        fd = actual_open(*args, **kwargs)
        opened.append(fd)
        return fd
    def tracked_close(fd):
        closed.append(fd)
        return actual_close(fd)
    def fail_read(*args):
        raise OSError('synthetic read error')
    monkeypatch.setattr(review_files.os, 'open', tracked_open)
    monkeypatch.setattr(review_files.os, 'close', tracked_close)
    monkeypatch.setattr(review_files.os, 'read', fail_read)
    monkeypatch.setattr(review_files.os, 'supports_dir_fd', {tracked_open})
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            review_files.snapshot_assignment_file(db, db.get(models.ReviewAssignment, 1), db.get(models.Manuscript, 1))
    assert error.value.status_code == 409
    assert opened and sorted(opened) == sorted(closed)
