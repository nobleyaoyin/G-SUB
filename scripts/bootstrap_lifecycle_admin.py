#!/usr/bin/env python3
"""Explicit offline lifecycle bootstrap. Never runs automatically."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT))
from app.lifecycle_bootstrap import bootstrap, validate_approval
from app.bootstrap_nonce_ledger import open_trusted_ledger, reserve_nonce
from scripts.maintenance_participation import run_guarded

# Provisioned independently by the system owner; it is not selected by CLI or env.
OWNER_KEY=Path('/private/etc/gsub/lifecycle-owner.pub')


def trusted_owner_key():
    parent=OWNER_KEY.parent
    if parent.resolve(strict=True)!=parent or parent.stat().st_uid!=0 or stat.S_IMODE(parent.stat().st_mode)&0o022:
        raise ValueError('Owner trust directory unavailable')
    fd=os.open(OWNER_KEY,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022 or info.st_size!=32:
            raise ValueError('Owner trust anchor unavailable')
        key=os.read(fd,33)
        if len(key)!=32:raise ValueError('Owner trust anchor unavailable')
        return key
    finally:os.close(fd)


def collaboration_database(value, *, project_root=None):
    """Accept only this disposable clone's explicitly configured private database."""
    path=Path(value)
    root=(PROJECT_ROOT if project_root is None else project_root)/'.test-data'
    if (not path.is_absolute() or os.environ.get('COLLABORATION_DATABASE') != str(path)
            or root.is_symlink() or not root.is_dir() or root.resolve(strict=True)!=root
            or not root.is_relative_to(Path(tempfile.gettempdir()).resolve(strict=True))
            or path.parent!=root or path.is_symlink() or path.resolve(strict=True)!=path):
        raise ValueError('Isolated collaboration database unavailable')
    directory=root.stat(); info=path.stat()
    if (directory.st_uid!=os.geteuid() or stat.S_IMODE(directory.st_mode)&0o022
            or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid()
            or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)&0o077):
        raise ValueError('Isolated collaboration database unavailable')
    return path


def _main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True);parser.add_argument('--target-user-id',type=int,required=True)
    parser.add_argument('--confirm-user-id',type=int,required=True);parser.add_argument('--approval-reference',required=True)
    parser.add_argument('--confirm-approval-reference',required=True);parser.add_argument('--signed-approval',required=True)
    parser.add_argument('--confirm-application-stopped',action='store_true')
    args=parser.parse_args()
    try:
        path=collaboration_database(args.database)
        if (args.target_user_id!=args.confirm_user_id or args.approval_reference!=args.confirm_approval_reference
                or not args.confirm_application_stopped):raise ValueError('Exact target, database, approval and stopped-writer confirmations required')
        if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')):raise ValueError('Database has a pending or active journal')
        approval=Path(args.signed_approval)
        if any(name in str(approval).lower() for name in ('demo','upgrade-test','main-collaboration')):
            raise ValueError('Restricted approval path')
        if not approval.is_absolute() or approval!=approval.resolve(strict=True):raise ValueError('Canonical signed approval required')
        fd=os.open(approval,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid()
                    or stat.S_IMODE(info.st_mode)&0o077 or info.st_size>16384):raise ValueError('Approval file unavailable')
            data=os.read(fd,16385)
        finally:os.close(fd)
        bundle=json.loads(data)
        key=trusted_owner_key()
        with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
            db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA integrity_check').fetchone()!=('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Database integrity unavailable')
            payload,approval_sha,_,operator_sha=validate_approval(bundle,key,path,args.target_user_id,args.approval_reference)
            ledger_fd=open_trusted_ledger()
            try:
                reservation=reserve_nonce(ledger_fd,payload['nonce'],approval_sha,operator_sha)
            finally:
                os.close(ledger_fd)
            result=bootstrap(db,bundle,key,path,args.target_user_id,args.approval_reference,reservation=reservation)
            if db.execute('PRAGMA integrity_check').fetchone()!=('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Database integrity unavailable')
            db.commit()
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as exc:
        print(f'Bootstrap refused or outcome unknown: {type(exc).__name__}',file=sys.stderr)
        return 1

def main():
    return run_guarded(_main)


if __name__=='__main__':raise SystemExit(main())
