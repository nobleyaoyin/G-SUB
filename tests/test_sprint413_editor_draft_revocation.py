"""Revocation protects historical editorial drafts in disposable fixtures."""
from unittest.mock import patch
import os
import jwt

from app import models, onlyoffice_docx
from app.routers import eic
from tests import test_reviewer_download as fixtures
from tests import test_final_workflow as final_fixtures
from tests.batch83_migration_support import bootstrap_prospective_distribution
from tests.academic_docx_fixture import academic_docx
from tests.test_onlyoffice_gsub_integration import CONFIG, SECRET


def test_initial_editor_revision_draft_versions_recheck_revocation():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        chief = models.User(name='Synthetic EIC', email='sprint413@example.com', password_hash='x', role='eic')
        f.db.add(chief)
        f.manuscript.status = 'initial_editing'
        source = f.write(f'uploads/initial_editing/{f.mid}/revision-source.txt', b'Synthetic approved source')
        f.db.add(models.InitialEditingSubmission(manuscript_id=f.mid, editor_id=f.editor.user_id,
            file_path=source, comments='Synthetic', status='author_revision_requested'))
        f.db.commit()
        invitation = f.db.query(models.InitialEditorInvitation).filter_by(manuscript_id=f.mid, editor_id=f.editor.user_id).one()
        iid = invitation.invitation_id
        bootstrap_prospective_distribution(f.db_path)
        with patch.object(eic, 'BASE_DIR', f.root):
            f.current = f.editor
            url = f'/eic/manuscripts/{f.mid}/online-text/initial'
            opened = f.client.get(url); assert opened.status_code == 200, opened.text
            for content in ('First synthetic version', 'Second synthetic version'):
                token = f.client.get(url).json()['version']
                saved = f.client.post(url, json={'content':content, 'expected_version':token})
                assert saved.status_code == 200, saved.text
            history = f.client.get(url).json()['history']
            assert [item['number'] for item in history] == [1, 2]
            paths = [f'{url}/{item["filename"]}' for item in history]
            assert f.client.get(paths[0]).content == b'First synthetic version'
            assert f.client.get(paths[1]).content == b'Second synthetic version'
            f.db.rollback(); f.current = chief
            revoke = f.client.post(f'/document-distribution/manuscripts/{f.mid}/editor-invitations/initial/{iid}/revoke', json={'reason':'Synthetic test'})
            assert revoke.status_code == 200, revoke.text
            f.current = f.editor
            assert f.client.get(url).status_code == 404
            assert f.client.get(paths[0]).status_code == 404
            assert f.client.get(paths[1]).status_code == 404
            assert f.client.post(url, json={'content':'Unauthorized', 'expected_version':'0'*64}).status_code == 404
            assert (f.root / source).read_bytes() == b'Synthetic approved source'
    finally:
        f.tearDown()


def test_final_editor_history_rechecks_actual_revocation():
    f = final_fixtures.FinalWorkflowTest(); f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root):
            source = f.write(f'uploads/initial_editing/{f.mid}/confirmed.txt', b'Synthetic confirmed source')
            submission = f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=f.mid).one()
            confirmation = f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one()
            submission.file_path = source; confirmation.file_path = source; f.db.commit()
            agreement = f.reach_agreement(); f.current = f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code == 200
            invitation = f.invite(f.editor); assert invitation.status_code == 201, invitation.text
            iid = invitation.json()['invitation_id']
            assert f.respond(f.editor, iid, 'accept').status_code == 200
            f.db.commit(); bootstrap_prospective_distribution(f.db_path)
            f.current = f.editor; url = f'/eic/manuscripts/{f.mid}/online-text/final'
            opened = f.client.get(url); assert opened.status_code == 200, opened.text
            assert f.client.post(url, json={'content':'Synthetic final draft','expected_version':opened.json()['version']}).status_code == 200
            history = f.client.get(url).json()['history']; path = f'{url}/{history[0]["filename"]}'
            assert f.client.get(path).content == b'Synthetic final draft'
            f.db.rollback(); f.current = f.chief
            revoked = f.client.post(f'/document-distribution/manuscripts/{f.mid}/editor-invitations/final/{iid}/revoke', json={'reason':'Synthetic test'})
            assert revoked.status_code == 200, revoked.text
            f.current = f.editor
            assert f.client.get(url).status_code == 404
            assert f.client.get(path).status_code == 404
            assert f.client.post(url, json={'content':'Unauthorized','expected_version':'0'*64}).status_code == 404
    finally:
        f.tearDown()


