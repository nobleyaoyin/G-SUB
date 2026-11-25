"""Synthetic HTTP checks for sample source authorization; no Main files."""
import importlib
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('SECRET_KEY', 'synthetic-editor-source-key-0000000000000000')

from fastapi import HTTPException
from sqlalchemy import text

import app.main as main
from app.models import User
from app.sample_storage import SampleStorage
from tests import test_reviewer_download as fixtures


def test_editor_sample_source_honors_controlled_authorization():
    f = fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        assert f.root.is_relative_to(Path(os.environ['TMPDIR']).resolve())
        assert not f.root.is_relative_to(Path(__file__).resolve().parents[1])
        eic = User(name='Synthetic EIC', email='sample-eic@example.com', role='eic', password_hash='x')
        other_editor = User(name='Other editor', email='other-editor@example.com', role='editor', password_hash='x')
        f.db.add_all([eic, other_editor]); f.db.commit()
        importlib.import_module('migrations.035_sample_document_storage').migrate(f.db_path)
        f.current = f.author
        created = f.client.post('/manuscripts/', json={'title':'Synthetic peer workflow', 'abstract':'Synthetic research abstract.'})
        assert created.status_code == 201
        mid = created.json()['manuscript_id']
        f.db.execute(text("INSERT INTO sample_manuscripts VALUES (:mid,datetime('now'))"), {'mid':mid})
        f.db.commit()  # Operator fixture provisioning, not a workflow transition.
        with patch.object(SampleStorage, 'for_development', return_value=SampleStorage(f.root / 'samples', f.root / 'uploads')):
            upload = f.client.post(f'/manuscripts/{mid}/upload', files={'file':('paper.pdf', b'%PDF-synthetic-428', 'application/pdf')})
            assert upload.status_code == 200
            f.db.rollback()
            assert f.client.post(f'/manuscripts/{mid}/submit').status_code == 200
            f.db.rollback()
            f.current = eic
            assert f.client.post(f'/eic/manuscripts/{mid}/initial-scan', json={'decision':'pass','comments':'Ready for initial editing.'}).status_code == 201
            f.db.rollback()
            invitation = f.client.post('/eic/initial-editor/invite', json={'manuscript_id':mid,'editor_id':f.editor.user_id})
            assert invitation.status_code == 201, invitation.text
            iid = invitation.json()['invitation_id']
            f.db.rollback()
            f.current = f.editor
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond', json={'decision':'accept'}).status_code == 200
            f.db.rollback()
            f.current = other_editor
            assert f.client.get(f'/manuscripts/{mid}/download').status_code == 403
            f.db.rollback()
            f.current = f.editor
            with patch('app.routers.manuscripts.source_may_be_controlled', return_value=True), patch('app.routers.manuscripts.authorize_source', side_effect=HTTPException(403, 'Grant required')) as authorize:
                assert f.client.get(f'/manuscripts/{mid}/download').status_code == 403
                assert f.client.get(f"/manuscripts/{mid}/versions/{upload.json()['filename']}").status_code == 403
                assert authorize.call_count == 2
            f.db.rollback()
            with patch('app.routers.manuscripts.source_may_be_controlled', return_value=True), patch('app.routers.manuscripts.authorize_source', return_value=None) as authorize:
                response = f.client.get(f'/manuscripts/{mid}/download')
                assert response.status_code == 200 and response.content == b'%PDF-synthetic-428'
                assert authorize.call_count == 1
            f.db.rollback()
            edited = f.client.post(f'/eic/initial-editing/{mid}/submit',
                data={'comments':'Synthetic editing.'}, files={'file':('edited.pdf', b'%PDF-synthetic-edited', 'application/pdf')})
            assert edited.status_code == 503
            assert not (f.root / 'uploads' / 'initial_editing' / str(mid)).exists()
    finally:
        f.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for item in reversed(f.patches): item.stop()
        f.db.close(); f.engine.dispose(); f.temp._finalizer.detach()
