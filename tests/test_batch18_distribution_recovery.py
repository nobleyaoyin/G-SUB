"""Read-only synthetic recovery inventory; no production database or files."""
import hashlib
import sqlite3
from app.distribution_recovery import inspect_distribution
from app.reviewer_artifact_storage import ArtifactStorage
from tests.test_batch17b_distribution_migration import database, migration


def test_readonly_diagnostics_distinguish_states_without_deleting(database,tmp_path):
    migration.migrate(database)
    root=(tmp_path/'private-objects');root.mkdir(mode=0o700)
    content=b'Synthetic content';digest=hashlib.sha256(content).hexdigest();stamp='2026-01-01T00:00:00.000000Z'
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for i,sid in enumerate(('a'*32,'b'*32,'c'*32,'d'*32)):
            db.execute('INSERT INTO distribution_reservations VALUES('+','.join('?'*12)+')',(sid,1,1,'editor_source',None,None,digest,len(content),'txt',f'synthetic-key-000{i}', 'f'*64,stamp))
        db.execute('INSERT INTO distribution_artifacts VALUES('+','.join('?'*12)+')',('e'*32,1,'editor_source',1,'d'*32,digest,len(content),'txt',None,None,1,stamp))
        db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',('1'*32,1,'e'*32,2,'editor',1,None,None,None,1,'manual','not_requested','not_requested','synthetic-grant-0001','f'*64,stamp))
        db.execute('INSERT INTO distribution_revocations VALUES(?,?,?,?)',('1'*32,1,'synthetic',stamp))
        db.execute('INSERT INTO distribution_reservations VALUES('+','.join('?'*12)+')',('7'*32,1,1,'editor_source',None,None,digest,len(content),'txt','synthetic-key-0007','f'*64,stamp))
        db.execute('INSERT INTO distribution_artifacts VALUES('+','.join('?'*12)+')',('8'*32,1,'editor_source',2,'7'*32,digest,len(content),'txt',None,None,1,stamp))
    with ArtifactStorage(root.resolve()) as store:
        store.publish_reserved('b'*32,content,'txt');store.publish_reserved('d'*32,content,'txt')
        (root/('c'*32)).write_bytes(b'wrong content')
        (root/('9'*32)).write_bytes(b'unregistered')
        (root/('.stage-'+'a'*32)).write_bytes(b'partial')
        before={p.name:p.read_bytes() for p in root.iterdir()}
        connection=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            connection.execute('PRAGMA query_only=ON'); report=inspect_distribution(connection,store)
        finally:connection.close()
        by_id={row['storage_id']:row for row in report['records']}
        assert by_id['a'*32]['status']=='pending_without_object' and by_id['a'*32]['staging_present']
        assert by_id['b'*32]['status']=='published_without_artifact'
        assert by_id['c'*32]['status']=='integrity_unavailable_or_mismatch'
        assert by_id['d'*32]['status']=='verified_artifact' and by_id['d'*32]['revoked_grant_count']==1
        assert by_id['7'*32]['status']=='missing_object'
        assert by_id['9'*32]['status']=='unregistered_object'
        assert report['dry_run'] and before=={p.name:p.read_bytes() for p in root.iterdir()}
