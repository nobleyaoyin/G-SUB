"""Disposable acceptance-intent tests: no automatic grant or delivery."""
from tests.batch83_migration_support import bootstrap_prospective_distribution
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from unittest.mock import patch
from fastapi import HTTPException

from app.routers import eic
from tests import test_reviewer_download as fixtures, test_final_workflow as final_fixtures
from tests.test_batch17b_distribution_migration import database, migration as manual
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch67_auto_migration import auto
from tests.test_batch70_controlled_source import policy_migration, provenance_migration

spec=importlib.util.spec_from_file_location('migration28',Path(__file__).resolve().parents[1]/'migrations/028_automatic_distribution_intents.py')
intent_migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(intent_migration)


def install(path):
    manual.migrate(path);auto.migrate(path);policy_migration.migrate(path);provenance_migration.migrate(path);intent_migration.migrate(path)


def test_migration_reapplication_empty_rollback(database):
    install(database);intent_migration.migrate(database)
    intent_migration.downgrade_empty(database);intent_migration.migrate(database)
    with sqlite3.connect(database) as db: assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_initial_acceptance_records_pending_intent_without_grant():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);bootstrap_prospective_distribution(f.db_path)
        ref=f'uploads/manuscripts/{mid}/paper.txt';digest=hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest()
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('a'*32,mid,'initial','automatic','current_author_manuscript',ref,digest,1,chief.user_id,'2020-01-01T00:00:00.000000Z'))
        f.current=f.editor
        with patch('app.automatic_distribution_intents.process_after_acceptance'):
            response=f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'})
        assert response.status_code==200,response.text
        assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==409
        assert f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').status_code==403
        with sqlite3.connect(f.db_path) as db:
            row=db.execute('SELECT policy_id,invitation_kind,invitation_id,recipient_id,source_ref,source_sha256 FROM controlled_automatic_intents').fetchone()
            assert row==('a'*32,'initial',iid,f.editor.user_id,ref,digest)
            assert db.execute('SELECT state FROM controlled_automatic_events').fetchone()==('pending',)
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE controlled_automatic_intents SET source_ref=?',('other',))
        with pytest.raises(RuntimeError,match='retained'): intent_migration.downgrade_empty(f.db_path)
        f.current=chief;history=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents')
        assert history.status_code==200,history.text
        assert len(history.json())==1 and history.json()[0]['state']=='pending'
        assert 'source_ref' not in history.json()[0]
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies/{"a"*32}/revoke',json={'reason':'Synthetic'}).status_code==200
        assert f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()[0]['state']=='revoked'
    finally:f.tearDown()


def test_final_acceptance_records_pending_intent_without_bypassing_agreement():
    f=final_fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
            iid=invitation.json()['invitation_id'];content=b'Synthetic final source\n'
            ref=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',content)
            f.manuscript.file_path=ref;f.db.commit();install(f.db_path);bootstrap_prospective_distribution(f.db_path)
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('b'*32,f.mid,'final','automatic','current_author_manuscript',ref,hashlib.sha256(content).hexdigest(),1,f.chief.user_id,'2020-01-01T00:00:00.000000Z'))
            response=f.respond(f.editor,iid,'accept');assert response.status_code==200,response.text
            assert f.respond(f.editor,iid,'accept').status_code==409
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT invitation_kind,invitation_id,recipient_id FROM controlled_automatic_intents').fetchone()==('final',iid,f.editor.user_id)
                assert db.execute('SELECT state FROM controlled_automatic_events').fetchone()==('pending',)
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
    finally:f.tearDown()


def test_broken_optional_intent_schema_does_not_undo_valid_acceptance():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path)
        with sqlite3.connect(f.db_path) as db:
            db.execute('DROP TRIGGER controlled_automatic_intents_no_update')
        f.current=f.editor
        response=f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'})
        assert response.status_code==200,response.text
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT status FROM initial_editor_invitations WHERE invitation_id=?',(iid,)).fetchone()==('accepted',)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(0,)
    finally:f.tearDown()


def test_policy_added_after_acceptance_does_not_create_retroactive_intent():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);f.current=f.editor
        assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('c'*32,mid,'initial','automatic','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt',hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest(),1,chief.user_id,'2020-01-01T00:00:00.000000Z'))
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(0,)
    finally:f.tearDown()


def test_concurrent_initial_acceptance_records_at_most_one_intent():
    from app.models import User
    from app.schemas import InitialEditorInvitationDecision
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);bootstrap_prospective_distribution(f.db_path)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('d'*32,mid,'initial','automatic','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt',hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest(),1,chief.user_id,'2020-01-01T00:00:00.000000Z'))
        barrier=Barrier(2)
        def respond():
            with f.Session() as session:
                actor=session.get(User,f.editor.user_id);barrier.wait()
                try:
                    return eic.respond_initial_editor_invitation(iid,InitialEditorInvitationDecision(decision='accept'),actor,session).status
                except HTTPException as exc:
                    session.rollback();return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:respond(),range(2)))
        assert sorted(str(x) for x in outcomes)==['409','accepted']
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_events').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
    finally:f.tearDown()
