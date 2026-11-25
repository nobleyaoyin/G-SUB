"""Fail-closed checks for prospectively controlled editor source bytes.

Callers must first perform their existing route-specific authorization and must
return the very bytes passed here. No user-provided actor or digest is trusted.
"""
from dataclasses import dataclass
import hashlib
from importlib import import_module
import os
import stat
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException


@dataclass(frozen=True)
class SourceDecision:
    mode: str
    policy_id: str | None = None


def _validate_policy_schema(conn):
    """Reject altered or incomplete installed evidence schemas."""
    for name in ('021_document_distribution', '025_automatic_distribution', '026_controlled_source_policy'):
        if not conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:name'), {'name':name}).first():
            raise HTTPException(503, 'Document authorization unavailable')
        module = import_module('migrations.' + name)
        normalize = getattr(module, '_normalize', None) or module.normalize
        for object_name, expected in module.DDL.items():
            row = conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'), {'name':object_name}).first()
            if not row or not row[0] or normalize(row[0]) != normalize(expected):
                raise HTTPException(503, 'Document authorization unavailable')


def _validate_provenance_schema(conn):
    name='027_source_grant_provenance'
    if not conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:name'), {'name':name}).first():
        raise HTTPException(503, 'Document authorization unavailable')
    module=import_module('migrations.'+name)
    for object_name,expected in module.DDL.items():
        row=conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'), {'name':object_name}).first()
        if not row or not row[0] or module.normalize(row[0])!=module.normalize(expected):
            raise HTTPException(503, 'Document authorization unavailable')


