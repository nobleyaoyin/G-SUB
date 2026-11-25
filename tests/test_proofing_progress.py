"""Proofing is a read-only projection of an authorized formatting submission."""
from unittest.mock import patch

from tests import test_formatting
import app.routers.eic as eic
import app.routers.formatting as formatting


def test_proofing_projection_and_revision():
    f = test_formatting.FormattingTest('test_formatting_and_publication')
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter).json()['invitation_id']
            f.current = f.author
            assert f.client.get(f'/manuscripts/{f.mid}/progress').json()['formatting_substage'] == 'formatter_invited'
            f.current = f.formatter
            assert f.client.get(f'/manuscripts/{f.mid}/progress').status_code == 404
            assert f.f_action(f.formatter, f'/formatting/invitations/{invitation}/respond', {'decision':'accept'}).status_code == 200
            f.current = f.author
            before = f.client.get(f'/manuscripts/{f.mid}/progress').json()
            assert before['current_stage'] == 'Formatting'
            assert before['formatting_substage'] == 'awaiting_formatted_proof'
            f.current = f.formatter
            response = f.client.post(f'/formatting/invitations/{invitation}/submit', data={'comments':'Proof'}, files={'file':('proof.pdf', b'%PDF-proof', 'application/pdf')})
            assert response.status_code == 201, response.text
            sid = response.json()['submission_id']
            f.current = f.author
            progress = f.client.get(f'/manuscripts/{f.mid}/progress')
            assert progress.status_code == 200, progress.text
            assert progress.json()['current_stage'] == 'Proofing'
            assert progress.json()['formatting_substage'] == 'pending_author'
            for actor in (f.chief, f.formatter):
                f.current = actor
                assert f.client.get(f'/manuscripts/{f.mid}/progress').json()['formatting_substage'] == 'pending_author'
            f.current = f.editor
            assert f.client.get(f'/manuscripts/{f.mid}/progress').json()['formatting_substage'] is None
            f.current = f.reviewer
            assert f.client.get(f'/manuscripts/{f.mid}/progress').status_code == 404
            assert {x['name']:x['state'] for x in progress.json()['stages']}['Formatting'] == 'completed'
            formatting_step = next(x['steps'][0] for x in progress.json()['stages'] if x['name'] == 'Formatting')
            assert formatting_step == {'name': 'Formatted proof submitted', 'state': 'completed'}
            steps = next(x['steps'] for x in progress.json()['stages'] if x['name'] == 'Proofing')
            assert [x['state'] for x in steps] == ['current', 'unknown']
            assert f.f_action(f.author, f'/formatting/submissions/{sid}/author-review', {'decision':'request_revision','comments':'Correct proof'}).status_code == 200
            f.current = f.author
            revision = f.client.get(f'/manuscripts/{f.mid}/progress').json()
            assert revision['current_stage'] == 'Formatting'
            assert revision['formatting_substage'] == 'author_revision_requested'
            f.current = f.other_formatter
            assert f.client.get(f'/manuscripts/{f.mid}/progress').status_code == 404
            f.current = f.formatter
            replacement = f.client.post(f'/formatting/invitations/{invitation}/submit', data={'comments':'Corrected proof'}, files={'file':('proof.pdf', b'%PDF-corrected', 'application/pdf')})
            assert replacement.status_code == 201, replacement.text
            sid = replacement.json()['submission_id']
            assert f.f_action(f.author, f'/formatting/submissions/{sid}/author-review', {'decision':'approve','comments':'OK'}).status_code == 200
            f.current = f.author
            progress = f.client.get(f'/manuscripts/{f.mid}/progress').json()
            assert progress['formatting_substage'] == 'pending_eic'
            assert [x['state'] for x in next(x['steps'] for x in progress['stages'] if x['name'] == 'Proofing')] == ['completed', 'current']
            assert f.f_action(f.chief, f'/formatting/submissions/{sid}/eic-review', {'decision':'request_revision','comments':'Revise'}).status_code == 200
            f.current = f.author
            eic_revision = f.client.get(f'/manuscripts/{f.mid}/progress').json()
            assert eic_revision['current_stage'] == 'Formatting'
            assert eic_revision['formatting_substage'] == 'eic_revision_requested'
            f.current = f.formatter
            replacement = f.client.post(f'/formatting/invitations/{invitation}/submit', data={'comments':'Corrected again'}, files={'file':('proof.pdf', b'%PDF-corrected-again', 'application/pdf')})
            assert replacement.status_code == 201, replacement.text
            sid = replacement.json()['submission_id']
            assert f.f_action(f.author, f'/formatting/submissions/{sid}/author-review', {'decision':'approve','comments':'OK'}).status_code == 200
            assert f.f_action(f.chief, f'/formatting/submissions/{sid}/eic-review', {'decision':'approve','comments':'OK'}).status_code == 200
            f.current = f.author
            approved = f.client.get(f'/manuscripts/{f.mid}/progress').json()
            assert approved['current_stage'] == 'Proofing'
            assert approved['formatting_substage'] == 'approved'
            assert f.f_action(f.chief, f'/formatting/submissions/{sid}/publish', {}).status_code == 201
            f.current = f.author
            stages = {x['name']:x['state'] for x in f.client.get(f'/manuscripts/{f.mid}/progress').json()['stages']}
            assert stages['Proofing'] == 'completed'
            assert stages['Publication'] == 'completed'
    finally:
        f.tearDown()


