"""Focused synthetic tests shared by Main and Stable Demo."""
import os
from unittest.mock import patch
from test_reviewer_download import ReviewerDownloadsTest
from app import models


class DemoBackendBoundaryTests(ReviewerDownloadsTest):
    def test_initial_screening_requires_eic_and_records_transition(self):
        chief = models.User(name='Synthetic EIC', email='scan-chief@example.com', password_hash='x', role='eic')
        manuscript = models.Manuscript(title='Synthetic scan', abstract='Synthetic', author_id=self.author.user_id, status='submitted', review_round=1)
        self.db.add_all([chief, manuscript]); self.db.flush()
        manuscript.file_path = self.write(f'uploads/manuscripts/{manuscript.manuscript_id}/scan.pdf', b'%PDF-synthetic')
        self.db.commit()
        url = f'/eic/manuscripts/{manuscript.manuscript_id}/initial-scan'
        payload = {'decision':'pass', 'comments':'Synthetic screening'}
        self.current = self.author
        self.assertEqual(self.client.post(url, json=payload).status_code, 403)
        self.current = chief
        result = self.client.post(url, json=payload)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()['manuscript_status'], 'initial_scan_passed')
        self.assertEqual(self.client.post(url, json=payload).status_code, 409)

    def test_onlyoffice_is_unavailable_when_disabled(self):
        with patch.dict(os.environ, {'GSUB_ONLYOFFICE_ENABLED':'0'}):
            self.current = self.author
            url = f'/onlyoffice/manuscripts/{self.mid}/author'
            self.assertEqual(self.client.get(url + '/availability').json(), {'available':False})
            self.assertEqual(self.client.post(url + '/sessions').status_code, 503)
