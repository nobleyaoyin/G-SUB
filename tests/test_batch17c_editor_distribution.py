"""Real HTTP and filesystem distribution checks using only synthetic temporary data."""
import importlib.util
from importlib import import_module
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch
import tests.test_reviewer_download as fixtures
from app.models import User
import app.routers.document_distribution as distribution

spec=importlib.util.spec_from_file_location('migration21',Path(__file__).resolve().parents[1]/'migrations/021_document_distribution.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)

def migrate_current_distribution(path):
    """Install the current additive distribution prerequisites in this test DB."""
    from database.bootstrap.initialize import MIGRATIONS
    migration.migrate(path)
    for name in MIGRATIONS:
        if '022' <= name[:3] <= '032':
            import_module('migrations.' + name).migrate(path)


def test_editor_grant_download_revoke_and_idempotent_retry():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        eic=User(name='Synthetic EIC',email='eic17c@example.invalid',password_hash='x',role='eic');other_editor=User(name='Other Editor',email='other17c@example.invalid',password_hash='x',role='editor');f.db.add_all([eic,other_editor])
        source=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',b'Synthetic manuscript content\n')
        f.manuscript.file_path=source;f.manuscript.status='initial_editing';f.db.commit();f.db.refresh(eic)
        editor_id=f.editor.user_id; eic_id=eic.user_id;other_editor_id=other_editor.user_id
        migrate_current_distribution(f.db_path)
        private=f.root/'private-objects';private.mkdir(mode=0o700)
        with patch.object(distribution,'DATA_ROOT',f.root.resolve()),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            f.current=f.editor
            assert f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates').status_code==403
            f.current=f.db.get(User,eic_id)
            candidates=f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates')
            assert candidates.status_code==200,candidates.text
            data=candidates.json(); assert len(data['recipients'])==1
            invitation=data['recipients'][0]
            request={'invitation_kind':invitation['invitation_kind'],'invitation_id':invitation['invitation_id'],'source_sha256':data['document']['sha256'],'idempotency_key':'synthetic-request-key-123'}
            wrong={**request,'invitation_id':999}
            assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=wrong).status_code==409
            assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json={**request,'source_sha256':'0'*64}).status_code==409
            grant=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=request)
            assert grant.status_code==200,grant.text
            gid=grant.json()['grant_id']; assert grant.json()['result']=='access_granted'
            retry=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=request)
            assert retry.status_code==200 and retry.json()['grant_id']==gid
            second={**request,'idempotency_key':'synthetic-request-key-456'}
            assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=second).json()['grant_id']==gid
            history=f.client.get(f'/document-distribution/manuscripts/{f.mid}/history')
            assert history.status_code==200 and len(history.json())==1
            assert history.json()[0]['email']=='not_requested'
            assert history.json()[0]['revoked_at'] is None
            assert f.client.get('/document-distribution/manuscripts/999999/history').status_code==404
            f.current=f.db.get(User,editor_id)
            listing=f.client.get('/document-distribution/my');assert listing.status_code==200 and listing.json()[0]['grant_id']==gid
            notifications=f.client.get('/notifications/my')
            assert notifications.status_code==200 and any(item['notification_type']=='document_distributed' for item in notifications.json())
            response=f.client.get(f'/document-distribution/grants/{gid}/download')
            assert response.status_code==200 and response.content==b'Synthetic manuscript content\n'
            with sqlite3.connect(f.db_path) as connection:
                storage_id=connection.execute('SELECT a.storage_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id WHERE g.grant_id=?',(gid,)).fetchone()[0]
            published=private/storage_id
            published.chmod(0o600);published.write_bytes(b'X'*len(response.content))
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==409
            published.write_bytes(response.content);published.chmod(0o400)
            # Replacing the original does not replace the already granted snapshot.
            (f.root/source).write_bytes(b'Later manuscript bytes\n')
            assert f.client.get(f'/document-distribution/grants/{gid}/download').content==b'Synthetic manuscript content\n'
            f.current=f.db.get(User,other_editor_id)
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
            f.current=f.other
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==403
            f.current=f.author
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==403
            assert f.client.get(f'/document-distribution/manuscripts/{f.mid}/history').status_code==403
            f.current=f.db.get(User,eic_id)
            assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic revocation'}).status_code==200
            revoked_history=f.client.get(f'/document-distribution/manuscripts/{f.mid}/history')
            assert revoked_history.status_code==200 and revoked_history.json()[0]['revoked_at']
            (f.root/source).write_bytes(b'Synthetic manuscript content\n')
            assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=request).status_code==409
            f.current=f.db.get(User,editor_id)
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
            assert f.client.get('/document-distribution/my').json()==[]
    finally: f.tearDown()


