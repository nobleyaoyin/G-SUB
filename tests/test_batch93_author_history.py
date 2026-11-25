"""Owner-only generation history and verified formatting downloads."""
from unittest.mock import patch
from datetime import datetime, timezone
from app import models
import app.routers.eic as eic
import app.routers.formatting as formatting
import app.routers.manuscripts as manuscripts
from tests import test_formatting as formatting_fixture


def test_owner_history_private_and_approved_download():
    f=formatting_fixture.FormattingTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root),patch.object(manuscripts,'BASE_DIR',f.root):
            f.prepare_final();f.current=f.author
            initial=f.client.get(f'/manuscripts/{f.mid}/generation-history');assert initial.status_code==200
            assert any(item['title']=='Author-confirmed editorial source' and item['review_round']==1 for item in initial.json()['entries'])
            inv=f.f_invite(f.formatter);assert inv.status_code==201,inv.text;iid=inv.json()['invitation_id']
            assert f.f_action(f.formatter,f'/formatting/invitations/{iid}/respond',{'decision':'accept'}).status_code==200
            f.current=f.formatter
            sent=f.client.post(f'/formatting/invitations/{iid}/submit',data={'comments':'Private formatter comment'},files={'file':('secret-name.pdf',b'%PDF-author-approved','application/pdf')});assert sent.status_code==201,sent.text;sid=sent.json()['submission_id']
            url=f'/manuscripts/{f.mid}/generation-history';download=f'{url}/formatting/{sid}/download'
            f.current=f.author;before=f.client.get(url);assert before.status_code==200,before.text
            assert not any((x.get('download') or {}).get('kind') == 'approved_formatting' for x in before.json()['entries'])
            assert any((x.get('download') or {}).get('kind') == 'approved_final' for x in before.json()['entries'])
            assert f.client.get(download).status_code==404
            eic_url=f'/eic/manuscripts/{f.mid}/document-timeline';eic_download=f'{eic_url}/formatting/{sid}/download'
            f.current=f.chief;pending=f.client.get(eic_download)
            assert pending.status_code==200 and pending.content==b'%PDF-author-approved'
            assert f.f_action(f.author,f'/formatting/submissions/{sid}/author-review',{'decision':'approve','comments':'author-private'}).status_code==200
            assert f.f_action(f.chief,f'/formatting/submissions/{sid}/eic-review',{'decision':'approve','comments':'eic-private'}).status_code==200
            f.current=f.chief
            timeline=f.client.get(eic_url);assert timeline.status_code==200,timeline.text
            agreement=next(x for x in timeline.json()['events'] if x['artifact_type']=='agreement')
            assert 'template approval pending' in agreement['status']
            eic_row=next(x for x in timeline.json()['events'] if x['id']==f'formatting:{sid}')
            assert eic_row['download']=={'kind':'formatting','id':sid} and eic_row['integrity']=='verified on download'
            eic_bytes=f.client.get(eic_download);assert eic_bytes.status_code==200 and eic_bytes.content==b'%PDF-author-approved'
            f.current=f.author;response=f.client.get(url);assert response.status_code==200,response.text
            assert response.headers['cache-control']=='no-store' and response.headers['x-content-type-options']=='nosniff'
            row=next(x for x in response.json()['entries'] if x['id']==f'formatting:{sid}')
            assert row['status']=='Approved' and row['download']=={'kind':'approved_formatting','id':sid}
            for secret in ('eic-private','author-private','Private formatter comment','secret-name.pdf','reviewer@example.com',str(f.root),'file_path'):
                assert secret not in response.text
            data=f.client.get(download);assert data.status_code==200 and data.content==b'%PDF-author-approved'
            assert data.headers['cache-control']=='no-store' and 'secret-name' not in data.headers['content-disposition']
            artifact=f.db.get(models.FormattingSubmission,sid);path=f.root/artifact.file_path;path.write_bytes(b'%PDF-tampered');assert f.client.get(download).status_code==409
            f.current=f.chief;assert f.client.get(eic_download).status_code==409
            path.write_bytes(b'%PDF-author-approved')
            recorded_path=artifact.file_path;artifact.file_path=f'uploads/formatting/{f.mid}/synthetic-missing.pdf';f.db.commit()
            assert f.client.get(eic_download).status_code==409
            f.current=f.author;assert f.client.get(download).status_code==409
            artifact.file_path=recorded_path;f.db.commit()
            f.current=f.other_author;assert f.client.get(url).status_code==404 and f.client.get(download).status_code==404
            f.current=f.reviewer;assert f.client.get(url).status_code==403 and f.client.get(download).status_code==403
            f.current=f.author;assert f.client.get(f'/manuscripts/999999/generation-history').status_code==404
            assert f.client.get(f'{url}/formatting/999999/download').status_code==404
            other=models.Manuscript(title='Other synthetic manuscript',abstract='Synthetic',author_id=f.author.user_id,status='submitted',review_round=1)
            f.db.add(other);f.db.commit()
            assert f.client.get(f'/manuscripts/{other.manuscript_id}/generation-history/formatting/{sid}/download').status_code==404
            f.current=f.chief;assert f.client.get(f'/eic/manuscripts/{other.manuscript_id}/document-timeline/formatting/{sid}/download').status_code==404
            f.current=f.author;assert f.client.get(eic_download).status_code==403
            f.current=f.chief;assert f.client.post(f'/formatting/submissions/{sid}/publish').status_code==201
            f.current=f.author;after=f.client.get(url);assert any(x['status']=='Published (local prototype)' for x in after.json()['entries'])
    finally:f.tearDown()


def test_author_history_rejects_cross_manuscript_final_invitation_and_orders_records():
    f=formatting_fixture.FormattingTest(); f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root),patch.object(manuscripts,'BASE_DIR',f.root):
            f.prepare_final(); f.current=f.author
            url=f'/manuscripts/{f.mid}/generation-history'
            original=f.client.get(url); assert original.status_code==200
            rows=original.json()['entries']
            final=next(x for x in rows if x['stage']=='Final Editing')
            times=[datetime.fromisoformat(x['recorded_at'].replace('Z','+00:00')).replace(tzinfo=timezone.utc)
                   for x in rows if x['recorded_at']]
            assert times == sorted(times)
            submission_id=int(final['id'].split(':')[1])
            binding=f.db.get(models.FinalEditingSubmissionInvitation,submission_id)
            other=models.Manuscript(title='Other synthetic',abstract='Synthetic',author_id=f.author.user_id,status='final_editing',review_round=1)
            f.db.add(other);f.db.flush()
            wrong=models.FinalEditorInvitation(manuscript_id=other.manuscript_id,editor_id=f.editor.user_id,
                invited_by=f.chief.user_id,status='accepted')
            f.db.add(wrong);f.db.flush();binding.invitation_id=wrong.invitation_id;f.db.commit()
            result=f.client.get(url);assert result.status_code==200
            assert not any(x['id']==final['id'] for x in result.json()['entries'])
            assert 'file_path' not in result.text and 'synthetic.pdf' not in result.text
    finally:f.tearDown()
