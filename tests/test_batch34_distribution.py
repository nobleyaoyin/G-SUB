"""Two authenticated editor grants and independent revocation in disposable storage."""
import hashlib
import sqlite3
from app.reviewer_artifact_storage import ArtifactStorage
from tests.batch83_migration_support import bootstrap_prospective_distribution
import os
from unittest.mock import patch
from app.routers import document_distribution as distribution, eic
from tests import test_final_workflow as final_fixture
from tests.test_batch17c_editor_distribution import migration


def test_two_grants_independent_revocation_and_history():
    f = final_fixture.FinalWorkflowTest(methodName='test_invitation_replacement_corrections_and_confirmation')
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root):
            agreement = f.reach_agreement()
            f.current = f.author
            accepted = f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={'decision':'accept','agreement_version':agreement['agreement_version']})
            assert accepted.status_code == 200, accepted.text
            invitation = f.invite(f.alternate)
            assert invitation.status_code == 201, invitation.text
            iid = invitation.json()['invitation_id']
            assert f.respond(f.alternate, iid, 'accept').status_code == 200
            source = f.write(f'uploads/manuscripts/{f.mid}/batch34.txt', b'Synthetic grant bytes\n')
            f.manuscript.file_path = source
            f.db.commit()
            migration.migrate(f.db_path)
            private = f.root / 'batch34-private'
            private.mkdir(mode=0o700)
            # Preserve a genuinely pre-cutover grant without inventing its round.
            old_grant='c'*32; old_artifact='a'*32; old_storage='b'*32
            digest=hashlib.sha256(b'Synthetic grant bytes\n').hexdigest();stamp='2020-01-01T00:00:00.000000Z'
            with ArtifactStorage(str(private)) as store:
                store.publish_reserved(old_storage,b'Synthetic grant bytes\n','txt')
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                initial_id=db.execute("SELECT invitation_id FROM initial_editor_invitations WHERE manuscript_id=? AND editor_id=? AND status='accepted'",(f.mid,f.editor.user_id)).fetchone()[0]
                db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(old_storage,f.mid,f.chief.user_id,'editor_source',None,None,digest,len(b'Synthetic grant bytes\n'),'txt','batch34-old-reservation','d'*64,stamp))
                db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(old_artifact,f.mid,'editor_source',1,old_storage,digest,len(b'Synthetic grant bytes\n'),'txt',None,None,f.chief.user_id,stamp))
                db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(old_grant,f.mid,old_artifact,f.editor.user_id,'editor',initial_id,None,None,None,f.chief.user_id,'manual','not_requested','not_requested','batch34-initial-grant-01','e'*64,stamp))
            bootstrap_prospective_distribution(f.db_path)
            with patch.object(distribution, 'DATA_ROOT', f.root), patch.dict(os.environ, {'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
                f.current = f.chief
                candidates = f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates')
                assert candidates.status_code == 200, candidates.text
                data = candidates.json()
                recipients = {row['invitation_kind']: row['invitation_id'] for row in data['recipients']}
                assert recipients['final'] == iid and recipients.get('initial')
                def grant(kind, key):
                    return f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants', json={
                        'invitation_kind':kind, 'invitation_id':recipients[kind],
                        'source_sha256':data['document']['sha256'], 'idempotency_key':key})
                wrong = f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants', json={
                    'invitation_kind':'final','invitation_id':iid,'source_sha256':'0'*64,'idempotency_key':'wrong-version-key-0001'})
                assert wrong.status_code == 409
                wrong_paper = f.client.post('/document-distribution/manuscripts/999999/grants', json={
                    'invitation_kind':'final','invitation_id':iid,'source_sha256':data['document']['sha256'],'idempotency_key':'wrong-paper-key-00001'})
                assert wrong_paper.status_code == 404
                first = grant('initial', 'batch34-initial-grant-new'); second = grant('final', 'batch34-final-grant-0001')
                assert first.status_code == 409 and second.status_code == 200
                g1, g2 = old_grant, second.json()['grant_id']
                assert g1 != g2
                f.current = f.editor
                assert f.client.get(f'/document-distribution/grants/{g1}/download').content == b'Synthetic grant bytes\n'
                assert f.client.get(f'/document-distribution/grants/{g2}/download').status_code == 404
                f.current = f.alternate
                assert f.client.get(f'/document-distribution/grants/{g2}/download').content == b'Synthetic grant bytes\n'
                assert f.client.get(f'/document-distribution/grants/{g1}/download').status_code == 404
                assert f.client.post(f'/document-distribution/grants/{g1}/revoke',json={'reason':'Synthetic'}).status_code == 403
                f.current = f.chief
                assert f.client.post(f'/document-distribution/grants/{g1}/revoke',json={'reason':'Synthetic'}).status_code == 200
                history = f.client.get(f'/document-distribution/manuscripts/{f.mid}/history')
                assert history.status_code == 200
                rows = {row['grant_id']:row for row in history.json()}
                assert rows[g1]['revoked_at'] and rows[g2]['revoked_at'] is None
                assert rows[g1]['email'] == rows[g2]['email'] == 'not_requested'
                first_revoked_at = rows[g1]['revoked_at']
                assert f.client.post(f'/document-distribution/grants/{g1}/revoke',json={'reason':'Retry'}).status_code == 200
                rows2 = {row['grant_id']:row for row in f.client.get(f'/document-distribution/manuscripts/{f.mid}/history').json()}
                assert rows2[g1]['revoked_at'] == first_revoked_at
                f.current = f.editor
                assert f.client.get(f'/document-distribution/grants/{g1}/download').status_code == 404
                f.current = f.alternate
                assert f.client.get(f'/document-distribution/grants/{g2}/download').content == b'Synthetic grant bytes\n'
    finally:
        f.tearDown()
