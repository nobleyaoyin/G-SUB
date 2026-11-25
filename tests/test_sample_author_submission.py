"""Actual synthetic HTTP operations; storage and database remain disposable."""
import hashlib
import importlib
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

os.environ.setdefault('SECRET_KEY', 'synthetic-author-submission-key-0000000000000000')

from sqlalchemy import event, text
from fastapi.testclient import TestClient

import app.main as main
from app.models import User
from app.sample_storage import SampleStorage
from tests import test_reviewer_download as reviewer_fixtures
from tests.test_secure_word_uploads import docx_bytes


def test_real_initial_submission_and_initial_revision():
    f = reviewer_fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        assert f.root.is_relative_to(Path(os.environ['TMPDIR']).resolve())
        assert not f.root.is_relative_to(Path(__file__).resolve().parents[1])
        f.db.add(User(name='Synthetic EIC', email='synthetic-eic@example.com', role='eic', password_hash='x'))
        f.db.commit()
        eic = f.db.query(User).filter_by(email='synthetic-eic@example.com').one()
        f.db.commit()
        importlib.import_module('migrations.035_sample_document_storage').migrate(f.db_path)
        f.current = f.author
        created = f.client.post('/manuscripts/', json={'title':'Synthetic research', 'abstract':'A synthetic research abstract.'})
        assert created.status_code == 201, created.text
        mid = created.json()['manuscript_id']
        f.db.execute(text("INSERT INTO sample_manuscripts VALUES (:mid,datetime('now'))"), {'mid': mid})
        f.db.commit()  # Initial operator fixture provisioning, not a workflow transition.
        storage = SampleStorage(f.root / 'sample_documents', f.root / 'uploads')
        with patch.object(SampleStorage, 'for_development', return_value=storage):
            first_bytes = b'%PDF-synthetic-original'
            first = f.client.post(f'/manuscripts/{mid}/upload', files={'file':('original.pdf', first_bytes, 'application/pdf')})
            assert first.status_code == 200, first.text
            f.db.rollback()
            with patch('app.routers.manuscripts.AI_PRESCREENING_ENABLED', True):
                ai_unavailable = f.client.post(f'/manuscripts/{mid}/submit')
                assert ai_unavailable.status_code == 503
            f.db.rollback()
            def fail_snapshot(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith('INSERT INTO MANUSCRIPT_SUBMISSION_SNAPSHOTS'):
                    raise sqlite3.DatabaseError('synthetic snapshot failure')
            event.listen(f.engine, 'before_cursor_execute', fail_snapshot)
            try:
                failed = TestClient(main.app, raise_server_exceptions=False).post(f'/manuscripts/{mid}/submit')
                assert failed.status_code >= 500
            finally:
                event.remove(f.engine, 'before_cursor_execute', fail_snapshot)
            f.db.rollback()
            assert f.db.execute(text('SELECT status FROM manuscripts WHERE manuscript_id=:mid'), {'mid':mid}).scalar_one() == 'draft'
            assert f.db.execute(text('SELECT count(*) FROM manuscript_submission_snapshots WHERE manuscript_id=:mid'), {'mid':mid}).scalar_one() == 0
            f.db.rollback()
            submitted = f.client.post(f'/manuscripts/{mid}/submit')
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()['status'] == 'submitted'
            f.db.rollback()
            assert f.client.post(f'/manuscripts/{mid}/submit').status_code == 409
            f.db.rollback()
            f.current = eic
            scan = f.client.post(f'/eic/manuscripts/{mid}/initial-scan', json={'decision':'revision_required','comments':'Clarify the methodology.'})
            assert scan.status_code == 201, scan.text
            f.db.rollback()
            f.current = f.author
            stale = f.client.post(f'/manuscripts/{mid}/initial-resubmit', json={'abstract':'Revised abstract.'})
            assert stale.status_code == 409, stale.text
            f.db.rollback()
            revised_bytes = docx_bytes()
            revised = f.client.post(f'/manuscripts/{mid}/upload', files={'file':('revision.docx', revised_bytes, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
            assert revised.status_code == 200, revised.text
            f.db.rollback()
            resubmitted = f.client.post(f'/manuscripts/{mid}/initial-resubmit', json={'abstract':'Revised abstract.'})
            assert resubmitted.status_code == 200, resubmitted.text
            assert resubmitted.json()['status'] == 'submitted'
            f.db.rollback()
            assert f.client.post(f'/manuscripts/{mid}/initial-resubmit', json={'abstract':'Revised abstract.'}).status_code == 409
            f.db.rollback()
            rows = f.db.execute(text('SELECT snapshot_id,submission_kind,review_round,file_ref,file_sha256 FROM manuscript_submission_snapshots WHERE manuscript_id=:mid ORDER BY submission_sequence'), {'mid':mid}).mappings().all()
            assert [row['submission_kind'] for row in rows] == ['initial','initial_revision']
            assert [row['review_round'] for row in rows] == [1,1]
            assert rows[0]['file_sha256'] == hashlib.sha256(first_bytes).hexdigest()
            assert rows[1]['file_sha256'] == hashlib.sha256(revised_bytes).hexdigest()
            assert first.json()['version_id'] in rows[0]['file_ref'] and revised.json()['version_id'] in rows[1]['file_ref']
            snapshot_ids = [row['snapshot_id'] for row in rows]
            f.db.rollback()
            for snapshot_id, expected in zip(snapshot_ids, [first_bytes, revised_bytes]):
                response = f.client.get(f'/manuscripts/{mid}/generation-history/submissions/{snapshot_id}/download')
                assert response.status_code == 200 and response.content == expected
            assert f.client.get(f'/manuscripts/{mid}/generation-history/submissions/{"f" * 32}/download').status_code == 404
            f.db.rollback()
            f.current = eic
            for snapshot_id, expected in zip(snapshot_ids, [first_bytes, revised_bytes]):
                response = f.client.get(f'/eic/manuscripts/{mid}/document-timeline/submissions/{snapshot_id}/download')
                assert response.status_code == 200 and response.content == expected
            f.db.rollback()
            f.current = f.reviewer
            assert f.client.get(f'/manuscripts/{mid}/generation-history/submissions/{snapshot_ids[0]}/download').status_code == 403
            assert not (f.root / 'uploads' / 'manuscripts' / str(mid)).exists()
    finally:
        f.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for item in reversed(f.patches):
            item.stop()
        f.db.close()
        f.engine.dispose()
        f.temp._finalizer.detach()  # Retain disposable test files for inspection.


def test_sample_online_text_save_history_and_submission():
    f = reviewer_fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        assert f.root.is_relative_to(Path(os.environ['TMPDIR']).resolve())
        assert not f.root.is_relative_to(Path(__file__).resolve().parents[1])
        importlib.import_module('migrations.035_sample_document_storage').migrate(f.db_path)
        f.current = f.author
        created = f.client.post('/manuscripts/', json={'title':'Online synthetic research', 'abstract':'A synthetic abstract.'})
        assert created.status_code == 201
        mid = created.json()['manuscript_id']
        f.db.execute(text("INSERT INTO sample_manuscripts VALUES (:mid,datetime('now'))"), {'mid':mid})
        f.db.commit()
        storage = SampleStorage(f.root / 'sample_documents', f.root / 'uploads')
        with patch.object(SampleStorage, 'for_development', return_value=storage):
            first = f.client.post(f'/manuscripts/{mid}/upload', files={'file':('draft.txt', b'Original synthetic text.', 'text/plain')})
            assert first.status_code == 200
            f.db.rollback()
            source = f.client.get(f'/manuscripts/{mid}/online-text')
            assert source.status_code == 200 and source.json()['content'] == 'Original synthetic text.'
            token = source.json()['version']
            f.db.rollback()
            saved = f.client.post(f'/manuscripts/{mid}/online-text', json={'content':'Revised synthetic text.', 'expected_version':token, 'change_note':'Clarification'})
            assert saved.status_code == 200, saved.text
            f.db.rollback()
            stale = f.client.post(f'/manuscripts/{mid}/online-text', json={'content':'Stale edit.', 'expected_version':token})
            assert stale.status_code == 409
            f.db.rollback()
            current = f.client.get(f'/manuscripts/{mid}/online-text')
            assert current.status_code == 200 and current.json()['content'] == 'Revised synthetic text.'
            assert len(current.json()['history']) == 1
            online_id = current.json()['history'][0]['id']
            current_token = current.json()['version']
            f.db.rollback()
            historical = f.client.get(f'/manuscripts/{mid}/online-text/versions/{online_id}')
            assert historical.status_code == 200 and historical.content == b'Revised synthetic text.'
            f.db.rollback()
            unconfirmed = f.client.post(f'/manuscripts/{mid}/submit')
            assert unconfirmed.status_code == 409
            f.db.rollback()
            submitted = f.client.post(f'/manuscripts/{mid}/submit', params={'expected_online_version':current_token})
            assert submitted.status_code == 200, submitted.text
            f.db.rollback()
            row = f.db.execute(text('SELECT snapshot_id,file_sha256 FROM manuscript_submission_snapshots WHERE manuscript_id=:mid'), {'mid':mid}).mappings().one()
            assert row['file_sha256'] == hashlib.sha256(b'Revised synthetic text.').hexdigest()
            snapshot_id = row['snapshot_id']
            f.db.rollback()
            assert f.client.get(f'/manuscripts/{mid}/generation-history/submissions/{snapshot_id}/download').content == b'Revised synthetic text.'
            assert not (f.root / 'uploads' / 'manuscripts' / str(mid)).exists()
    finally:
        f.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for item in reversed(f.patches):
            item.stop()
        f.db.close()
        f.engine.dispose()
        f.temp._finalizer.detach()
