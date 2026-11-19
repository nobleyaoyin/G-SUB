"""Isolated TXT upload and PDF-proof regression coverage."""
import hashlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import models
from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
import app.routers.eic as eic
import app.routers.formatting as formatting
from tests.test_final_workflow import FinalWorkflowTest


class SafeSubsetTest(unittest.TestCase):
    def setUp(self):
        self.fx = FinalWorkflowTest('test_invitation_replacement_corrections_and_confirmation')
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)

    def test_txt_validation(self):
        self.assertEqual(validate_manuscript_file('paper.TXT', 'Résumé\n'.encode()), ('.txt', 'text/plain'))
        for data in (b'', b'\xff', b'hello\x00world', b'%PDF-fake', b'PK\x03\x04fake', b'   '):
            with self.subTest(data=data), self.assertRaises(HTTPException):
                validate_manuscript_file('paper.txt', data)
        with self.assertRaises(HTTPException) as too_large:
            validate_manuscript_file('paper.txt', b'a' * (MAX_MANUSCRIPT_FILE_SIZE + 1))
        self.assertEqual(too_large.exception.status_code, 413)
        with self.assertRaises(HTTPException): validate_manuscript_file('paper.exe', b'hello')

    def test_author_txt_revision_keeps_round_one_binding(self):
        f = self.fx
        f.select_single_blind_policy()
        original = f.assign(f.reviewer, 1)
        self.assertEqual(original.status_code, 201, original.text)
        aid = original.json()['assignment_id']
        f.manuscript.status = 'revision_required'; f.db.commit()
        f.current = f.other
        denied = f.client.post(f'/manuscripts/{f.mid}/upload', files={'file': ('revision.txt', b'text', 'text/plain')})
        self.assertEqual(denied.status_code, 403)
        f.current = f.author
        payload = 'Synthetic revision résumé\n'.encode()
        upload = f.client.post(f'/manuscripts/{f.mid}/upload', files={'file': ('revision.txt', payload, 'text/plain')})
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(f.client.post(f'/manuscripts/{f.mid}/resubmit', json={'abstract': 'Revised'}).status_code, 200)
        new = f.assign(f.other, 2)
        self.assertEqual(new.status_code, 201, new.text)
        new_id = new.json()['assignment_id']
        download = f.client.get(f'/assignments/{new_id}/download')
        self.assertEqual(download.content, payload)
        self.assertTrue(download.headers['content-type'].startswith('text/plain'))
        self.assertIn('.txt', download.headers['content-disposition'])
        f.current = f.reviewer
        self.assertEqual(f.client.get(f'/assignments/{aid}/download').content, b'%PDF-first')
        self.assertEqual((f.root / f.pdf).read_bytes(), b'%PDF-first')

    def test_final_text_source_txt_proof_and_hash(self):
        f = self.fx
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            agreement = f.reach_agreement(); f.current = f.author
            self.assertEqual(f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={'decision': 'accept', 'agreement_version': agreement['agreement_version']}).status_code, 200)
            invitation = f.invite(f.editor).json()['invitation_id']
            self.assertEqual(f.respond(f.editor, invitation, 'accept').status_code, 200)
            f.current = f.reviewer
            self.assertEqual(f.client.post(f'/eic/final-editing/{f.mid}/submit', data={'comments': 'x'}, files={'file': ('final.txt', b'text', 'text/plain')}).status_code, 403)
            f.current = f.editor
            for invalid in (b'\xff', b'text\x00binary'):
                self.assertEqual(f.client.post(f'/eic/final-editing/{f.mid}/submit', data={'comments': 'x'}, files={'file': ('final.txt', invalid, 'text/plain')}).status_code, 400)
            text = b'Final source document\n'
            response = f.client.post(f'/eic/final-editing/{f.mid}/submit', data={'comments': 'Edited'}, files={'file': ('final.txt', text, 'text/plain')})
            self.assertEqual(response.status_code, 201, response.text); sid = response.json()['submission_id']
            for who, role in ((f.chief, 'eic'), (f.author, 'author')):
                self.assertEqual(f.review(who, sid, role, 'approve').status_code, 200)
            f.current = f.author
            downloaded = f.client.get(f'/eic/final-editing/submissions/{sid}/download')
            self.assertEqual(downloaded.content, text); self.assertTrue(downloaded.headers['content-type'].startswith('text/plain'))
            self.assertIn('.txt', downloaded.headers['content-disposition'])
            formatter = models.User(name='Synthetic formatter', email='format@example.com', password_hash='x', role='formatter')
            f.db.add(formatter); f.db.commit(); f.current = f.chief
            inv = f.client.post('/formatting/invite', json={'manuscript_id': f.mid, 'formatter_id': formatter.user_id}).json()['invitation_id']
            f.current = formatter
            self.assertEqual(f.client.post(f'/formatting/invitations/{inv}/respond', json={'decision': 'accept'}).status_code, 200)
            source = f.client.get(f'/formatting/invitations/{inv}/input')
            self.assertEqual(source.content, text); self.assertTrue(source.headers['content-type'].startswith('text/plain'))
            self.assertIn('.txt', source.headers['content-disposition'])
            proof = b'Formatted proof text\\n'
            uploaded = f.client.post(f'/formatting/invitations/{inv}/submit', data={'comments': 'proof'}, files={'file': ('proof.txt', proof, 'text/plain')})
            self.assertEqual(uploaded.status_code, 201, uploaded.text); proof_id = uploaded.json()['submission_id']
            f.current = f.author
            self.assertEqual(f.client.post(f'/formatting/submissions/{proof_id}/author-review', json={'decision':'approve', 'comments':'ok'}).status_code, 200)
            f.current = f.chief
            self.assertEqual(f.client.post(f'/formatting/submissions/{proof_id}/eic-review', json={'decision':'approve', 'comments':'ok'}).status_code, 200)
            self.assertEqual(f.client.post(f'/formatting/submissions/{proof_id}/publish').status_code, 201)
            f.db.expire_all(); stored = f.db.get(models.FormattingSubmission, proof_id)
            self.assertEqual(stored.sha256, hashlib.sha256(proof).hexdigest())
            self.assertEqual((f.root / stored.file_path).read_bytes(), proof)


if __name__ == '__main__': unittest.main()