def test_reviewer_upload_version_and_eic_only_download():
    from app.models import ReviewAssignment, ReviewerInvitation
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        eic=User(name='Synthetic EIC',email='review17c@example.invalid',password_hash='x',role='eic');f.db.add(eic)
        assignment=ReviewAssignment(manuscript_id=f.mid,reviewer_id=f.reviewer.user_id,assigned_by=f.editor.user_id,review_round=1,status='assigned')
        f.db.add(assignment);f.db.flush();f.db.add(ReviewerInvitation(assignment_id=assignment.assignment_id,status='accepted'))
        f.db.commit();aid=assignment.assignment_id;eic_id=eic.user_id; reviewer_id=f.reviewer.user_id
        migration.migrate(f.db_path);private=f.root/'review-private';private.mkdir(mode=0o700)
        with patch.object(distribution,'DATA_ROOT',f.root.resolve()),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            f.current=f.other
            denied=f.client.post(f'/document-distribution/review-assignments/{aid}/documents',headers={'Idempotency-Key':'review-upload-key-0001'},files={'file':('review.txt',b'Synthetic reviewed text','text/plain')})
            assert denied.status_code==409
            f.current=f.db.get(User,reviewer_id)
            request=lambda: f.client.post(f'/document-distribution/review-assignments/{aid}/documents',headers={'Idempotency-Key':'review-upload-key-0001'},files={'file':('review.txt',b'Synthetic reviewed text','text/plain')})
            response=request();assert response.status_code==200,response.text
            artifact=response.json();assert artifact['review_round']==1 and artifact['version']==1
            assert request().json()==artifact
            changed=f.client.post(f'/document-distribution/review-assignments/{aid}/documents',headers={'Idempotency-Key':'review-upload-key-0001'},files={'file':('review.txt',b'Different reviewed text','text/plain')})
            assert changed.status_code==409
            invalid=f.client.post(f'/document-distribution/review-assignments/{aid}/documents',headers={'Idempotency-Key':'review-upload-key-0002'},files={'file':('review.exe',b'Invalid','application/octet-stream')})
            assert invalid.status_code==400
            revision=f.client.post(f'/document-distribution/review-assignments/{aid}/documents',headers={'Idempotency-Key':'review-upload-key-0002'},files={'file':('review.txt',b'Second reviewed version','text/plain')})
            assert revision.status_code==200 and revision.json()['version']==2
            f.current=f.author
            assert f.client.get(f"/document-distribution/reviewed-documents/{artifact['artifact_id']}/download").status_code==403
            f.current=f.db.get(User,eic_id)
            listing=f.client.get(f'/document-distribution/manuscripts/{f.mid}/reviewed-documents')
            assert listing.status_code==200 and len(listing.json())==2 and listing.json()[0]['artifact_id']==artifact['artifact_id']
            result=f.client.get(f"/document-distribution/reviewed-documents/{artifact['artifact_id']}/download")
            assert result.status_code==200 and result.content==b'Synthetic reviewed text'
            f.manuscript.review_round=2;f.db.commit();f.current=f.db.get(User,reviewer_id)
            assert request().status_code==409
    finally: f.tearDown()


def test_parallel_retry_and_storage_unavailable_recovery():
    from concurrent.futures import ThreadPoolExecutor
    from app.database import get_db
    import app.main as main
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        eic=User(name='Synthetic EIC',email='eic17c2@example.com',password_hash='x',role='eic');f.db.add(eic)
        f.manuscript.file_path=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',b'Concurrent manuscript\n');f.manuscript.status='initial_editing';f.db.commit()
        migrate_current_distribution(f.db_path);private=f.root/'private-concurrent';private.mkdir(mode=0o700)
        def independent_db():
            with f.Session() as db: yield db
        main.app.dependency_overrides[get_db]=independent_db
        f.current=eic
        with patch.object(distribution,'DATA_ROOT',f.root.resolve()),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            data=f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates').json();inv=data['recipients'][0]
            payload={'invitation_kind':inv['invitation_kind'],'invitation_id':inv['invitation_id'],'source_sha256':data['document']['sha256'],'idempotency_key':'parallel-request-key-123'}
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=payload),range(2)))
            assert all(r.status_code in (200,503) for r in results),[r.text for r in results]
            retry=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=payload)
            assert retry.status_code==200,retry.text
            assert len(f.client.get(f'/document-distribution/manuscripts/{f.mid}/history').json())==1
            recover={**payload,'idempotency_key':'recovery-request-key-456'}
            with patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':''}):
                assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=recover).status_code==503
            recovered=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=recover)
            assert recovered.status_code==200,recovered.text
            assert recovered.json()['grant_id']==retry.json()['grant_id']
    finally: f.tearDown()


def test_notification_failure_rolls_back_grant_and_retry_reconciles():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        eic=User(name='Synthetic EIC',email='eic17c3@example.com',password_hash='x',role='eic');f.db.add(eic)
        f.manuscript.file_path=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',b'Retry manuscript\n');f.manuscript.status='initial_editing';f.db.commit();f.current=eic
        migrate_current_distribution(f.db_path);private=f.root/'private-retry';private.mkdir(mode=0o700)
        with patch.object(distribution,'DATA_ROOT',f.root.resolve()),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            data=f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates').json();inv=data['recipients'][0]
            payload={'invitation_kind':inv['invitation_kind'],'invitation_id':inv['invitation_id'],'source_sha256':data['document']['sha256'],'idempotency_key':'transaction-retry-key-123'}
            with sqlite3.connect(f.db_path) as db:
                db.execute("CREATE TRIGGER fail_distribution_notification BEFORE INSERT ON notifications WHEN NEW.notification_type='document_distributed' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            result=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=payload)
            assert result.status_code==503
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()[0]==0
                assert db.execute('SELECT COUNT(*) FROM distribution_artifacts').fetchone()[0]==0
                assert db.execute('SELECT COUNT(*) FROM distribution_reservations').fetchone()[0]==1
                db.execute('DROP TRIGGER fail_distribution_notification')
            assert len([p for p in private.iterdir() if not p.name.startswith('.')])==1
            retry=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=payload)
            assert retry.status_code==200,retry.text
            assert len(f.client.get(f'/document-distribution/manuscripts/{f.mid}/history').json())==1
    finally: f.tearDown()
