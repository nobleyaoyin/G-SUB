"""Migration and human verification guards, using disposable Sprint 7 fixtures."""
import importlib
import sqlite3
import pytest
from test_batch38_eic_proof import fixture
from test_batch40_reviewer_candidates import ready, CHECKS
from test_sprint7_candidate_provenance import submit

migration = importlib.import_module('migrations.038_candidate_preparation_provenance')


def test_migration_preserves_existing_data_and_is_idempotent(fixture):
    f, chief, headers, _, _, _, _ = ready(fixture)
    with sqlite3.connect(f.db_path) as db:
        before = db.execute('select count(*) from reviewer_candidate_reservations').fetchone()[0]
    migration.migrate(f.db_path)
    migration.migrate(f.db_path)
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('select count(*) from reviewer_candidate_reservations').fetchone()[0] == before
        assert db.execute('select count(*) from candidate_preparation_events').fetchone()[0] == 0
        assert not db.execute('pragma foreign_key_check').fetchall()
        assert db.execute('select count(*) from schema_migrations where migration_id=?', (migration.MIGRATION_ID,)).fetchone()[0] == 1


def test_prepared_candidate_requires_matching_context_and_filename(fixture):
    f, chief, headers, aid, sid, _, _ = ready(fixture)
    migration.migrate(f.db_path)
    result = submit(f, chief, headers, sid)
    assert result.status_code == 201
    cid = result.json()['candidate_id']
    base = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{cid}'
    info = f.client.get(base+'/processing', headers=headers(chief)).json()
    ctx = {'expected_sha256':info['prepared_sha256'], 'expected_artifact_version':info['artifact_version'], 'expected_review_round':info['review_round']}
    checks = {**CHECKS, **ctx, 'filename_verified':True}
    assert f.client.post(base+'/verify', headers=headers(f.reviewer), json=checks).status_code == 403
    assert f.client.post(base+'/approve', headers=headers(f.author), json={**ctx,'confirmed':True}).status_code == 403
    assert f.client.post(base+'/reject', headers=headers(f.author), json={'reason':'x'}).status_code == 403
    assert f.client.post(base+'/verify', headers=headers(chief), json={**checks,'author_names':False}).status_code == 422
    assert f.client.post(base+'/verify', headers=headers(chief), json={**checks,'filename_verified':False}).status_code == 422
    assert f.client.post(base+'/verify', headers=headers(chief), json={**checks,'expected_sha256':'0'*64}).status_code == 409
    assert f.client.post(base+'/verify', headers=headers(chief), json={**checks,'expected_review_round':2}).status_code == 409
    assert f.client.post(base+'/verify', headers=headers(chief), json={**checks,'expected_artifact_version':99}).status_code == 409
    assert f.client.post(base.replace(f'/manuscripts/{f.mid}/', f'/manuscripts/{f.mid+1}/')+'/verify', headers=headers(chief), json=checks).status_code in (404,409)
    assert f.client.post(base+'/approve', headers=headers(chief), json={**ctx,'confirmed':True}).status_code == 409
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 409
    assert f.client.post(base+'/verify', headers=headers(chief), json=checks).status_code == 200
    assert f.client.post(base+'/approve', headers=headers(chief), json={**ctx,'confirmed':False}).status_code == 409
    assert f.client.post(base+'/approve', headers=headers(chief), json={**ctx,'confirmed':True}).status_code == 200
    info = f.client.get(base+'/processing',headers=headers(chief)).json()
    assert info['filename_verification']['status'] == 'verified'
    assert info['human_review']['status'] == 'verified' and info['approval']['status'] == 'approved'
    with sqlite3.connect(f.db_path) as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute('update candidate_filename_verifications set artifact_version=2')
        with pytest.raises(sqlite3.IntegrityError): db.execute('delete from candidate_filename_verifications')