def test_docx_editor_session_rechecks_actual_revocation():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        chief = models.User(name='Synthetic EIC', email='sprint413docx@example.com', password_hash='x', role='eic')
        f.db.add(chief); f.manuscript.status = 'initial_editing'
        source = f.write(f'uploads/initial_editing/{f.mid}/revision.docx', academic_docx())
        f.db.add(models.InitialEditingSubmission(manuscript_id=f.mid, editor_id=f.editor.user_id,
            file_path=source, comments='Synthetic', status='author_revision_requested'))
        f.db.commit()
        iid = f.db.query(models.InitialEditorInvitation).filter_by(manuscript_id=f.mid, editor_id=f.editor.user_id).one().invitation_id
        bootstrap_prospective_distribution(f.db_path)
        with patch.object(onlyoffice_docx, 'BASE_DIR', f.root), patch.dict(os.environ, CONFIG):
            f.current = f.editor; base = f'/onlyoffice/manuscripts/{f.mid}/initial'
            opened = f.client.post(base+'/sessions'); assert opened.status_code == 200, opened.text
            sid = opened.json()['session']
            assert f.client.get(base+f'/sessions/{sid}/status').status_code == 200
            f.db.rollback(); f.current = chief
            revoked = f.client.post(f'/document-distribution/manuscripts/{f.mid}/editor-invitations/initial/{iid}/revoke', json={'reason':'Synthetic test'})
            assert revoked.status_code == 200, revoked.text
            f.current = f.editor
            assert f.client.get(base+f'/sessions/{sid}/status').status_code == 403
            assert f.client.get(base+'/versions').status_code == 403
            assert f.client.post(base+'/sessions').status_code == 403
    finally:
        f.tearDown()


def test_final_docx_version_rechecks_actual_revocation():
    f = final_fixtures.FinalWorkflowTest(); f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(onlyoffice_docx, 'BASE_DIR', f.root), patch.dict(os.environ, CONFIG):
            content = academic_docx()
            source = f.write(f'uploads/initial_editing/{f.mid}/confirmed.docx', content)
            submission = f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=f.mid).one()
            confirmation = f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one()
            submission.file_path = source; confirmation.file_path = source; f.db.commit()
            agreement = f.reach_agreement(); f.current = f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code == 200
            invitation = f.invite(f.editor); assert invitation.status_code == 201, invitation.text
            iid = invitation.json()['invitation_id']; assert f.respond(f.editor, iid, 'accept').status_code == 200
            f.db.commit(); bootstrap_prospective_distribution(f.db_path)
            f.current = f.editor; base = f'/onlyoffice/manuscripts/{f.mid}/final'
            opened = f.client.post(base+'/sessions'); assert opened.status_code == 200, opened.text
            sid = opened.json()['session']; body = {'key':sid,'status':2,'url':'http://127.0.0.1:8088/cache/files/synthetic'}
            token = jwt.encode({'payload':body,'operation':'callback'}, SECRET, algorithm='HS256')
            with patch.object(onlyoffice_docx, 'fetch', return_value=content):
                assert f.client.post('/onlyoffice/callbacks/'+sid, json=body, headers={'Authorization':'Bearer '+token}).status_code == 200
            versions = f.client.get(base+'/versions').json(); assert len(versions) == 1
            path = base+'/versions/'+versions[0]['id']; assert f.client.get(path).content == content
            f.db.rollback(); f.current = f.chief
            revoked = f.client.post(f'/document-distribution/manuscripts/{f.mid}/editor-invitations/final/{iid}/revoke', json={'reason':'Synthetic test'})
            assert revoked.status_code == 200, revoked.text
            f.current = f.editor
            assert f.client.get(path).status_code == 403
            assert f.client.get(base+f'/sessions/{sid}/status').status_code == 403
    finally:
        f.tearDown()
