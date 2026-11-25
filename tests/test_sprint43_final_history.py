"""Approved final-edit history download uses independent owner authorization."""
from unittest.mock import patch
from app import models
from app.routers import eic, formatting, manuscripts
from tests import test_formatting as fixtures


def test_approved_final_history_download_is_scoped_and_safe():
    f=fixtures.FormattingTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root),patch.object(manuscripts,'BASE_DIR',f.root):
            # The existing fixture performs the actual agreement, invitation and approval HTTP workflow.
            f.prepare_final();f.current=f.author
            url=f'/manuscripts/{f.mid}/generation-history'
            history=f.client.get(url);assert history.status_code==200,history.text
            row=next(x for x in history.json()['entries'] if x['stage']=='Final Editing')
            assert row['status']=='Approved; file integrity unavailable'
            assert row['download']['kind']=='approved_final';sid=row['download']['id']
            download=f'{url}/final-editing/{sid}/download'
            response=f.client.get(download);assert response.status_code==200 and response.content==b'%PDF-approved-final'
            assert response.headers['cache-control']=='no-store' and response.headers['x-content-type-options']=='nosniff'
            assert str(f.root) not in history.text and 'file_path' not in history.text
            eic_url=f'/eic/manuscripts/{f.mid}/document-timeline/final-editing/{sid}/download'
            assert f.client.get(eic_url).status_code==403
            f.current=f.chief
            timeline=f.client.get(f'/eic/manuscripts/{f.mid}/document-timeline');assert timeline.status_code==200
            event=next(x for x in timeline.json()['events'] if x['id']==f'final:{sid}')
            assert event['download']=={'kind':'final_editing','id':sid} and event['integrity']=='unavailable'
            result=f.client.get(eic_url);assert result.status_code==200 and result.content==response.content
            f.current=f.other_author;assert f.client.get(download).status_code==404
            f.current=f.reviewer;assert f.client.get(download).status_code==403
            f.current=f.author
            other=models.Manuscript(title='Synthetic other',abstract='Synthetic',author_id=f.author.user_id,status='submitted',review_round=1)
            f.db.add(other);f.db.commit()
            assert f.client.get(f'/manuscripts/{other.manuscript_id}/generation-history/final-editing/{sid}/download').status_code==404
            f.current=f.chief;assert f.client.get(f'/eic/manuscripts/{other.manuscript_id}/document-timeline/final-editing/{sid}/download').status_code==404
            f.current=f.author
            submission=f.db.get(models.FinalEditingSubmission,sid)
            # Corrupt synthetic fixture metadata only to test fail-closed behavior.
            original=submission.file_path;submission.file_path=f'uploads/final_editing/{f.mid}/missing.pdf';f.db.commit()
            assert f.client.get(download).status_code==409
            submission.file_path=original;submission.status='pending_author';f.db.commit()
            assert f.client.get(download).status_code==404
    finally:f.tearDown()
