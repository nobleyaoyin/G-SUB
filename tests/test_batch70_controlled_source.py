"""Synthetic HTTP coverage for the initial controlled-source integration."""
from tests.batch83_migration_support import bootstrap_prospective_distribution
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch
import pytest

from app.routers import document_distribution as distribution, eic
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migration as manual
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch67_auto_migration import auto
from tests.test_batch17b_distribution_migration import database
from tests import test_final_workflow as final_fixtures

spec = importlib.util.spec_from_file_location('migration26', Path(__file__).resolve().parents[1]/'migrations/026_controlled_source_policy.py')
policy_migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy_migration)
provenance_spec = importlib.util.spec_from_file_location('migration27', Path(__file__).resolve().parents[1]/'migrations/027_source_grant_provenance.py')
provenance_migration = importlib.util.module_from_spec(provenance_spec)
provenance_spec.loader.exec_module(provenance_migration)


def test_initial_editor_manual_policy_legacy_grant_and_revocation():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f)
        manual.migrate(f.db_path);auto.migrate(f.db_path);policy_migration.migrate(f.db_path);policy_migration.migrate(f.db_path);provenance_migration.migrate(f.db_path);bootstrap_prospective_distribution(f.db_path)
        private=f.root/'batch70-private';private.mkdir(mode=0o700)
        with patch.object(distribution,'DATA_ROOT',f.root),patch.object(eic,'BASE_DIR',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=f.editor
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            original=b'Synthetic batch 22 bytes\n'
            assert f.client.get(f'/manuscripts/{mid}/download').content==original
            digest=hashlib.sha256(original).hexdigest()
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch70-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2026-01-01T00:00:00.000000Z','initial_enrollment'))
                db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch70-event'))
                db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('batch70-policy',mid,'initial','manual','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt',digest,1,chief.user_id,'2026-01-01T00:00:00Z'))
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').status_code==403
            assert f.client.get(f'/eic/manuscripts/{mid}/online-text/initial').status_code==403
            f.current=chief
            grant=f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json={'invitation_kind':'initial','invitation_id':iid,'source_sha256':digest,'idempotency_key':'batch70-manual-key-0001'})
            assert grant.status_code==200,grant.text
            gid=grant.json()['grant_id'];f.current=f.editor
            assert f.client.get(f'/manuscripts/{mid}/download').content==original
            assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').content==original
            assert f.client.get(f'/eic/manuscripts/{mid}/online-text/initial').json()['content'].encode()==original
            assert f.client.get(f'/document-distribution/grants/{gid}/download').content==original
            from app.controlled_source_authorization import authorize_source
            def replace_after_authorization(*args, **kwargs):
                decision=authorize_source(*args, **kwargs)
                (f.root/f'uploads/manuscripts/{mid}/paper.txt').write_bytes(b'Replaced after authorization\n')
                return decision
            with patch('app.routers.manuscripts.authorize_source', side_effect=replace_after_authorization):
                assert f.client.get(f'/manuscripts/{mid}/download').content==original
            (f.root/f'uploads/manuscripts/{mid}/paper.txt').write_bytes(original)
            (f.root/f'uploads/manuscripts/{mid}/paper.txt').write_bytes(b'Changed synthetic document\n')
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            (f.root/f'uploads/manuscripts/{mid}/paper.txt').write_bytes(original)
            from app.models import Manuscript
            manuscript=f.db.get(Manuscript,mid)
            manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/next.txt',b'New synthetic version\n')
            f.db.commit()
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').status_code==403
            manuscript.file_path=f'uploads/manuscripts/{mid}/paper.txt';f.db.commit()
            f.current=chief
            assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic'}).status_code==200
            f.current=f.editor
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').status_code==403
            assert f.client.get(f'/eic/manuscripts/{mid}/online-text/initial').status_code==403
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO controlled_source_policy_revocations VALUES(?,?,?,?)',('batch70-policy',chief.user_id,'Synthetic','2026-01-02T00:00:00.000000Z'))
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('batch70-auto',mid,'initial','automatic','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt',digest,2,chief.user_id,'2026-01-02T00:00:00.000000Z'))
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
    finally:f.tearDown()


def test_migration_reapplication_exclusive_policy_and_retained_evidence(database):
    manual.migrate(database);auto.migrate(database);policy_migration.migrate(database);policy_migration.migrate(database)
    policy_migration.downgrade_empty(database);policy_migration.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        record=('policy-1',1,'initial','manual','current_author_manuscript','uploads/manuscripts/1/paper.txt','a'*64,1,1,'2026-01-01T00:00:00.000000Z')
        db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',record)
        with pytest.raises(sqlite3.IntegrityError,match='Active policy exists'):
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('policy-2',1,'initial','automatic','current_author_manuscript','uploads/manuscripts/1/paper.txt','a'*64,2,1,'2026-01-02T00:00:00.000000Z'))
        with pytest.raises(sqlite3.IntegrityError,match='immutable'):
            db.execute("UPDATE controlled_source_policies SET mode='automatic'")
        db.execute('INSERT INTO controlled_source_policy_revocations VALUES(?,?,?,?)',('policy-1',1,'Synthetic','2026-01-02T00:00:00.000000Z'))
        db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('policy-2',1,'initial','automatic','current_author_manuscript','uploads/manuscripts/1/paper.txt','a'*64,2,1,'2026-01-02T00:00:00.000000Z'))
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        db.commit()
    with pytest.raises(RuntimeError,match='retained'):
        policy_migration.downgrade_empty(database)


def test_final_editor_controlled_manual_download_and_revocation():
    f=final_fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
            iid=invitation.json()['invitation_id'];assert f.respond(f.editor,iid,'accept').status_code==200
            original=b'Synthetic final controlled document\n';ref=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',original)
            f.manuscript.file_path=ref;f.db.commit()
            manual.migrate(f.db_path);auto.migrate(f.db_path);policy_migration.migrate(f.db_path);provenance_migration.migrate(f.db_path);bootstrap_prospective_distribution(f.db_path)
            private=f.root/'batch70-final-private';private.mkdir(mode=0o700)
            with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
                f.current=f.editor
                assert f.client.get(f'/manuscripts/{f.mid}/download').content==original
                digest=hashlib.sha256(original).hexdigest()
                with sqlite3.connect(f.db_path) as db:
                    db.execute('PRAGMA foreign_keys=ON')
                    db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch70-final-event',f.editor.user_id,1,None,'active',1,f.chief.user_id,'2026-01-01T00:00:00.000000Z','initial_enrollment'))
                    db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch70-final-event'))
                    db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('batch70-final-policy',f.mid,'final','manual','current_author_manuscript',ref,digest,1,f.chief.user_id,'2026-01-01T00:00:00.000000Z'))
                assert f.client.get(f'/manuscripts/{f.mid}/download').status_code==403
                f.current=f.chief
                grant=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json={'invitation_kind':'final','invitation_id':iid,'source_sha256':digest,'idempotency_key':'batch70-final-key-00001'})
                assert grant.status_code==200,grant.text
                gid=grant.json()['grant_id'];f.current=f.editor
                assert f.client.get(f'/manuscripts/{f.mid}/download').content==original
                assert f.client.get(f'/manuscripts/{f.mid}/versions/paper.txt').content==original
                f.current=f.chief
                assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic'}).status_code==200
                f.current=f.editor
                assert f.client.get(f'/manuscripts/{f.mid}/download').status_code==403
                assert f.client.get(f'/manuscripts/{f.mid}/versions/paper.txt').status_code==403
    finally:f.tearDown()
