"""Conservative reconciliation against isolated synthetic data only."""
import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text

from app import models
from app.manuscript_upload_reconciliation import inspect_manuscript_uploads
from tests import test_reviewer_download as fixtures


@pytest.fixture
def case():
    fixture = fixtures.ReviewerDownloadsTest();fixture.setUp()
    try:
        for name in ('041_author_submission_drafts','042_author_submission_linkage','043_author_submission_attachments','044_manuscript_upload_names','045_manuscript_upload_requests'):
            importlib.import_module('migrations.' + name).migrate(fixture.db_path)
        manuscript=models.Manuscript(title='Synthetic',abstract='Synthetic',author_id=fixture.author.user_id,status='draft',review_round=1)
        fixture.db.add(manuscript);fixture.db.commit();fixture.mid=manuscript.manuscript_id;fixture.current=fixture.author
        yield fixture
    finally:
        fixture.tearDown()


def upload(case, data=b'synthetic content'):
    request_id=str(uuid4())
    response=case.client.post(f'/manuscripts/{case.mid}/upload',data={'request_id':request_id},files={'file':('file.txt',data,'text/plain')})
    assert response.status_code==200,response.text
    return request_id


def inspect(case, mid=None):
    with case.Session() as session:
        return inspect_manuscript_uploads(session,case.root,mid or case.mid)


def test_dry_run_preserves_recorded_and_indeterminate_legacy_files(case):
    request_id=upload(case)
    directory=case.root/'uploads'/'manuscripts'/str(case.mid)
    legacy=directory/'older-unrecorded.txt';legacy.write_bytes(b'legacy version')
    before={p.name:p.read_bytes() for p in directory.iterdir()}
    first=inspect(case);second=inspect(case)
    assert first==second
    assert first['recorded']==[{'request_id':request_id,'state':'verified'}]
    assert first['current']=='present' and len(first['indeterminate_versions'])==1
    assert first['cleanup_available'] is False
    assert {p.name:p.read_bytes() for p in directory.iterdir()}==before
    with case.Session() as session:
        with pytest.raises(TypeError):
            inspect_manuscript_uploads(session,case.root,case.mid,cleanup=True)
    assert {p.name:p.read_bytes() for p in directory.iterdir()}==before


def test_missing_and_tampered_recorded_files_are_never_cleanup_candidates(case):
    request_id=upload(case)
    path=case.root/case.db.get(models.Manuscript,case.mid).file_path
    path.write_bytes(b'changed')
    assert inspect(case)['recorded']==[{'request_id':request_id,'state':'integrity_mismatch'}]
    path.unlink()
    result=inspect(case)
    assert result['recorded']==[{'request_id':request_id,'state':'missing'}]
    assert result['current']=='missing' and result['cleanup_available'] is False


def test_other_manuscript_and_symlink_are_not_followed(case):
    upload(case)
    other=models.Manuscript(title='Other',abstract='Synthetic',author_id=case.author.user_id,status='draft',review_round=1)
    case.db.add(other);case.db.commit()
    other_dir=case.root/'uploads'/'manuscripts'/str(other.manuscript_id);other_dir.mkdir(parents=True)
    outside=other_dir/'other.txt';outside.write_bytes(b'other manuscript')
    directory=case.root/'uploads'/'manuscripts'/str(case.mid)
    (directory/'linked.txt').symlink_to(outside)
    result=inspect(case)
    assert result['unsafe_entries']==1 and outside.read_bytes()==b'other manuscript'
    assert result['cleanup_available'] is False


def test_audit_waits_for_concurrent_sqlite_writer(case):
    upload(case)
    ready=threading.Event()
    def audit():
        ready.set()
        return inspect(case)
    with case.Session() as lock, ThreadPoolExecutor(max_workers=1) as pool:
        lock.execute(text('BEGIN IMMEDIATE'))
        future=pool.submit(audit)
        assert ready.wait(2)
        time.sleep(.15)
        assert not future.done()
        lock.rollback()
        assert future.result(timeout=5)['recorded'][0]['state']=='verified'
