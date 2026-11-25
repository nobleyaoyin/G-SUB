"""Local enrollment safety against disposable SQLite and storage only."""
import importlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from scripts import enroll_sample_manuscript as enrollment
from app.sample_storage import SampleStorage, SampleStorageError


@pytest.fixture
def sample_root(tmp_path):
    root = tmp_path.resolve()
    assert root.is_relative_to(Path(os.environ['TMPDIR']).resolve())
    assert not root.is_relative_to(Path(__file__).resolve().parents[1])
    db_path = root / 'manuscript.db'
    with sqlite3.connect(db_path) as db:
        db.executescript('''CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES ('fixture',datetime('now'));
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, role TEXT NOT NULL);
        CREATE TABLE manuscripts (manuscript_id INTEGER PRIMARY KEY, author_id INTEGER, status TEXT,
          file_path TEXT, review_round INTEGER, FOREIGN KEY(author_id) REFERENCES users(user_id));
        CREATE TABLE history (id INTEGER PRIMARY KEY, manuscript_id INTEGER REFERENCES manuscripts(manuscript_id));
        INSERT INTO users VALUES (1,'author'); INSERT INTO users VALUES (2,'editor');
        INSERT INTO manuscripts VALUES (10,1,'draft',NULL,1);''')
    importlib.import_module('migrations.035_sample_document_storage').migrate(db_path)
    return root, db_path


def records(root):
    return [json.loads(line) for line in (root / enrollment.AUDIT_NAME).read_text().splitlines()]


def test_empty_draft_registration_is_audited_and_duplicate_rejected(sample_root):
    root, db = sample_root
    result = enrollment._enroll(db, root, 10)
    assert result['outcome'] == 'registered' and result['author_id'] == 1
    assert result['storage_namespace'] == 'sample:v1/manuscripts/10/'
    with sqlite3.connect(db) as conn:
        assert conn.execute('select manuscript_id,registered_at from sample_manuscripts').fetchall() == [(10, result['registered_at'])]
    events = records(root)
    assert [event['outcome'] for event in events] == ['started', 'prepared', 'registered']
    assert events[-1]['operator_context'] == {'kind': 'local_os_uid', 'uid': os.geteuid()}
    assert not (root / 'uploads').exists() and not (root / '.gsub_sample_storage').exists()
    with pytest.raises(enrollment.EnrollmentError, match='already registered'):
        enrollment._enroll(db, root, 10)
    assert records(root)[-1]['outcome'] == 'rejected'
    with sqlite3.connect(db) as conn:
        assert conn.execute('select count(*) from sample_manuscripts').fetchone()[0] == 1


@pytest.mark.parametrize('mutation,match', [
    ("UPDATE manuscripts SET status='submitted'", 'empty first-round draft'),
    ("UPDATE manuscripts SET file_path='uploads/legacy.pdf'", 'empty first-round draft'),
    ("UPDATE manuscripts SET review_round=2", 'empty first-round draft'),
    ("UPDATE manuscripts SET author_id=2", 'Author owner'),
    ("INSERT INTO history VALUES (1,10)", 'existing related records'),
    ("CREATE TABLE artifact (manuscript_id INTEGER); INSERT INTO artifact VALUES (10)", 'existing related records'),
])
def test_ineligible_state_rejected_without_partial_registration(sample_root, mutation, match):
    root, db = sample_root
    with sqlite3.connect(db) as conn: conn.executescript(mutation)
    with pytest.raises(enrollment.EnrollmentError, match=match): enrollment._enroll(db, root, 10)
    with sqlite3.connect(db) as conn: assert conn.execute('select count(*) from sample_manuscripts').fetchone()[0] == 0
    assert records(root)[-1]['outcome'] == 'rejected'


def test_reserved_missing_and_invalid_owner_fail_closed(sample_root):
    root, db = sample_root
    for mid in (enrollment.RESERVED_ID, 999):
        with pytest.raises(enrollment.EnrollmentError): enrollment._enroll(db, root, mid)
    with sqlite3.connect(db) as conn: conn.execute('UPDATE manuscripts SET author_id=999')
    with pytest.raises(enrollment.EnrollmentError): enrollment._enroll(db, root, 10)
    with sqlite3.connect(db) as conn: assert conn.execute('select count(*) from sample_manuscripts').fetchone()[0] == 0


def test_rollback_on_audit_failure(sample_root, monkeypatch):
    root, db = sample_root
    original = enrollment._record
    def fail_prepared(fd, value):
        if value['outcome'] == 'prepared': raise OSError('synthetic audit failure')
        return original(fd, value)
    monkeypatch.setattr(enrollment, '_record', fail_prepared)
    with pytest.raises(OSError): enrollment._enroll(db, root, 10)
    with sqlite3.connect(db) as conn: assert conn.execute('select count(*) from sample_manuscripts').fetchone()[0] == 0
    assert records(root)[-1]['outcome'] == 'rejected'


