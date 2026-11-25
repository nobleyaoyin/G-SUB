"""Root-controlled, create-once approval reservations outside the application DB.

A reservation is deliberately never removed on failure. Restoring only the
application DB cannot restore an already consumed approval. System-wide storage
rollback or a privileged actor who can alter this directory remains outside this
local control and requires independently protected backup/monitoring.
"""
import json
import os
from pathlib import Path
import re
import stat
import threading
from datetime import datetime, timezone

LEDGER_DIRECTORY=Path('/private/var/db/gsub-lifecycle-nonces')
_HEX=re.compile(r'^[0-9a-f]{64}$')
_ISSUER=object()


class Reservation:
    """Process-local evidence created only after the durable create-once write."""
    def __init__(self, issuer, nonce, approval_sha256, operator_fingerprint):
        if issuer is not _ISSUER:raise ValueError('Invalid approval reservation')
        self._nonce,self._approval,self._operator=nonce,approval_sha256,operator_fingerprint
        self._used=False
        self._lock=threading.Lock()

    def consume(self, nonce, approval_sha256, operator_fingerprint):
        with self._lock:
            if self._used or (nonce,approval_sha256,operator_fingerprint)!=(self._nonce,self._approval,self._operator):
                raise ValueError('Approval reservation unavailable')
            self._used=True


def open_trusted_ledger():
    path=LEDGER_DIRECTORY
    if path.resolve(strict=True)!=path or path.is_symlink():raise ValueError('Approval ledger unavailable')
    parent=path.parent.stat()
    if parent.st_uid!=0 or stat.S_IMODE(parent.st_mode)&0o022:raise ValueError('Approval ledger parent unavailable')
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    info=os.fstat(fd)
    if info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700:
        os.close(fd);raise ValueError('Approval ledger unavailable')
    return fd


def reserve_nonce(directory_fd, nonce, approval_sha256, operator_fingerprint):
    """Burn a verified nonce once; partial writes and failures never trigger cleanup."""
    if any(not isinstance(x,str) or not _HEX.fullmatch(x) for x in (nonce,approval_sha256,operator_fingerprint)):
        raise ValueError('Invalid approval reservation')
    directory=os.fstat(directory_fd)
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid!=0 or stat.S_IMODE(directory.st_mode)!=0o700:
        raise ValueError('Approval ledger unavailable')
    record={'nonce':nonce,'approval_sha256':approval_sha256,'operator_key_sha256':operator_fingerprint,
            'reserved_at':datetime.now(timezone.utc).isoformat(),'state':'consumed_or_outcome_unknown'}
    data=(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode('ascii')
    fd=os.open(nonce+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400,dir_fd=directory_fd)
    try:
        if os.write(fd,data)!=len(data):raise OSError('Incomplete approval reservation')
        os.fsync(fd)
    finally:os.close(fd)
    os.fsync(directory_fd)
    return Reservation(_ISSUER,nonce,approval_sha256,operator_fingerprint)