def source_may_be_controlled(db, manuscript_id):
    """Identify a prospective policy without altering legacy file handling."""
    try:
        conn = db.connection()
        if conn.dialect.name != 'sqlite': raise HTTPException(503, 'Document authorization unavailable')
        from app.editor_invitation_revocation import is_revoked_raw
        raw=conn.connection.driver_connection
        is_revoked_raw(raw,'initial',0)
        if raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone() and raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='031_editor_invitation_revocation'").fetchone() and raw.execute('SELECT 1 FROM editor_invitation_revocations WHERE manuscript_id=? LIMIT 1',(manuscript_id,)).fetchone():
            return True
        has_migrations=bool(raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone())
        has_round_marker=has_migrations and raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone()
        has_round_table=raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_distribution_grant_rounds'").fetchone()
        if has_round_marker or has_round_table:
            from app.editor_distribution_rounds import require_schema
            require_schema(raw)
            if raw.execute('''SELECT 1 FROM distribution_grants g LEFT JOIN editor_distribution_legacy_grants l ON l.grant_id=g.grant_id
                WHERE g.manuscript_id=? AND g.recipient_role='editor' AND l.grant_id IS NULL LIMIT 1''',(manuscript_id,)).fetchone():return True
        tables = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        if ('schema_migrations' in tables and 'automatic_distribution_configurations' not in tables and
                conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='025_automatic_distribution'")).first()):
            raise HTTPException(503, 'Document authorization unavailable')
        if 'automatic_distribution_configurations' in tables and conn.execute(text(
                'SELECT 1 FROM automatic_distribution_configurations WHERE manuscript_id=:mid LIMIT 1'), {'mid':manuscript_id}).first():
            return True
        installed = 'schema_migrations' in tables and bool(conn.execute(text(
            "SELECT 1 FROM schema_migrations WHERE migration_id='026_controlled_source_policy'")).first())
        if 'controlled_source_policies' not in tables:
            if installed or 'controlled_source_policy_revocations' in tables: raise HTTPException(503, 'Document authorization unavailable')
            return False
        if not installed or 'controlled_source_policy_revocations' not in tables: raise HTTPException(503, 'Document authorization unavailable')
        _validate_policy_schema(conn)
        return bool(conn.execute(text('SELECT 1 FROM controlled_source_policies WHERE manuscript_id=:mid LIMIT 1'), {'mid':manuscript_id}).first())
    except HTTPException: raise
    except SQLAlchemyError: raise HTTPException(503, 'Document authorization unavailable') from None


def source_path_is_controlled(db, manuscript_id, path, root):
    """Match a recorded source identity, including a now-historical source."""
    if not source_may_be_controlled(db, manuscript_id): return False
    try:
        conn = db.connection()
        tables = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        if ('schema_migrations' in tables and 'automatic_distribution_configurations' not in tables and
                conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='025_automatic_distribution'")).first()):
            raise HTTPException(503, 'Document authorization unavailable')
        if 'automatic_distribution_configurations' in tables and conn.execute(text(
                'SELECT 1 FROM automatic_distribution_configurations WHERE manuscript_id=:mid LIMIT 1'), {'mid':manuscript_id}).first():
            raise HTTPException(503, 'Document authorization unavailable')
        refs = list(conn.execute(text('SELECT source_ref FROM controlled_source_policies WHERE manuscript_id=:mid'), {'mid':manuscript_id}).scalars())
        if conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'")).first():
            refs.extend(conn.execute(text('SELECT source_ref FROM editor_distribution_grant_rounds WHERE manuscript_id=:mid'),{'mid':manuscript_id}).scalars())
        candidate = Path(path).resolve()
        return any((Path(ref) if Path(ref).is_absolute() else Path(root)/ref).resolve() == candidate for ref in refs)
    except HTTPException: raise
    except (SQLAlchemyError, OSError, ValueError): raise HTTPException(503, 'Document authorization unavailable') from None


def read_bounded_source(path, maximum):
    """Read one regular file into the bytes that the caller will return."""
    if not hasattr(os, 'O_NOFOLLOW'):
        raise HTTPException(503, 'Document unavailable')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
                raise OSError('Invalid file')
            chunks = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk: break
                chunks.append(chunk); remaining -= len(chunk)
            data = b''.join(chunks)
            after = os.fstat(fd)
            if len(data) != before.st_size or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise OSError('File changed')
            return data
        finally: os.close(fd)
    except OSError:
        raise HTTPException(409, 'Document unavailable') from None


def authorize_source(db, actor, manuscript_id, content, invitation_kind=None, grant_id=None):
    """Authorize server-read source bytes; legacy means existing rules apply.

    Automatic access deliberately fails closed until automatic grants have a
    trusted linkage to the prospective policy and an integrated processor.
    """
    if actor.role != 'editor':
        return SourceDecision('legacy')
    if not isinstance(content, bytes):
        raise HTTPException(503, 'Document authorization unavailable')
    try:
        conn = db.connection()
        if conn.dialect.name != 'sqlite': raise HTTPException(503, 'Document authorization unavailable')
        from app.editor_invitation_revocation import is_revoked
        active=[]
        for kind,table in (('initial','initial_editor_invitations'),('final','final_editor_invitations')):
            if invitation_kind and kind!=invitation_kind:continue
            invitation=conn.execute(text(f"SELECT invitation_id FROM {table} WHERE manuscript_id=:mid AND editor_id=:uid AND status='accepted' ORDER BY invitation_id DESC LIMIT 1"),{'mid':manuscript_id,'uid':actor.user_id}).first()
            if invitation:active.append(not is_revoked(db,kind,invitation[0]))
        if active and not any(active):raise HTTPException(403,'Document unavailable')
        tables = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        if ('schema_migrations' in tables and 'automatic_distribution_configurations' not in tables and
                conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='025_automatic_distribution'")).first()):
            raise HTTPException(503, 'Document authorization unavailable')
        if 'automatic_distribution_configurations' in tables:
            old = conn.execute(text('SELECT 1 FROM automatic_distribution_configurations WHERE manuscript_id=:mid LIMIT 1'), {'mid': manuscript_id}).first()
            if old: raise HTTPException(503, 'Document authorization unavailable')
        installed = ('schema_migrations' in tables and bool(conn.execute(text(
            "SELECT 1 FROM schema_migrations WHERE migration_id='026_controlled_source_policy'")).first()))
        if 'controlled_source_policies' not in tables:
            if installed or 'controlled_source_policy_revocations' in tables: raise HTTPException(503, 'Document authorization unavailable')
            return SourceDecision('legacy')
        if not installed or 'controlled_source_policy_revocations' not in tables:
            raise HTTPException(503, 'Document authorization unavailable')
        _validate_policy_schema(conn)
        rows = conn.execute(text('''SELECT p.policy_id,p.invitation_kind,p.mode,p.source_ref,p.source_sha256,p.version,p.authorized_at,
            r.policy_id AS revoked FROM controlled_source_policies p
            LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id
            WHERE p.manuscript_id=:mid ORDER BY p.version DESC'''), {'mid': manuscript_id}).mappings().all()
        if not rows:
            from app.editor_distribution_rounds import authorize_unconfigured_source
            if authorize_unconfigured_source(conn.connection.driver_connection,manuscript_id,actor.user_id,hashlib.sha256(content).hexdigest(),invitation_kind):return SourceDecision('manual')
            return SourceDecision('legacy')
        _validate_provenance_schema(conn)
        latest = {}
        for row in rows: latest.setdefault(row['invitation_kind'], row)
        if invitation_kind and invitation_kind not in latest:
            from app.editor_distribution_rounds import authorize_unconfigured_source
            if authorize_unconfigured_source(conn.connection.driver_connection,manuscript_id,actor.user_id,hashlib.sha256(content).hexdigest(),invitation_kind):return SourceDecision('manual')
            return SourceDecision('legacy')
        candidates = []
        accepted_without_policy = False
        for kind, table in (('initial','initial_editor_invitations'),('final','final_editor_invitations')):
            if invitation_kind and kind != invitation_kind: continue
            invite = conn.execute(text(f"SELECT invitation_id FROM {table} WHERE manuscript_id=:mid AND editor_id=:uid AND status='accepted' ORDER BY invitation_id DESC LIMIT 1"), {'mid':manuscript_id,'uid':actor.user_id}).first()
            if invite:
                from app.editor_invitation_revocation import is_revoked
                if is_revoked(db,kind,invite[0]):
                    raise HTTPException(403,'Document unavailable')
            if invite and kind in latest: candidates.append((latest[kind], invite[0]))
            elif invite: accepted_without_policy = True
        if not candidates and accepted_without_policy:
            from app.editor_distribution_rounds import authorize_unconfigured_source
            if authorize_unconfigured_source(conn.connection.driver_connection,manuscript_id,actor.user_id,hashlib.sha256(content).hexdigest(),invitation_kind):return SourceDecision('manual')
            return SourceDecision('legacy')
        if not candidates: raise HTTPException(403, 'Document unavailable')
        if not conn.execute(text("SELECT 1 FROM users WHERE user_id=:uid AND role='editor'"), {'uid':actor.user_id}).first():
            raise HTTPException(403, 'Document unavailable')
        if 'account_lifecycle' not in tables or not conn.execute(text("SELECT 1 FROM account_lifecycle WHERE user_id=:uid AND state='active'"), {'uid':actor.user_id}).first():
            raise HTTPException(403, 'Document unavailable')
        digest = hashlib.sha256(content).hexdigest()
        current = conn.execute(text('SELECT file_path FROM manuscripts WHERE manuscript_id=:mid'), {'mid':manuscript_id}).first()
        if not current or not current[0]: raise HTTPException(403, 'Document unavailable')
        for policy, iid in candidates:
            if policy['revoked'] is not None or policy['source_ref'] != current[0] or policy['source_sha256'] != digest:
                continue
            column = 'initial_invitation_id' if policy['invitation_kind']=='initial' else 'final_invitation_id'
            if policy['mode']=='automatic':
                if not conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='030_automatic_processing'")).first():
                    continue
                from app.automatic_distribution_processor import validate_processing_schema
                validate_processing_schema(db)
                grant=conn.execute(text(f'''SELECT g.grant_id FROM controlled_automatic_grant_provenance evidence
                    JOIN controlled_automatic_intents i ON i.intent_id=evidence.intent_id
                    JOIN distribution_grants g ON g.grant_id=evidence.grant_id
                    JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
                    WHERE evidence.policy_id=:policy_id AND evidence.policy_version=:policy_version
                      AND evidence.manuscript_id=:mid AND evidence.recipient_id=:uid
                      AND evidence.invitation_kind=:kind AND evidence.invitation_id=:iid
                      AND evidence.source_ref=:source_ref AND evidence.source_sha256=:digest
                      AND i.policy_id=:policy_id AND i.recipient_id=:uid AND i.invitation_id=:iid
                      AND g.manuscript_id=:mid AND g.recipient_id=:uid AND g.{column}=:iid
                      AND (:grant_id IS NULL OR g.grant_id=:grant_id)
                      AND a.manuscript_id=:mid AND a.kind='editor_source' AND a.sha256=:digest
                      AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id) LIMIT 1'''),
                    {'mid':manuscript_id,'uid':actor.user_id,'iid':iid,'digest':digest,'policy_id':policy['policy_id'],
                     'policy_version':policy['version'],'kind':policy['invitation_kind'],'source_ref':policy['source_ref'],'grant_id':grant_id}).first()
                if grant:
                    from app.editor_distribution_rounds import validate_if_present
                    validate_if_present(conn.connection.driver_connection,grant[0])
                    return SourceDecision('automatic',policy['policy_id'])
                continue
            if policy['mode']!='manual': continue
            grant = conn.execute(text(f'''SELECT g.grant_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
                JOIN controlled_source_grant_provenance evidence ON evidence.grant_id=g.grant_id
                WHERE g.manuscript_id=:mid AND g.recipient_id=:uid AND g.{column}=:iid AND g.mode='manual'
                  AND (:grant_id IS NULL OR g.grant_id=:grant_id)
                  AND a.manuscript_id=:mid AND a.kind='editor_source' AND a.sha256=:digest AND g.created_at>=:authorized_at
                  AND evidence.policy_id=:policy_id AND evidence.policy_version=:policy_version
                  AND evidence.manuscript_id=:mid AND evidence.recipient_id=:uid AND evidence.invitation_kind=:kind
                  AND evidence.invitation_id=:iid AND evidence.source_ref=:source_ref AND evidence.source_sha256=:digest
                  AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id) LIMIT 1'''),
                {'mid':manuscript_id,'uid':actor.user_id,'iid':iid,'digest':digest,'authorized_at':policy['authorized_at'],
                 'policy_id':policy['policy_id'],'policy_version':policy['version'],'kind':policy['invitation_kind'],'source_ref':policy['source_ref'],'grant_id':grant_id}).first()
            if grant:
                from app.editor_distribution_rounds import validate_if_present
                validate_if_present(conn.connection.driver_connection,grant[0])
                return SourceDecision('manual',policy['policy_id'])
        raise HTTPException(403, 'Document unavailable')
    except HTTPException: raise
    except (SQLAlchemyError, KeyError): raise HTTPException(503, 'Document authorization unavailable') from None