def test_migration_rejects_conflicts_and_wrong_provenance_bindings(fixture):
    from test_sprint6_docx_preparation import word_document
    f, chief, headers, _, sid, _, _ = ready(fixture)
    old = f.client.post(f'/eic/manuscripts/{f.mid}/reviewer-candidates', headers=headers(chief),
        data={'review_round':1, 'source_id':sid, 'artifact_version':1, 'fmt':'docx'},
        files={'file':('manual.docx', word_document(), 'application/octet-stream')})
    assert old.status_code == 201
    cid = old.json()['candidate_id']
    migration.migrate(f.db_path)
    with sqlite3.connect(f.db_path) as db:
        db.execute('pragma foreign_keys=on')
        reservation = db.execute('select manuscript_id,review_round,source_id,sha256,prepared_by from reviewer_candidate_reservations where candidate_id=?', (cid,)).fetchone()
        source_sha = db.execute('''select s.sha256 from reviewer_candidate_reservations r
            join eic_prospective_proofs p on p.proof_id=r.proof_id
            join eic_proof_reservations s on s.storage_id=p.storage_id where r.candidate_id=?''', (cid,)).fetchone()[0]
        mid, rnd, source, digest, actor = reservation
        # Each changed association is tested independently against a valid DOCX reservation.
        values = (cid, mid, rnd, source, source_sha, 'a'*64, digest, 'docx-v1', actor, '2026-01-01', 'prepared', 'unverified', 'pending')
        for index, replacement in ((1,mid+1),(2,rnd+1),(4,'0'*64)):
            invalid=list(values); invalid[index]=replacement
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('insert into candidate_preparation_events values (?,?,?,?,?,?,?,?,?,?,?,?,?)',invalid)
            db.rollback()
        assert db.execute('select count(*) from candidate_preparation_events').fetchone()[0] == 0
        assert db.execute('select count(*) from reviewer_candidate_publications where candidate_id=?', (cid,)).fetchone()[0] == 1


def test_migration_conflict_rolls_back_without_record(fixture):
    f, _, _, _, _, _, _ = ready(fixture)
    with sqlite3.connect(f.db_path) as db:
        db.execute('create table candidate_filename_verifications (conflicting text)')
    with pytest.raises(RuntimeError):
        migration.migrate(f.db_path)
    with sqlite3.connect(f.db_path) as db:
        assert not db.execute('select 1 from schema_migrations where migration_id=?', (migration.MIGRATION_ID,)).fetchone()
        assert not db.execute("select 1 from sqlite_master where name='candidate_preparation_events'").fetchone()
        assert not db.execute('pragma foreign_key_check').fetchall()


def test_prepared_candidate_changed_after_verification_cannot_be_approved(fixture):
    f, chief, headers, _, sid, _, private = ready(fixture)
    migration.migrate(f.db_path)
    created = submit(f, chief, headers, sid)
    assert created.status_code == 201
    cid = created.json()['candidate_id']
    base = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{cid}'
    info = f.client.get(base+'/processing', headers=headers(chief)).json()
    ctx = {'expected_sha256':info['prepared_sha256'], 'expected_artifact_version':info['artifact_version'], 'expected_review_round':info['review_round']}
    assert f.client.post(base+'/verify', headers=headers(chief), json={**CHECKS, **ctx, 'filename_verified':True}).status_code == 200
    candidate_file = private / cid
    candidate_file.chmod(0o600)
    candidate_file.write_bytes(b'changed synthetic candidate')
    candidate_file.chmod(0o400)
    assert f.client.post(base+'/approve', headers=headers(chief), json={**ctx,'confirmed':True}).status_code in (409,503)
    assert f.client.post(base+'/publish', headers=headers(chief)).status_code in (409,503)


def test_release_rechecks_rejection_even_if_approval_is_forged(fixture):
    f, chief, headers, aid, sid, _, _ = ready(fixture)
    migration.migrate(f.db_path)
    created = submit(f, chief, headers, sid)
    assert created.status_code == 201
    cid = created.json()['candidate_id']
    base = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{cid}'
    info = f.client.get(base+'/processing', headers=headers(chief)).json()
    ctx = {'expected_sha256':info['prepared_sha256'], 'expected_artifact_version':info['artifact_version'], 'expected_review_round':info['review_round']}
    assert f.client.post(base+'/verify', headers=headers(chief), json={**CHECKS, **ctx, 'filename_verified':True}).status_code == 200
    assert f.client.post(base+'/reject', headers=headers(chief), json={'reason':'synthetic identifying text'}).status_code == 200
    # Deliberate synthetic database forgery tests defense in depth; it is not a workflow transition.
    with sqlite3.connect(f.db_path) as db:
        db.execute('insert into reviewer_candidate_approvals values (?,?,?,?,?)', (cid,chief.user_id,'2026-01-01',ctx['expected_sha256'],ctx['expected_artifact_version']))
    assert f.client.post(base+'/publish', headers=headers(chief)).status_code == 409
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 409
