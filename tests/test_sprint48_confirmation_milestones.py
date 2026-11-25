"""Initial Editing milestone completion requires matching recorded evidence."""
from app import models
from tests import test_reviewer_download as fixtures


def test_confirmation_milestone_rejects_mismatched_author_or_file():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief=models.User(name='Synthetic EIC',email='sprint48-eic@example.com',password_hash='x',role='eic')
        f.db.add(chief);f.db.commit()
        confirmation=f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one()
        original_path=confirmation.file_path;original_author=confirmation.author_id
        def read(actor):
            f.current=actor;response=f.client.get(f'/manuscripts/{f.mid}/progress')
            assert response.status_code==200,response.text
            stage=next(x for x in response.json()['stages'] if x['name']=='Initial Editing')
            steps={x['name']:x['state'] for x in stage['steps']}
            assert 'file_path' not in response.text and 'comments' not in str(stage)
            return stage['state'],steps['Pre-review Author Confirmation']
        assert read(f.author)==('completed','completed')
        assert read(chief)==('completed','completed')
        # Only disposable fixture evidence is corrupted; no transition is claimed.
        confirmation.file_path=f'uploads/initial_editing/{f.mid}/different.pdf';f.db.commit()
        assert read(f.author)==('unknown','unknown')
        assert read(chief)==('unknown','unknown')
        confirmation.file_path=original_path;confirmation.author_id=f.other.user_id;f.db.commit()
        assert read(f.author)==('unknown','unknown')
        confirmation.author_id=original_author;f.db.commit()
        assert read(f.author)==('completed','completed')
        f.current=f.other;assert f.client.get(f'/manuscripts/{f.mid}/progress').status_code==404
    finally:f.tearDown()
