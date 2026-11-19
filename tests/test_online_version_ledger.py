"""Online version history tests use a disposable synthetic SQLite fixture."""
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.test_reviewer_download import ReviewerDownloadsTest
from app.database import get_db
import app.main as main


class OnlineVersionLedgerTests(ReviewerDownloadsTest):
    def setUp(self):
        super().setUp()
        importlib.import_module('migrations.014_online_document_versions').migrate(self.db_path)

    def setup_draft(self):
        self.manuscript.status = 'draft'
        self.manuscript.file_path = self.write(f'uploads/manuscripts/{self.mid}/original.txt', b'Synthetic original')
        self.db.commit()
        self.current = self.author
        return f'/manuscripts/{self.mid}/online-text'

    def test_author_versions_survive_reconnect_and_authorize_download(self):
        url = self.setup_draft()
        opened = self.client.get(url).json()
        self.assertEqual(self.client.post(url,json={'content':'One','expected_version':opened['version'],'change_note':'Synthetic note'}).status_code,200)
        first = self.client.get(url).json()
        self.assertEqual(self.client.post(url,json={'content':'Two','expected_version':first['version']}).status_code,200)
        before = self.client.get(url).json()
        self.assertEqual([r['number'] for r in before['history']], [1,2])
        self.assertEqual(before['history'][0]['change_note'], 'Synthetic note')
        self.client.__exit__(None, None, None)
        self.db.close(); self.engine.dispose(); self.db = self.Session()
        self.client = TestClient(main.app); self.client.__enter__()
        after = self.client.get(url).json()
        self.assertEqual(after['history'], before['history'])
        version = f"{url}/versions/{after['history'][0]['id']}"
        self.assertEqual(self.client.get(version).content,b'One')
        self.current = self.reviewer
        self.assertEqual(self.client.get(version).status_code,404)
        self.current = self.author
        self.assertEqual((self.root/f'uploads/manuscripts/{self.mid}/original.txt').read_bytes(),b'Synthetic original')

    def test_author_submission_requires_selected_current_token(self):
        url = self.setup_draft()
        original = self.client.get(url).json()
        self.assertEqual(self.client.post(url,json={'content':'First','expected_version':original['version']}).status_code,200)
        first = self.client.get(url).json()
        self.assertEqual(self.client.post(url,json={'content':'Second','expected_version':first['version']}).status_code,200)
        endpoint = f'/manuscripts/{self.mid}/submit'
        self.assertEqual(self.client.post(endpoint,params={'expected_online_version':first['version']}).status_code,409)
        self.db.rollback()
        latest = self.client.get(url).json()
        self.assertEqual(self.client.post(endpoint,params={'expected_online_version':latest['version']}).status_code,200)

    def test_migration_is_idempotent_and_history_immutable(self):
        migration = importlib.import_module('migrations.014_online_document_versions')
        self.db.close(); self.engine.dispose()
        migration.migrate(self.db_path); migration.migrate(self.db_path)
        self.db = self.Session()
        self.manuscript = self.db.get(type(self.manuscript), self.mid)
        url = self.setup_draft()
        opened = self.client.get(url).json()
        self.assertEqual(self.client.post(url,json={'content':'One','expected_version':opened['version']}).status_code,200)
        with self.assertRaises(Exception):
            self.db.execute(text('DELETE FROM online_document_versions'))
        self.db.rollback()
        self.assertEqual(len(self.client.get(url).json()['history']),1)

    def test_write_lock_prevents_concurrent_ledger_changes(self):
        self.setup_draft()
        first = sqlite3.connect(self.db_path, timeout=.05)
        second = sqlite3.connect(self.db_path, timeout=.05)
        try:
            first.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError): second.execute('BEGIN IMMEDIATE')
        finally:
            first.rollback(); first.close(); second.close()

    def test_changed_source_rejects_submission(self):
        url = self.setup_draft()
        opened = self.client.get(url).json()
        self.assertEqual(self.client.post(url,json={'content':'Draft','expected_version':opened['version']}).status_code,200)
        selected = self.client.get(url).json()
        (self.root/f'uploads/manuscripts/{self.mid}/original.txt').write_bytes(b'Changed synthetic source')
        response = self.client.post(f'/manuscripts/{self.mid}/submit',params={'expected_online_version':selected['version']})
        self.assertEqual(response.status_code,409)
        self.db.rollback(); self.db.expire_all()
        self.assertEqual(self.db.get(type(self.manuscript), self.mid).status,'draft')

    def test_concurrent_saves_do_not_overwrite(self):
        url = self.setup_draft()
        token = self.client.get(url).json()['version']
        def session_override():
            session = self.Session()
            try: yield session
            finally: session.close()
        main.app.dependency_overrides[get_db] = session_override
        def save(content):
            return self.client.post(url,json={'content':content,'expected_version':token}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ('Concurrent one', 'Concurrent two')))
        self.assertEqual(sorted(results), [200,409])
        self.assertEqual(len(self.client.get(url).json()['history']),1)

    def test_concurrent_save_and_submission_do_not_substitute(self):
        url = self.setup_draft()
        token = self.client.get(url).json()['version']
        self.assertEqual(self.client.post(url,json={'content':'Selected','expected_version':token}).status_code,200)
        selected = self.client.get(url).json()['version']
        def session_override():
            session = self.Session()
            try: yield session
            finally: session.close()
        main.app.dependency_overrides[get_db] = session_override
        def save():
            return self.client.post(url,json={'content':'Concurrent draft','expected_version':selected}).status_code
        def submit():
            return self.client.post(f'/manuscripts/{self.mid}/submit',params={'expected_online_version':selected}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(save), pool.submit(submit)]
            statuses = [result.result() for result in results]
        self.assertEqual(sorted(statuses),[200,409])
        self.db.expire_all()
        manuscript = self.db.get(type(self.manuscript),self.mid)
        if statuses[1] == 200:
            self.assertEqual((self.root/manuscript.file_path).read_bytes(),b'Selected')
        else:
            self.assertEqual(manuscript.status,'draft')

    def test_missing_migration_fails_closed_for_editor(self):
        url = self.setup_draft()
        self.db.close(); self.engine.dispose()
        db = sqlite3.connect(self.db_path)
        db.execute('DROP TRIGGER online_versions_no_delete'); db.execute('DROP TRIGGER online_versions_no_update')
        db.execute('DROP TABLE online_document_versions')
        db.execute("DELETE FROM schema_migrations WHERE migration_id='014_online_document_versions'")
        db.commit(); db.close()
        self.db = self.Session()
        self.assertEqual(self.client.get(url).status_code,503)

    def test_save_commit_acknowledgement_loss_preserves_record_and_file(self):
        url = self.setup_draft()
        token = self.client.get(url).json()['version']
        commit = self.db.commit
        def lost_acknowledgement():
            commit()
            raise sqlite3.OperationalError('Synthetic lost acknowledgement')
        with patch.object(self.db,'commit',side_effect=lost_acknowledgement):
            response = self.client.post(url,json={'content':'Committed draft','expected_version':token})
        self.assertEqual(response.status_code,503)
        current = self.client.get(url).json()
        self.assertEqual(current['content'],'Committed draft')
        self.assertEqual(len(current['history']),1)
        self.assertEqual(self.client.get(f"{url}/versions/{current['history'][0]['id']}").content,b'Committed draft')