def test_symlinks_and_storage_configuration_fail_closed(sample_root, tmp_path):
    root, db = sample_root
    (root / 'uploads').symlink_to(root / 'elsewhere', target_is_directory=True)
    with pytest.raises(SampleStorageError): enrollment._enroll(db, root, 10)
    with sqlite3.connect(db) as conn: assert conn.execute('select count(*) from sample_manuscripts').fetchone()[0] == 0
    # A root changed to a symlink after construction is rejected before writing.
    base = tmp_path / 'later'; base.mkdir()
    store = SampleStorage(base / 'samples', base / 'uploads')
    (base / 'uploads').symlink_to(base / 'samples', target_is_directory=True)
    with pytest.raises(SampleStorageError): store.write_new('sample:v1/manuscripts/1/file.txt', b'private')
    assert not (base / 'samples').exists()


def test_cli_refuses_without_all_confirmations(monkeypatch):
    def never(*args, **kwargs): raise AssertionError('must not open database')
    monkeypatch.setattr(enrollment, '_enroll', never)
    monkeypatch.delenv('MANUSCRIPT_MODE', raising=False)
    with pytest.raises(SystemExit): enrollment.main(['--manuscript-id','10','--confirm-manuscript-id','10','--confirm-main-development','--confirm-application-stopped'])
    monkeypatch.setenv('MANUSCRIPT_MODE', 'development')
    with pytest.raises(SystemExit): enrollment.main(['--manuscript-id','10','--confirm-manuscript-id','11','--confirm-main-development','--confirm-application-stopped'])
    with pytest.raises(SystemExit): enrollment.main(['--manuscript-id','10','--confirm-manuscript-id','10','--confirm-main-development'])


def test_real_operator_command_in_disposable_development(sample_root):
    import shutil
    import subprocess
    import sys
    root, db = sample_root
    project = Path(__file__).resolve().parents[1]
    for directory in ('scripts', 'app', 'migrations'):
        (root / directory).mkdir()
    shutil.copyfile(project / 'scripts/enroll_sample_manuscript.py', root / 'scripts/enroll_sample_manuscript.py')
    shutil.copyfile(project / 'scripts/maintenance_participation.py', root / 'scripts/maintenance_participation.py')
    shutil.copyfile(project / 'app/sample_storage.py', root / 'app/sample_storage.py')
    shutil.copyfile(project / 'app/maintenance_barrier.py', root / 'app/maintenance_barrier.py')
    shutil.copyfile(project / 'app/config.py', root / 'app/config.py')
    shutil.copyfile(project / 'migrations/035_sample_document_storage.py', root / 'migrations/035_sample_document_storage.py')
    shutil.copyfile(project / 'migrations/_target_safety.py', root / 'migrations/_target_safety.py')
    env = os.environ.copy()
    env['MANUSCRIPT_MODE'] = 'development'
    completed = subprocess.run([sys.executable, str(root / 'scripts/enroll_sample_manuscript.py'),
        '--manuscript-id', '10', '--confirm-manuscript-id', '10',
        '--confirm-main-development', '--confirm-application-stopped'], cwd=root, env=env,
        capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)['outcome'] == 'registered'
    assert records(root)[-1]['outcome'] == 'registered'
    with sqlite3.connect(db) as conn:
        assert conn.execute('select manuscript_id from sample_manuscripts').fetchall() == [(10,)]


def test_preexisting_sample_namespace_is_never_adopted(sample_root):
    root, db = sample_root
    sample = root / '.gsub_sample_storage'
    sample.mkdir(mode=0o700)
    (sample / 'manuscripts').mkdir(mode=0o700)
    (sample / 'manuscripts' / '10').mkdir(mode=0o700)
    with pytest.raises(enrollment.EnrollmentError, match='namespace already exists'):
        enrollment._enroll(db, root, 10)
    with sqlite3.connect(db) as conn:
        assert conn.execute('select count(*) from sample_manuscripts').fetchone()[0] == 0
    assert records(root)[-1]['outcome'] == 'rejected'


def test_cli_rejects_non_development_before_importing_configuration():
    import subprocess
    import sys
    env = os.environ.copy()
    env['MANUSCRIPT_MODE'] = 'demo'
    env.pop('MANUSCRIPT_DEMO_ROOT', None)
    script = Path(__file__).resolve().parents[1] / 'scripts/enroll_sample_manuscript.py'
    result = subprocess.run([sys.executable, str(script), '--help'], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'only in development mode' in result.stderr
    assert 'demo root' not in result.stderr.lower()
