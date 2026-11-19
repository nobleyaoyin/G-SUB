"""Author text editing using the isolated reviewer workflow fixture."""
from test_reviewer_download import ReviewerDownloadsTest
import importlib


class OnlineTextTest(ReviewerDownloadsTest):
    def setUp(self):
        super().setUp()
        importlib.import_module('migrations.014_online_document_versions').migrate(self.db_path)

    def prepare_text(self):
        self.manuscript.status = 'draft'
        self.manuscript.file_path = self.write(f'uploads/manuscripts/{self.mid}/original.txt', b'Original synthetic text')
        self.db.commit()
        self.current = self.author

    def test_edit_stale_history_and_original(self):
        self.prepare_text()
        url = f'/manuscripts/{self.mid}/online-text'
        opened = self.client.get(url); self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(opened.json()['content'], 'Original synthetic text')
        token = opened.json()['version']
        saved = self.client.post(url, json={'content':'First edit', 'expected_version':token})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.post(url, json={'content':'Stale edit', 'expected_version':token}).status_code, 409)
        opened = self.client.get(url); self.assertEqual(opened.json()['content'], 'First edit')
        self.assertEqual(self.client.post(url, json={'content':'Second edit', 'expected_version':opened.json()['version']}).status_code, 200)
        final = self.client.get(url).json()
        self.assertEqual(final['content'], 'Second edit'); self.assertEqual(len(final['history']), 2)
        self.assertEqual((self.root / f'uploads/manuscripts/{self.mid}/original.txt').read_bytes(), b'Original synthetic text')
        downloaded = self.client.get(f"/manuscripts/{self.mid}/versions/{final['history'][-1]['filename']}")
        self.assertEqual(downloaded.content, b'Second edit')
        self.assertEqual(self.client.get(f'/manuscripts/{self.mid}/download').content, b'Second edit')

    def test_role_stage_and_format_restrictions(self):
        self.prepare_text()
        url = f'/manuscripts/{self.mid}/online-text'
        self.current = self.reviewer; self.assertEqual(self.client.get(url).status_code, 404)
        self.current = self.editor; self.assertEqual(self.client.get(url).status_code, 404)
        self.current = self.author; self.manuscript.status = 'ready_for_peer_review'; self.db.commit()
        self.assertEqual(self.client.get(url).status_code, 409)
        self.manuscript.status = 'draft'; self.manuscript.file_path = self.pdf; self.db.commit()
        self.assertEqual(self.client.get(url).status_code, 415)