def test_inconsistent_proof_review_evidence_is_unavailable():
    from app import models
    f = test_formatting.FormattingTest('test_formatting_and_publication')
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter).json()['invitation_id']
            assert f.f_action(f.formatter, f'/formatting/invitations/{invitation}/respond', {'decision':'accept'}).status_code == 200
            f.current = f.formatter
            response = f.client.post(f'/formatting/invitations/{invitation}/submit', data={'comments':'Proof'}, files={'file':('proof.pdf', b'%PDF-proof', 'application/pdf')})
            assert response.status_code == 201
            # Deliberately inconsistent disposable fixture: no Author review event.
            row = f.db.get(models.FormattingSubmission, response.json()['submission_id'])
            row.status = 'pending_eic'
            f.db.commit()
            f.current = f.author
            result = f.client.get(f'/manuscripts/{f.mid}/progress')
            assert result.status_code == 200
            assert result.json()['formatting_substage'] is None
            assert result.json()['current_stage'] is None
            assert result.json()['participant_task']['task_state'] == 'unavailable'
    finally:
        f.tearDown()


def test_duplicate_active_proof_evidence_is_unavailable():
    from sqlalchemy import text
    from app import models
    f = test_formatting.FormattingTest('test_formatting_and_publication')
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter).json()['invitation_id']
            assert f.f_action(f.formatter, f'/formatting/invitations/{invitation}/respond', {'decision':'accept'}).status_code == 200
            f.current = f.formatter
            response = f.client.post(f'/formatting/invitations/{invitation}/submit', data={'comments':'Proof'}, files={'file':('proof.pdf', b'%PDF-proof', 'application/pdf')})
            assert response.status_code == 201
            original = f.db.get(models.FormattingSubmission, response.json()['submission_id'])
            # Simulate a legacy/corrupt disposable DB with its protective index absent.
            f.db.execute(text('DROP INDEX uq_formatting_current'))
            f.db.add(models.FormattingSubmission(manuscript_id=f.mid, invitation_id=invitation,
                file_path=original.file_path, sha256=original.sha256, status='pending_author', comments='synthetic duplicate'))
            f.db.commit()
            f.current = f.author
            result = f.client.get(f'/manuscripts/{f.mid}/progress')
            assert result.status_code == 200
            assert result.json()['current_stage'] is None
            assert result.json()['formatting_substage'] is None
            assert result.json()['participant_task']['task_state'] == 'unavailable'
    finally:
        f.tearDown()


def test_missing_final_approval_evidence_makes_stage_unavailable():
    from app import models
    f = test_formatting.FormattingTest('test_formatting_and_publication')
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter).json()['invitation_id']
            assert f.f_action(f.formatter, f'/formatting/invitations/{invitation}/respond', {'decision':'accept'}).status_code == 200
            current = f.db.get(models.FormatterInvitation, invitation)
            final = f.db.get(models.FinalEditingSubmission, current.final_submission_id)
            # Corrupt only the disposable fixture; do not manufacture a workflow transition.
            final.author_reviewed_at = None
            f.db.commit()
            f.current = f.author
            result = f.client.get(f'/manuscripts/{f.mid}/progress')
            assert result.status_code == 200
            assert result.json()['current_stage'] is None
            assert result.json()['formatting_substage'] is None
            assert result.json()['participant_task']['task_state'] == 'unavailable'
    finally:
        f.tearDown()


def test_declined_formatter_invitation_remains_in_formatting():
    f = test_formatting.FormattingTest('test_formatting_and_publication')
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter).json()['invitation_id']
            assert f.f_action(f.formatter, f'/formatting/invitations/{invitation}/respond', {'decision':'decline'}).status_code == 200
            f.current = f.author
            result = f.client.get(f'/manuscripts/{f.mid}/progress')
            assert result.status_code == 200
            assert result.json()['current_stage'] == 'Formatting'
            assert result.json()['formatting_substage'] == 'formatter_declined'
    finally:
        f.tearDown()
