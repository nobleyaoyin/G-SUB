#!/usr/bin/env python3
"""Conservative literal-file sync; writes require a reviewed manifest hash.

CLI roots are fixed to Main and its official Stable sibling. Existing files only.
No deployment, service operations, migrations, directory mirroring or deletion.
"""
import argparse
import ctypes
import difflib
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys

# Extend only through review and new safety tests; no patterns or directories.
ALLOWLIST = frozenset({
    'app/routers/manuscripts.py',
    'frontend/src/AuthorDashboard.jsx',
    'frontend/src/AuthorDashboard.css',
    'frontend/index.html',
    'frontend/public/favicon.svg',
})
# These reviewed differences intentionally remain distinct or are cosmetic.
# They may be inspected but cannot be applied until this policy is reviewed.
APPLY_ALLOWLIST = frozenset({'frontend/index.html', 'frontend/public/favicon.svg'})
PROTECTED = {'.demo_data', 'uploads', 'backups', 'backup', '.venv', 'node_modules',
             'dist', '.git', '.agents', '.codex', '__pycache__', '.pytest_cache',
             '.cache', 'cache', 'logs', 'log', 'tmp', 'temp', 'credentials', 'accounts'}
MAX_BYTES = 2 * 1024 * 1024
NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
DIRECTORY = getattr(os, 'O_DIRECTORY', 0)
if not NOFOLLOW or not DIRECTORY:
    raise RuntimeError('This tool requires no-follow directory descriptors')


def validate_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Invalid relative path')
    p = PurePosixPath(value)
    parts = value.split('/')
    if p.is_absolute() or any(x in ('', '.', '..') for x in parts):
        raise ValueError('Invalid relative path')
    for component in parts:
        name = component.lower()
        if (name in PROTECTED or name.startswith(('.env', '.git', '.onlyoffice', 'backup'))
                or name.endswith(('.db', '.sqlite', '.sqlite3', '-wal', '-shm', '-journal', '.key', '.pem', '.log', '.tmp', '.bak'))
                or any(word in name for word in ('credential', 'password', 'secret', 'account', 'jwt'))
                or '.before' in name):
            raise ValueError('Protected path')
    if value not in ALLOWLIST:
        raise ValueError('Path is not in the literal allowlist')
    return parts


def open_root(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or not path.is_dir() or path.is_symlink():
        raise ValueError('Root must be an existing canonical non-symlink directory')
    return os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW)


def parent_fd(rootfd, parts):
    current = os.dup(rootfd)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=current)
            os.close(current); current = nxt
        return current
    except BaseException:
        os.close(current); raise


def read_fd(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
        raise ValueError('Unsafe, hard-linked or oversized file')
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        b = os.read(fd, 65536)
        if not b: break
        chunks.append(b)
        if sum(map(len, chunks)) > MAX_BYTES: raise ValueError('File exceeds size limit')
    return b''.join(chunks)


def open_file(parent, name):
    fd = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=parent)
    try: data = read_fd(fd)
    except BaseException: os.close(fd); raise
    return fd, data


def digest(data): return hashlib.sha256(data).hexdigest()
def canonical(obj): return (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()


def metadata_copy(srcfd, dstfd, include_data):
    """macOS fcopyfile preserves ACL, xattrs, ownership and mode or fails closed."""
    if sys.platform != 'darwin': raise RuntimeError('Writes require macOS fcopyfile metadata support')
    if include_data:
        os.lseek(srcfd, 0, os.SEEK_SET); os.lseek(dstfd, 0, os.SEEK_SET); os.ftruncate(dstfd, 0)
    lib = ctypes.CDLL(None, use_errno=True)
    f = lib.fcopyfile; f.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]; f.restype = ctypes.c_int
    if f(srcfd, dstfd, None, 15 if include_data else 7) != 0:
        err = ctypes.get_errno(); raise OSError(err, os.strerror(err))
    if stat.S_IMODE(os.fstat(srcfd).st_mode) != stat.S_IMODE(os.fstat(dstfd).st_mode):
        raise RuntimeError('Metadata mode verification failed')


