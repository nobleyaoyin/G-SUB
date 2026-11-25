#!/usr/bin/env python3
"""Offline owner-signed administrator succession; never runs at startup."""
import argparse,json,os,sqlite3,stat,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.bootstrap_lifecycle_admin import trusted_owner_key,collaboration_database
from app.bootstrap_nonce_ledger import open_trusted_ledger,reserve_nonce
from app.lifecycle_succession import validate_approval,succeed
from scripts.maintenance_participation import run_guarded

def _main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True);p.add_argument('--current-admin-id',type=int,required=True)
    p.add_argument('--successor-id',type=int,required=True);p.add_argument('--confirm-successor-id',type=int,required=True)
    p.add_argument('--approval-reference',required=True);p.add_argument('--confirm-approval-reference',required=True)
    p.add_argument('--signed-approval',required=True);p.add_argument('--confirm-application-stopped',action='store_true')
    a=p.parse_args()
    try:
        path=collaboration_database(a.database,project_root=ROOT)
        if (a.successor_id!=a.confirm_successor_id or a.approval_reference!=a.confirm_approval_reference or not a.confirm_application_stopped):raise ValueError('Confirmation unavailable')
        if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')):raise ValueError('Database journal unavailable')
        approval=Path(a.signed_approval)
        if any(name in str(approval).lower() for name in ('demo','upgrade-test','main-collaboration')):raise ValueError('Restricted approval path')
        if not approval.is_absolute() or approval!=approval.resolve(strict=True):raise ValueError('Approval unavailable')
        fd=os.open(approval,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077 or st.st_size>16384:raise ValueError('Approval unavailable')
            bundle=json.loads(os.read(fd,16385))
        finally:os.close(fd)
        key=trusted_owner_key()
        with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
            db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA integrity_check').fetchone()!=('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Integrity unavailable')
            payload,digest,_,operator=validate_approval(bundle,key,now=int(time.time()),db_path=path)
            if (payload['previous_admin_user_id'],payload['successor_user_id'],payload['approval_reference'])!=(a.current_admin_id,a.successor_id,a.approval_reference):raise ValueError('Approval mismatch')
            ledger=open_trusted_ledger()
            try:reservation=reserve_nonce(ledger,payload['nonce'],digest,operator)
            finally:os.close(ledger)
            result=succeed(db,bundle,key,path,reservation=reservation)
            if db.execute('PRAGMA integrity_check').fetchone()!=('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Integrity unavailable')
            db.commit()
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        print(f'Succession refused or outcome unknown: {type(exc).__name__}',file=sys.stderr);return 1
def main():
    return run_guarded(_main)


if __name__=='__main__':raise SystemExit(main())
