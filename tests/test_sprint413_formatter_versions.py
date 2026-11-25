"""Formatter revisions retain separately authorized, integrity-checked proofs."""
import hashlib
from unittest.mock import patch
from app import models
from app.routers import eic, formatting
from tests import test_formatting as fixtures


def test_formatted_proof_replacement_preserves_exact_history():
    f = fixtures.FormattingTest(); f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter); assert invitation.status_code == 201, invitation.text
            iid = invitation.json()['invitation_id']
            assert f.f_action(f.formatter, f'/formatting/invitations/{iid}/respond', {'decision':'accept'}).status_code == 200
            def upload(content):
                f.current = f.formatter
                return f.client.post(f'/formatting/invitations/{iid}/submit', data={'comments':'Synthetic'}, files={'file':('proof.pdf',content,'application/pdf')})
            first = b'%PDF-first synthetic proof'; second = b'%PDF-second synthetic proof'
            one = upload(first); assert one.status_code == 201, one.text
            sid1 = one.json()['submission_id']
            assert upload(second).status_code == 409
            assert f.f_action(f.author, f'/formatting/submissions/{sid1}/author-review', {'decision':'request_revision','comments':'Synthetic'}).status_code == 200
            two = upload(second); assert two.status_code == 201, two.text
            sid2 = two.json()['submission_id']; assert sid1 != sid2
            for actor in (f.formatter, f.chief, f.author):
                f.current = actor
                assert f.client.get(f'/formatting/submissions/{sid1}/download').content == first
                assert f.client.get(f'/formatting/submissions/{sid2}/download').content == second
            f.current = f.other_formatter
            assert f.client.get(f'/formatting/submissions/{sid1}/download').status_code == 403
            f.current = f.reviewer
            assert f.client.get(f'/formatting/submissions/{sid2}/download').status_code == 403
            f.current = f.formatter
            record = f.db.get(models.FormattingSubmission, sid1)
            assert record.sha256 == hashlib.sha256(first).hexdigest()
            (f.root / record.file_path).write_bytes(b'%PDF-synthetic-tamper')
            assert f.client.get(f'/formatting/submissions/{sid1}/download').status_code == 409
            assert f.client.get(f'/formatting/submissions/{sid2}/download').content == second
    finally:
        f.tearDown()