def metadata_fingerprint(fd):
    """Record security-relevant target metadata; never include timestamps."""
    if sys.platform != 'darwin': raise RuntimeError('Metadata inspection requires macOS')
    info=os.fstat(fd);lib=ctypes.CDLL(None,use_errno=True)
    names=lib.flistxattr;names.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int];names.restype=ctypes.c_ssize_t
    size=names(fd,None,0,0)
    if size < 0: raise OSError(ctypes.get_errno(),'Cannot list extended attributes')
    buf=ctypes.create_string_buffer(size or 1)
    if size and names(fd,buf,size,0)!=size: raise RuntimeError('Extended attributes changed')
    get=lib.fgetxattr;get.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int];get.restype=ctypes.c_ssize_t
    attrs={}
    for name in sorted(x for x in buf.raw[:size].split(b'\0') if x):
        n=get(fd,name,None,0,0,0)
        if n < 0: raise OSError(ctypes.get_errno(),'Cannot read extended attribute')
        value=ctypes.create_string_buffer(n or 1)
        if n and get(fd,name,value,n,0,0)!=n:raise RuntimeError('Extended attribute changed')
        attrs[name.hex()]=digest(value.raw[:n])
    getacl=lib.acl_get_fd;getacl.argtypes=[ctypes.c_int];getacl.restype=ctypes.c_void_p
    ctypes.set_errno(0);acl=getacl(fd);aclhash=None
    if acl:
        convert=lib.acl_to_text;convert.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ssize_t)];convert.restype=ctypes.c_void_p
        free=lib.acl_free;free.argtypes=[ctypes.c_void_p];length=ctypes.c_ssize_t()
        try:
            textptr=convert(acl,ctypes.byref(length))
            if not textptr:raise OSError(ctypes.get_errno(),'Cannot inspect ACL')
            try:aclhash=digest(ctypes.string_at(textptr,length.value))
            finally:free(textptr)
        finally:free(acl)
    elif ctypes.get_errno() not in (errno.ENOENT,):raise OSError(ctypes.get_errno(),'Cannot inspect ACL')
    return {'mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,'flags':getattr(info,'st_flags',0),'xattrs':attrs,'acl_sha256':aclhash}


def write_all(fd, data):
    os.ftruncate(fd, 0); os.lseek(fd, 0, os.SEEK_SET)
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0: raise OSError('Short write')
        view = view[n:]
    os.fsync(fd)


def private_file(parent, name):
    return os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600, dir_fd=parent)


def write_journal(op, data):
    # Append-only intent/outcome journal: each record fsynced before next action.
    fd = os.open('journal.jsonl', os.O_WRONLY | os.O_APPEND | NOFOLLOW, dir_fd=op)
    try:
        remaining = memoryview((json.dumps(data, sort_keys=True) + '\n').encode())
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0: raise OSError('Short journal write')
            remaining = remaining[written:]
        os.fsync(fd)
    finally: os.close(fd)


