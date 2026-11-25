"""Record acceptance-bound intent evidence; does not grant document access."""
import hashlib
import json
import logging
from importlib import import_module
from uuid import uuid4
from sqlalchemy import text
from app.strict_utc import canonical_utc

logger=logging.getLogger(__name__)


def process_after_acceptance(db,intent_id):
    """Process after the acceptance commit without affecting its outcome."""
    if not intent_id: return
    try:
        from sqlalchemy.orm import Session
        from app.automatic_distribution_processor import process_intent
        with Session(bind=db.get_bind()) as session:
            process_intent(session,intent_id)
    except Exception:
        logger.warning('Automatic distribution processing unavailable')


def validate_intent_schema(conn):
    """Validate 028 and its optional 029 forward trigger replacement."""
    old=import_module('migrations.028_automatic_distribution_intents')
    newer=import_module('migrations.029_intent_precision_failures')
    present=bool(conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:id'),{'id':newer.MIGRATION_ID}).first())
    for name,expected in old.DDL.items():
        if present and name=='controlled_automatic_intents_check': expected=newer.DDL[name]
        actual=conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'),{'name':name}).first()
        if not actual or not actual[0] or old.normalize(actual[0])!=old.normalize(expected): raise RuntimeError('Intent schema unavailable')
    if present:
        for name,expected in newer.DDL.items():
            actual=conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'),{'name':name}).first()
            if not actual or not actual[0] or newer.normalize(actual[0])!=newer.normalize(expected): raise RuntimeError('Intent schema unavailable')
    return present


def _record_capture_failure(db, manuscript_id, kind, invitation_id, stamp):
    """Record a sanitized failure if the separate 029 ledger is healthy."""
    try:
        with db.begin_nested():
            conn=db.connection();newer=import_module('migrations.029_intent_precision_failures')
            if not conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:id'),{'id':newer.MIGRATION_ID}).first(): return False
            for name,expected in newer.DDL.items():
                if name=='controlled_automatic_intents_check': continue
                actual=conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'),{'name':name}).first()
                if not actual or not actual[0] or newer.normalize(actual[0])!=newer.normalize(expected): return False
            policy=conn.execute(text('''SELECT p.policy_id FROM controlled_source_policies p
                LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id
                WHERE p.manuscript_id=:mid AND p.invitation_kind=:kind AND p.mode='automatic' AND r.policy_id IS NULL
                ORDER BY p.version DESC LIMIT 1'''),{'mid':manuscript_id,'kind':kind}).first()
            if not policy: return False
            conn.execute(text('''INSERT OR IGNORE INTO controlled_automatic_capture_failures VALUES
                (:id,:policy,:mid,:kind,:iid,'capture_unavailable',:stamp)'''),
                {'id':uuid4().hex,'policy':policy[0],'mid':manuscript_id,'kind':kind,'iid':invitation_id,'stamp':stamp})
            return True
    except Exception:
        logger.warning('Automatic distribution capture failure could not be recorded')
        return False


def capture_acceptance(db, manuscript_id, kind, invitation_id, recipient_id, accepted_at):
    """Best-effort intent capture in a savepoint of the invitation transaction.

    Automatic activation is disabled. This records a pending intent only; it
    does not process files, create a grant, or modify the invitation outcome.
    """
    try:
        with db.begin_nested():
            conn=db.connection()
            if conn.dialect.name!='sqlite': return None
            tables={row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'schema_migrations' not in tables: return None
            installed=conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='028_automatic_distribution_intents'")).first()
            if not installed:
                if 'controlled_source_policies' in tables and conn.execute(text("SELECT 1 FROM controlled_source_policies WHERE manuscript_id=:mid AND invitation_kind=:kind AND mode='automatic'"),{'mid':manuscript_id,'kind':kind}).first():
                    raise RuntimeError('Intent schema unavailable')
                return None
            validate_intent_schema(conn)
            policy=conn.execute(text('''SELECT p.policy_id,p.version,p.source_ref,p.source_sha256
                FROM controlled_source_policies p LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id
                WHERE p.manuscript_id=:mid AND p.invitation_kind=:kind AND p.mode='automatic' AND r.policy_id IS NULL
                ORDER BY p.version DESC LIMIT 1'''),{'mid':manuscript_id,'kind':kind}).first()
            if not policy: return None
            from app.editor_distribution_rounds import require_schema,resolve
            raw=conn.connection.driver_connection
            require_schema(raw)
            round_evidence=resolve(raw,manuscript_id,kind)
            stamp=canonical_utc(accepted_at)
            fields=[manuscript_id,kind,invitation_id,recipient_id,policy[0],policy[1],policy[2],policy[3],stamp]
            fingerprint=hashlib.sha256(json.dumps(fields,separators=(',',':')).encode()).hexdigest()
            key=hashlib.sha256(f'editor-acceptance:{kind}:{invitation_id}'.encode()).hexdigest()
            prior=conn.execute(text('SELECT intent_id,fingerprint FROM controlled_automatic_intents WHERE idempotency_key=:key'),{'key':key}).first()
            if prior:
                if prior[1]!=fingerprint: raise RuntimeError('Intent conflict')
                existing=raw.execute('SELECT round_kind,review_round,agreement_id,decision_id FROM editor_distribution_intent_rounds WHERE intent_id=?',(prior[0],)).fetchone()
                if existing!=round_evidence:raise RuntimeError('Intent round conflict')
                return prior[0]
            intent_id=uuid4().hex
            conn.execute(text('''INSERT INTO controlled_automatic_intents VALUES
                (:id,:policy,:mid,:kind,:iid,:recipient,:version,:ref,:digest,:key,:fingerprint,:accepted,:created)'''),
                {'id':intent_id,'policy':policy[0],'mid':manuscript_id,'kind':kind,'iid':invitation_id,
                 'recipient':recipient_id,'version':policy[1],'ref':policy[2],'digest':policy[3],
                 'key':key,'fingerprint':fingerprint,'accepted':stamp,'created':stamp})
            conn.execute(text('INSERT INTO controlled_automatic_events VALUES (:id,:intent,1,\'pending\',NULL,:stamp)'),
                {'id':uuid4().hex,'intent':intent_id,'stamp':stamp})
            raw.execute('INSERT INTO editor_distribution_intent_rounds VALUES(?,?,?,?,?,?,?)',(intent_id,manuscript_id,*round_evidence,stamp))
            return intent_id
    except Exception:
        # Invitation acceptance must not be rolled back by optional recording.
        # No identities, paths or manuscript content are included in the log.
        logger.warning('Automatic distribution intent could not be recorded')
        try:
            _record_capture_failure(db,manuscript_id,kind,invitation_id,canonical_utc(accepted_at))
        except Exception:
            logger.warning('Automatic distribution capture failure could not be recorded')
        return None
