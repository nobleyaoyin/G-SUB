"""Restore-safe nonce checks using synthetic authorities and disposable databases."""
import os,sqlite3
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from app.models import User
from app.lifecycle_bootstrap import bootstrap,validate_approval
from app.bootstrap_nonce_ledger import reserve_nonce
from app.lifecycle_prototype import lifecycle_read
from test_batch38_eic_proof import fixture
from tests.test_lifecycle_prototype import principal,AUTHORITY
from test_sprint12_lifecycle_admin import approval,reserved_bootstrap,fixture_reserve,migration


def setup_synthetic(f):
    migration.migrate(f.db_path)
    user=User(name='Synthetic restore EIC',email='restore-eic@example.com',password_hash='x',role='eic')
    f.db.add(user);f.db.commit()
    owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate()
    key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    return user,key,approval(f.db_path,user.user_id,user.email,owner,operator)


def test_restore_same_inode_cannot_reuse_signed_nonce_and_audit_is_normalized(fixture):
    f,chief,headers,_,_,_,_=fixture
    user,key,signed=setup_synthetic(f);backup=f.root/'pre-bootstrap.sqlite'
    f.db.rollback()
    with sqlite3.connect(f.db_path) as source,sqlite3.connect(backup) as target:source.backup(target)
    inode=f.db_path.stat().st_ino
    with sqlite3.connect(f.db_path,timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
        reserved_bootstrap(raw,signed,key,f.db_path,user.user_id,'SYNTHETIC-APPROVAL');raw.commit()
    with sqlite3.connect(f.db_path,timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON')
        records=lifecycle_read(raw,principal(chief.user_id),user.user_id,authority=AUTHORITY,history=True)
        assert records[0][4]['kind']=='offline_operator'
        assert records[0][4]['operator_key_sha256'] and records[0][4]['approval_reference']=='SYNTHETIC-APPROVAL'
    f.db.rollback()
    with sqlite3.connect(backup) as source,sqlite3.connect(f.db_path) as target:source.backup(target)
    assert f.db_path.stat().st_ino==inode
    with sqlite3.connect(f.db_path,timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
        with pytest.raises(FileExistsError):reserved_bootstrap(raw,signed,key,f.db_path,user.user_id,'SYNTHETIC-APPROVAL')
        raw.rollback()
        assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==0


def test_rollback_burns_reservation_and_missing_capability_is_denied(fixture):
    f,_,_,_,_,_,_=fixture
    user,key,signed=setup_synthetic(f)
    with sqlite3.connect(f.db_path,timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
        with pytest.raises(TypeError):bootstrap(raw,signed,key,f.db_path,user.user_id,'SYNTHETIC-APPROVAL')
        reserved_bootstrap(raw,signed,key,f.db_path,user.user_id,'SYNTHETIC-APPROVAL')
        raw.rollback()
    with sqlite3.connect(f.db_path,timeout=.2) as raw:
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
        with pytest.raises(FileExistsError):reserved_bootstrap(raw,signed,key,f.db_path,user.user_id,'SYNTHETIC-APPROVAL')
        raw.rollback()
        assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==0


def test_non_root_ledger_directory_is_rejected(fixture):
    from types import SimpleNamespace
    from unittest.mock import patch
    f,_,_,_,_,_,_=fixture
    directory=f.root/'untrusted-ledger';directory.mkdir(mode=0o700)
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:
        actual=os.fstat(fd)
        with patch('app.bootstrap_nonce_ledger.os.fstat',return_value=SimpleNamespace(st_mode=actual.st_mode,st_uid=501)):
            with pytest.raises(ValueError):reserve_nonce(fd,'1'*64,'2'*64,'3'*64)
    finally:os.close(fd)


def test_uncertain_ledger_write_is_not_retried(fixture):
    from unittest.mock import patch
    f,_,_,_,_,_,_=fixture
    directory=f.root/'uncertain-ledger';directory.mkdir(mode=0o700)
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:
        with patch('app.bootstrap_nonce_ledger.os.fsync',side_effect=OSError('synthetic fsync failure')):
            with pytest.raises(OSError):fixture_reserve(fd,'a'*64,'b'*64,'c'*64)
        with pytest.raises(FileExistsError):fixture_reserve(fd,'a'*64,'b'*64,'c'*64)
    finally:os.close(fd)


def test_concurrent_reservations_are_single_use(fixture):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from unittest.mock import patch
    import threading
    f,_,_,_,_,_,_=fixture
    directory=f.root/'concurrent-ledger';directory.mkdir(mode=0o700)
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    actual=os.fstat(fd);barrier=threading.Barrier(2)
    def attempt(_):
        barrier.wait()
        try:reserve_nonce(fd,'d'*64,'e'*64,'f'*64);return 'reserved'
        except FileExistsError:return 'denied'
    try:
        with patch('app.bootstrap_nonce_ledger.os.fstat',return_value=SimpleNamespace(st_mode=actual.st_mode,st_uid=0)):
            with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(attempt,range(2)))
        assert sorted(outcomes)==['denied','reserved']
    finally:os.close(fd)