class Engine:
    def __init__(self, source, target):
        self.source = Path(source); self.target = Path(target)
        if self.source == self.target or self.source in self.target.parents or self.target in self.source.parents:
            raise ValueError('Roots must be disjoint')
        self.sf = open_root(self.source); self.tf = open_root(self.target)

    def close(self): os.close(self.sf); os.close(self.tf)

    def scan(self, names):
        if len(names) != len(set(names)) or not names: raise ValueError('Select unique allowlisted files')
        entries = []
        for name in sorted(names):
            parts = validate_path(name); sp = parent_fd(self.sf, parts); tp = parent_fd(self.tf, parts)
            try:
                s, sd = open_file(sp, parts[-1]); t, td = open_file(tp, parts[-1])
                try:
                    # Exact textual diffs only; reject opaque/binary or invalid UTF-8.
                    st, tt = sd.decode('utf-8'), td.decode('utf-8')
                    diff = ''.join(difflib.unified_diff(tt.splitlines(True), st.splitlines(True), fromfile='Stable/'+name, tofile='Main/'+name))
                    entries.append({'path':name,'source_sha256':digest(sd),'target_sha256':digest(td),'different':sd != td,'diff':diff,'target_metadata':metadata_fingerprint(t)})
                finally: os.close(s); os.close(t)
            finally: os.close(sp); os.close(tp)
        return {'version':1,'source_root':str(self.source),'target_root':str(self.target),'entries':entries}

    def validate_manifest(self, m):
        if set(m) != {'version','source_root','target_root','entries'} or m['version'] != 1 or m['source_root'] != str(self.source) or m['target_root'] != str(self.target):
            raise ValueError('Manifest roots or version mismatch')
        entries=m['entries']
        if not isinstance(entries,list) or not entries: raise ValueError('Empty manifest')
        names=[]
        for e in entries:
            if set(e) != {'path','source_sha256','target_sha256','different','diff','target_metadata'}: raise ValueError('Invalid entry')
            validate_path(e['path']); names.append(e['path'])
        if len(names)!=len(set(names)): raise ValueError('Duplicate path')
        # Full comparison includes exact diffs and detects source/target drift.
        if self.scan(names) != m: raise ValueError('Manifest drift or tampering')
        if not any(e['different'] for e in entries): raise ValueError('No changes to apply')
        if any(e['different'] and e['path'] not in APPLY_ALLOWLIST for e in entries): raise ValueError('Manifest includes review-only or intentionally different files')

    def apply(self, manifest, approval_hash, backup_parent, fault=None):
        raw=Path(manifest).read_bytes()
        if digest(raw)!=approval_hash: raise ValueError('Explicit approved manifest hash mismatch')
        m=json.loads(raw); self.validate_manifest(m)
        bp=Path(backup_parent)
        if not bp.is_absolute() or bp.resolve()!=bp or not bp.is_dir() or bp.is_symlink() or bp in (self.source,self.target) or self.source in bp.parents or self.target in bp.parents or bp in self.source.parents or bp in self.target.parents:
            raise ValueError('Backup parent must be a separate canonical directory')
        info = bp.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('Backup parent must be private and owned by the current user')
        bfd=open_root(bp); op_name='sync-'+secrets.token_hex(12); os.mkdir(op_name,0o700,dir_fd=bfd); op=os.open(op_name,os.O_RDONLY|DIRECTORY|NOFOLLOW,dir_fd=bfd)
        os.close(bfd)
        try:
            j=private_file(op,'journal.jsonl');os.close(j)
            mf=private_file(op,'manifest.json');write_all(mf,raw);os.close(mf)
            write_journal(op,{'phase':'begin','manifest_sha256':digest(raw)})
            # Back up every target before replacing any target.
            for idx,e in enumerate(m['entries']):
                if not e['different']: continue
                parts=validate_path(e['path']);tp=parent_fd(self.tf,parts)
                try:
                    t,td=open_file(tp,parts[-1])
                    try:
                        if digest(td)!=e['target_sha256'] or metadata_fingerprint(t)!=e['target_metadata']:raise ValueError('Target changed before backup')
                        bf=private_file(op,f'{idx}.backup')
                        try:
                            metadata_copy(t,bf,True);os.fsync(bf)
                            if digest(read_fd(bf))!=e['target_sha256'] or metadata_fingerprint(bf)!=e['target_metadata']:raise RuntimeError('Backup verification failed')
                        finally:os.close(bf)
                    finally:os.close(t)
                finally:os.close(tp)
            os.fsync(op);write_journal(op,{'phase':'backups_verified'})
            for idx,e in enumerate(m['entries']):
                if not e['different']:continue
                parts=validate_path(e['path']);sp=parent_fd(self.sf,parts);tp=parent_fd(self.tf,parts)
                try:
                    s,sd=open_file(sp,parts[-1]);t,td=open_file(tp,parts[-1])
                    try:
                        if digest(sd)!=e['source_sha256'] or digest(td)!=e['target_sha256'] or metadata_fingerprint(t)!=e['target_metadata']:raise ValueError('Source or target changed before replacement')
                        tmp='.gsub-sync-'+secrets.token_hex(12);stage=private_file(tp,tmp)
                        try:
                            metadata_copy(t,stage,False);write_all(stage,sd)
                            if digest(read_fd(stage))!=e['source_sha256'] or metadata_fingerprint(stage)!=e['target_metadata']:raise RuntimeError('Staged file mismatch')
                        finally:os.close(stage)
                        write_journal(op,{'phase':'prepared','index':idx,'staging':tmp})
                        if fault:fault('prepared',idx)
                        # Reopen to detect path replacement after initial validation.
                        check,now=open_file(tp,parts[-1])
                        try:
                            before=os.fstat(t); current=os.fstat(check)
                            if (before.st_dev,before.st_ino,before.st_mtime_ns)!=(current.st_dev,current.st_ino,current.st_mtime_ns) or digest(now)!=e['target_sha256'] or metadata_fingerprint(check)!=e['target_metadata']:
                                raise ValueError('Target changed after staging')
                        finally:os.close(check)
                        fresh_parent=parent_fd(self.tf,parts)
                        try:
                            if (os.fstat(fresh_parent).st_dev,os.fstat(fresh_parent).st_ino)!=(os.fstat(tp).st_dev,os.fstat(tp).st_ino):raise ValueError('Target parent changed')
                        finally:os.close(fresh_parent)
                        source_check,source_now=open_file(sp,parts[-1])
                        try:
                            before=os.fstat(s); current=os.fstat(source_check)
                            if (before.st_dev,before.st_ino,before.st_mtime_ns)!=(current.st_dev,current.st_ino,current.st_mtime_ns) or digest(source_now)!=e['source_sha256']:
                                raise ValueError('Source changed after staging')
                        finally:os.close(source_check)
                        fresh_source_parent=parent_fd(self.sf,parts)
                        try:
                            if (os.fstat(fresh_source_parent).st_dev,os.fstat(fresh_source_parent).st_ino)!=(os.fstat(sp).st_dev,os.fstat(sp).st_ino):raise ValueError('Source parent changed')
                        finally:os.close(fresh_source_parent)
                        os.rename(tmp,parts[-1],src_dir_fd=tp,dst_dir_fd=tp);os.fsync(tp)
                        write_journal(op,{'phase':'replaced','index':idx})
                        if fault:fault('replaced',idx)
                    finally:os.close(s);os.close(t)
                finally:os.close(sp);os.close(tp)
            write_journal(op,{'phase':'complete'});return bp/op_name
        finally:os.close(op)

    def rollback(self, operation, approval_hash):
        op_path=Path(operation)
        if not op_path.is_absolute() or op_path.resolve()!=op_path or not op_path.is_dir() or op_path.is_symlink() or self.source in op_path.parents or self.target in op_path.parents or op_path in self.source.parents or op_path in self.target.parents:
            raise ValueError('Unsafe operation directory')
        op=open_root(op_path)
        try:
            mf,raw=open_file(op,'manifest.json');os.close(mf)
            if digest(raw)!=approval_hash:raise ValueError('Explicit rollback approval hash mismatch')
            m=json.loads(raw)
            if m.get('source_root')!=str(self.source) or m.get('target_root')!=str(self.target):raise ValueError('Operation roots mismatch')
            entries=m['entries'];seen=set()
            # All backups and targets checked before any rollback write.
            for idx,e in enumerate(entries):
                parts=validate_path(e['path'])
                if e['path'] in seen:raise ValueError('Duplicate entry')
                seen.add(e['path'])
                if not e['different']:continue
                bf,bd=open_file(op,f'{idx}.backup')
                try:
                    if digest(bd)!=e['target_sha256'] or metadata_fingerprint(bf)!=e['target_metadata']:raise ValueError('Backup drift')
                finally:os.close(bf)
                tp=parent_fd(self.tf,parts)
                try:
                    t,td=open_file(tp,parts[-1])
                    try:
                        if digest(td) not in (e['target_sha256'],e['source_sha256']) or metadata_fingerprint(t)!=e['target_metadata']:raise ValueError('Rollback conflict')
                    finally:os.close(t)
                finally:os.close(tp)
            write_journal(op,{'phase':'rollback_begin'})
            for idx,e in enumerate(entries):
                if not e['different']:continue
                parts=validate_path(e['path']);tp=parent_fd(self.tf,parts)
                try:
                    t,td=open_file(tp,parts[-1])
                    try:
                        if metadata_fingerprint(t)!=e['target_metadata']:raise ValueError('Rollback metadata drift')
                    finally:os.close(t)
                    if digest(td)==e['target_sha256']:continue
                    if digest(td)!=e['source_sha256']:raise ValueError('Rollback target drift')
                    bf,bd=open_file(op,f'{idx}.backup');tmp='.gsub-restore-'+secrets.token_hex(12);stage=private_file(tp,tmp)
                    try:
                        metadata_copy(bf,stage,True);os.fsync(stage)
                        if digest(read_fd(stage))!=e['target_sha256'] or metadata_fingerprint(stage)!=e['target_metadata']:raise RuntimeError('Rollback stage mismatch')
                    finally:os.close(stage);os.close(bf)
                    write_journal(op,{'phase':'rollback_prepared','index':idx,'staging':tmp})
                    check,now=open_file(tp,parts[-1])
                    try:
                        if digest(now)!=e['source_sha256'] or metadata_fingerprint(check)!=e['target_metadata']:raise ValueError('Rollback target changed after staging')
                    finally:os.close(check)
                    os.rename(tmp,parts[-1],src_dir_fd=tp,dst_dir_fd=tp);os.fsync(tp);write_journal(op,{'phase':'restored','index':idx})
                finally:os.close(tp)
            write_journal(op,{'phase':'rollback_complete'})
        finally:os.close(op)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    plan=sub.add_parser('dry-run');plan.add_argument('--file',action='append',required=True,choices=sorted(ALLOWLIST))
    apply=sub.add_parser('apply');apply.add_argument('--manifest',required=True);apply.add_argument('--approve-manifest-sha256',required=True);apply.add_argument('--backup-parent',required=True)
    rollback=sub.add_parser('rollback');rollback.add_argument('--operation',required=True);rollback.add_argument('--approve-manifest-sha256',required=True)
    args=parser.parse_args();source=Path(__file__).resolve().parent.parent;target=source.parent/'Manuscript-Stable-Demo';engine=Engine(source,target)
    try:
        if args.command=='dry-run':sys.stdout.buffer.write(canonical(engine.scan(args.file)))
        elif args.command=='apply':print('Operation backup:',engine.apply(args.manifest,args.approve_manifest_sha256,args.backup_parent))
        else:engine.rollback(args.operation,args.approve_manifest_sha256);print('Rollback complete; backups retained')
    finally:engine.close()
if __name__=='__main__':main()
