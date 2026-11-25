"""Synthetic Manual policy activation and exact-source grant evidence."""
from tests.batch83_migration_support import bootstrap_prospective_distribution
import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import pytest

from app.routers import document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch17b_distribution_migration import database, migration as manual
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch67_auto_migration import auto
from tests.test_batch70_controlled_source import policy_migration, provenance_migration


def test_migration_reapplication_and_empty_rollback(database):
    manual.migrate(database);auto.migrate(database);policy_migration.migrate(database)
    provenance_migration.migrate(database);provenance_migration.migrate(database)
    with sqlite3.connect(database) as db: assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    provenance_migration.downgrade_empty(database);provenance_migration.migrate(database)


def test_manual_configuration_grant_provenance_and_revocation():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f)
        manual.migrate(f.db_path);auto.migrate(f.db_path);policy_migration.migrate(f.db_path);provenance_migration.migrate(f.db_path)
        private=f.root/'batch72-private';private.mkdir(mode=0o700)
        original=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(original).hexdigest()
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            path=f'/document-distribution/manuscripts/{mid}/policies'
            payload={'invitation_kind':'initial','mode':'manual','source_sha256':digest,'confirmed':True}
            assert f.client.post(path,json={**payload,'mode':'automatic'}).status_code==503
            bootstrap_prospective_distribution(f.db_path)
            assert f.client.post(path,json={**payload,'invitation_kind':'reviewer'}).status_code==422
            result=f.client.post(path,json=payload);assert result.status_code==201,result.text
            pid=result.json()['policy_id'];assert result.json()['version']==1
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch72-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2026-01-01T00:00:00.000000Z','initial_enrollment'))
                db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch72-event'))
            f.current=f.editor
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            f.current=chief
            grant_payload={'invitation_kind':'initial','invitation_id':iid,'source_sha256':digest,'idempotency_key':'batch72-request-key-0001'}
            from app.models import User
            barrier=Barrier(2)
            def grant_once():
                with f.Session() as session:
                    actor=session.get(User,chief.user_id);barrier.wait()
                    return distribution.create_grant(mid,distribution.GrantRequest(**grant_payload),actor,session)
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes=list(pool.map(lambda _:grant_once(),range(2)))
            assert outcomes[0]['grant_id']==outcomes[1]['grant_id']
            gid=outcomes[0]['grant_id']
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json=grant_payload).json()['grant_id']==gid
            with sqlite3.connect(f.db_path) as db:
                evidence=db.execute('SELECT policy_id,source_ref,source_sha256,recipient_id,invitation_id FROM controlled_source_grant_provenance WHERE grant_id=?',(gid,)).fetchone()
                assert evidence==(pid,f'uploads/manuscripts/{mid}/paper.txt',digest,f.editor.user_id,iid)
                with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE controlled_source_grant_provenance SET source_ref=?',('other',))
                with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM controlled_source_grant_provenance')
            with pytest.raises(RuntimeError,match='retained'): provenance_migration.downgrade_empty(f.db_path)
            f.current=f.editor
            assert f.client.get(f'/manuscripts/{mid}/download').content==original
            from app.models import Manuscript
            manuscript=f.db.get(Manuscript,mid)
            manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/same-bytes-other-version.txt',original);f.db.commit()
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            f.current=chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json={**grant_payload,'idempotency_key':'batch72-conflict-key-0002'}).status_code==409
            manuscript.file_path=f'uploads/manuscripts/{mid}/paper.txt';f.db.commit()
            f.current=chief
            assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic'}).status_code==200
            f.current=f.editor
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
    finally:f.tearDown()
