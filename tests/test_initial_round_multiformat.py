"""Four-format first review handoff using only isolated fixtures."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException

from app import models
import app.routers.eic as eic
from tests import test_reviewer_download, test_secure_word_uploads


class InitialRoundMultiFormatTests(unittest.TestCase):
    def test_historical_docx_resource_bound(self):
        from app.routers.manuscripts import validate_manuscript_file
        oversized = test_secure_word_uploads.docx_bytes(b'x' * (17 * 1024 * 1024))
        with self.assertRaises(HTTPException):
            validate_manuscript_file('historic.docx', oversized, historical=True)

    def test_upload_approval_and_round_one_binding(self):
        formats = [
            ('pdf', b'%PDF-synthetic', 'application/pdf'),
            ('docx', test_secure_word_uploads.docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            ('doc', test_secure_word_uploads.doc_bytes(), 'application/msword'),
            ('txt', 'Synthetic text résumé\n'.encode(), 'text/plain'),
        ]
        for ext, data, mime in formats:
            with self.subTest(extension=ext):
                f = test_reviewer_download.ReviewerDownloadsTest('test_first_round_binding_and_access')
                f.setUp()
                try:
                    with patch.object(eic, 'BASE_DIR', f.root):
                        chief = models.User(name='Chief', email='chief@example.test', password_hash='x', role='eic')
                        m = models.Manuscript(title='Synthetic', abstract='Synthetic', author_id=f.author.user_id, status='initial_scan_passed', review_round=1)
                        f.db.add_all([chief, m]); f.db.commit(); f.mid = m.manuscript_id; f.manuscript = m
                        f.current = chief
                        inv = f.client.post('/eic/initial-editor/invite', json={'manuscript_id': f.mid, 'editor_id': f.editor.user_id})
                        self.assertEqual(inv.status_code, 201, inv.text)
                        f.current = f.editor
                        self.assertEqual(f.client.post(f"/eic/initial-editor/invitations/{inv.json()['invitation_id']}/respond", json={'decision':'accept'}).status_code, 200)
                        f.current = f.other
                        self.assertEqual(f.client.post(f'/eic/initial-editing/{f.mid}/submit', data={'comments':'x'}, files={'file':('edit.'+ext,data,mime)}).status_code, 403)
                        f.current = f.editor
                        res = f.client.post(f'/eic/initial-editing/{f.mid}/submit', data={'comments':'Edited'}, files={'file':('edit.'+ext,data,mime)})
                        self.assertEqual(res.status_code, 201, res.text); sid = res.json()['submission_id']
                        f.current = f.author
                        self.assertEqual(f.client.post(f'/eic/initial-editing/submissions/{sid}/pre-review-confirmation', json={'decision':'confirm','comments':'early'}).status_code, 409)
                        download = f.client.get(f'/eic/initial-editing/submissions/{sid}/download')
                        self.assertEqual(download.content, data); self.assertTrue(download.headers['content-type'].startswith(mime)); self.assertIn('.'+ext, download.headers['content-disposition'])
                        for user, action in ((f.author,'author-review'), (f.editor,'editor-approval'), (chief,'eic-approval')):
                            f.current=user
                            self.assertEqual(f.client.post(f'/eic/initial-editing/submissions/{sid}/{action}',json={'decision':'approve','comments':'Approved'}).status_code,200)
                        f.current=f.author
                        self.assertEqual(f.client.post(f'/eic/initial-editing/submissions/{sid}/pre-review-confirmation',json={'decision':'confirm','comments':'Confirmed'}).status_code,200)
                        assigned=f.assign(f.reviewer,1)
                        self.assertEqual(assigned.status_code,201,assigned.text); aid=assigned.json()['assignment_id']
                        f.current=f.reviewer; download=f.client.get(f'/assignments/{aid}/download')
                        self.assertEqual(download.content,data); self.assertTrue(download.headers['content-type'].startswith(mime)); self.assertIn('.'+ext,download.headers['content-disposition'])
                        f.current=f.other; self.assertEqual(f.client.get(f'/assignments/{aid}/download').status_code,403)
                        # Changing the manuscript's unrelated latest path cannot change the round-one binding.
                        m.file_path = f.write(f'uploads/manuscripts/{f.mid}/other.txt', b'other'); f.db.commit(); f.current=f.reviewer
                        self.assertEqual(f.client.get(f'/assignments/{aid}/download').content,data)
                        self.assertEqual((f.root / f.pdf).read_bytes(),b'%PDF-first')
                finally:
                    f.tearDown()


if __name__ == '__main__': unittest.main()
