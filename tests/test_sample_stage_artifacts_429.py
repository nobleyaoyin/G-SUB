"""Guardrails for additive sample Final Editing and Formatting bindings."""
import importlib
import os
from pathlib import Path
import sqlite3
import pytest
os.environ.setdefault('SECRET_KEY', 'synthetic-stage-storage-key-0000000000000000')

import app.main as main
from tests import test_reviewer_download as fixtures


def test_stage_migration_is_idempotent_and_rejects_forged_binding():
    fixture = fixtures.ReviewerDownloadsTest()
    fixture.setUp()
    try:
        assert fixture.root.is_relative_to(Path(os.environ['TMPDIR']).resolve())
        fixture.db.close()
        importlib.import_module('migrations.035_sample_document_storage').migrate(fixture.db_path)
        migration = importlib.import_module('migrations.037_sample_final_formatting')
        migration.migrate(fixture.db_path)
        migration.migrate(fixture.db_path)
        with sqlite3.connect(fixture.db_path) as db:
            with pytest.raises(sqlite3.IntegrityError, match='invalid sample stage artifact binding'):
                db.execute('''INSERT INTO sample_stage_artifacts
                  (kind,submission_id,manuscript_id,actor_id,version_id,storage_identity,sha256,byte_size,file_format,created_at)
                  VALUES ('formatting',999,1,1,?,? ,?,1,'pdf',datetime('now'))''',
                  ('a'*32,'sample:v1/formatting/1/'+('a'*32)+'.pdf','b'*64))
            assert db.execute('SELECT count(*) FROM sample_stage_artifacts').fetchone()[0] == 0
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
        migration.downgrade_empty(fixture.db_path)
    finally:
        fixture.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for item in reversed(fixture.patches): item.stop()
        fixture.engine.dispose(); fixture.temp._finalizer.detach()


def test_stage_reader_checks_binding_and_digest(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from app import sample_stage_artifacts
    from app.sample_storage import SampleStorage
    import hashlib

    storage = SampleStorage(tmp_path / 'sample', tmp_path / 'uploads')
    version = 'a' * 32
    identity = f'sample:v1/final_editing/3/{version}.pdf'
    data = b'%PDF-synthetic-final'
    digest = storage.write_new(identity, data)
    row = {'version_id':version, 'file_format':'pdf', 'storage_identity':identity,
           'sha256':digest, 'byte_size':len(data), 'actor_id':7}
    db = MagicMock()
    db.execute.return_value.mappings.return_value.first.return_value = row
    monkeypatch.setattr(sample_stage_artifacts, 'require_schema', lambda _: None)
    monkeypatch.setattr(SampleStorage, 'for_development', lambda: storage)
    submission = SimpleNamespace(submission_id=2, manuscript_id=3, editor_id=7, file_path=identity)
    assert sample_stage_artifacts.read(db, 'final_editing', submission)[1] == data
    row['actor_id'] = 8
    with pytest.raises(HTTPException) as exc: sample_stage_artifacts.read(db, 'final_editing', submission)
    assert exc.value.status_code == 409
    row['actor_id'] = 7
    row['sha256'] = hashlib.sha256(b'different').hexdigest()
    with pytest.raises(HTTPException) as exc: sample_stage_artifacts.read(db, 'final_editing', submission)
    assert exc.value.status_code == 409
