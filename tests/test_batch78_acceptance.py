"""Disposable same-source stage race and recovery checks."""
import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from fastapi import HTTPException

from app.automatic_distribution_processor import process_intent
from app.routers import document_distribution as distribution, eic
from tests import test_final_workflow as fixtures
from tests.test_batch73_acceptance_intents import install
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch75_automatic_processor import processing_migration


def test_same_source_cross_stage_intents_only_current_stage_can_grant():
    # The original final-stage fixture contained completed review records before
    # its synthetic Initial acceptance, so it cannot establish pre-review round
    # evidence. Reuse the migrated same-source concurrent HTTP/processor scenario
    # with a genuine pre-review starting fixture and an explicit later transition.
    from tests.test_batch83_round_binding import test_concurrent_initial_final_same_source_respects_current_round
    test_concurrent_initial_final_same_source_respects_current_round()


def test_reservation_failure_then_safe_retry():
    import pytest
    from tests.test_batch77_recovery import pending
    with pending() as (f,chief,mid,iid,policy,intent):
        with sqlite3.connect(f.db_path) as db:
            db.execute("CREATE TRIGGER batch78_fail_reservation BEFORE INSERT ON distribution_reservations BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with f.Session() as session:
            with pytest.raises(HTTPException) as exc: process_intent(session,intent)
            assert exc.value.status_code==503
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            assert db.execute('SELECT state FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('failed',)
            db.execute('DROP TRIGGER batch78_fail_reservation')
        with f.Session() as session: result=process_intent(session,intent)
        assert result['status']=='granted'
        with f.Session() as session: assert process_intent(session,intent)['grant_id']==result['grant_id']


def test_publication_failure_then_safe_retry():
    import pytest
    from app.reviewer_artifact_storage import ArtifactStorage
    from tests.test_batch77_recovery import pending
    with pending() as (f,chief,mid,iid,policy,intent):
        with patch.object(ArtifactStorage,'publish_reserved',side_effect=OSError('synthetic publication failure')):
            with f.Session() as session:
                with pytest.raises(HTTPException) as exc: process_intent(session,intent)
                assert exc.value.status_code==503
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
        f.current=f.editor;assert f.client.get('/document-distribution/my').json()==[]
        with f.Session() as session: result=process_intent(session,intent)
        assert result['status']=='granted'
        assert f.client.get(f"/document-distribution/grants/{result['grant_id']}/download").content==b'Synthetic batch 22 bytes\n'


def test_separate_process_crash_and_restart_recovers_expired_lease():
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    from tests.test_batch77_recovery import pending
    with pending() as (f,chief,mid,iid,policy,intent):
        root=Path(__file__).resolve().parents[1]
        program=textwrap.dedent('''
            import os,sys,time
            from pathlib import Path
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from app.routers import document_distribution as distribution
            from app.automatic_distribution_processor import process_intent
            from app.reviewer_artifact_storage import ArtifactStorage
            import app.automatic_distribution_processor as processor
            distribution.DATA_ROOT=Path(sys.argv[1])
            engine=create_engine('sqlite:///'+sys.argv[2],connect_args={'timeout':10})
            if sys.argv[4]=='crash':
                original=ArtifactStorage.publish_reserved
                def crash(store,*a,**k):
                    original(store,*a,**k)
                    os._exit(77)
                ArtifactStorage.publish_reserved=crash
            else:
                current=time.time_ns()
                processor.time.time_ns=lambda:current+120_000_000_000
            with Session(engine) as db:
                print(process_intent(db,sys.argv[3])['status'],flush=True)
        ''')
        args=[sys.executable,'-c',program,str(f.root),str(f.db_path),intent]
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        crashed=subprocess.run(args+['crash'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert crashed.returncode==77,crashed.stderr
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
        recovered=subprocess.run(args+['recover'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert recovered.returncode==0,recovered.stderr
        assert recovered.stdout.strip()=='granted'
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)
