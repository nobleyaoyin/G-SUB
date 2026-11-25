"""Milestones follow real synthetic Final Editing and Formatting operations."""
from unittest.mock import patch
from app.routers import eic, formatting
from tests import test_formatting as fixtures


def test_approved_proof_and_publication_milestones_are_role_filtered():
    f = fixtures.FormattingTest(); f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root), patch.object(formatting, 'BASE_DIR', f.root):
            f.prepare_final()
            invitation = f.f_invite(f.formatter); assert invitation.status_code == 201, invitation.text
            iid = invitation.json()['invitation_id']
            f.current = f.author
            url = f'/manuscripts/{f.mid}/progress'
            response = f.client.get(url); assert response.status_code == 200, response.text
            stages = {item['name']:item for item in response.json()['stages']}
            for name in ('Peer Review', 'EIC Decision', 'Author Agreement'):
                assert stages[name]['state'] == 'completed'
                assert stages[name]['steps'][0]['state'] == 'completed'
            assert stages['Final Editing']['state'] == 'completed'
            assert stages['Final Editing']['steps'][0]['state'] == 'completed'
            assert stages['Formatting']['state'] == 'current'
            assert stages['Publication']['state'] == 'pending'
            assert f.f_action(f.formatter, f'/formatting/invitations/{iid}/respond', {'decision':'accept'}).status_code == 200
            f.current = f.formatter
            proof = f.client.post(f'/formatting/invitations/{iid}/submit', data={'comments':'PRIVATE SYNTHETIC'}, files={'file':('proof.pdf',b'%PDF-synthetic-proof','application/pdf')})
            assert proof.status_code == 201, proof.text; sid = proof.json()['submission_id']
            assert f.f_action(f.author, f'/formatting/submissions/{sid}/author-review', {'decision':'approve','comments':'Synthetic'}).status_code == 200
            assert f.f_action(f.chief, f'/formatting/submissions/{sid}/eic-review', {'decision':'approve','comments':'Synthetic'}).status_code == 200
            published = f.f_action(f.chief, f'/formatting/submissions/{sid}/publish', {})
            assert published.status_code == 201, published.text
            f.current = f.author; response = f.client.get(url)
            assert response.status_code == 200 and 'PRIVATE SYNTHETIC' not in response.text
            stages = {item['name']:item for item in response.json()['stages']}
            assert stages['Formatting']['state'] == 'completed' and stages['Formatting']['steps'][0]['state'] == 'completed'
            assert stages['Publication']['state'] == 'completed' and stages['Publication']['steps'][0]['state'] == 'completed'
            f.current = f.formatter; response = f.client.get(url)
            assert response.status_code == 200 and all('steps' not in item for item in response.json()['stages'])
            f.current = f.reviewer; assert f.client.get(url).status_code == 404
    finally:
        f.tearDown()
