"""Author projection must not claim a mismatched initial editing source."""
from app import models
from tests import test_reviewer_download as fixtures


def test_confirmation_and_round_source_require_matching_approved_file():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        # Existing synthetic fixture starts with an EIC-approved submission and
        # Author confirmation; invitation/policy and round binding use HTTP.
        f.select_single_blind_policy()
        result=f.assign(f.reviewer,1);assert result.status_code==201,result.text
        f.current=f.author
        url=f'/manuscripts/{f.mid}/generation-history'
        response=f.client.get(url);assert response.status_code==200,response.text
        initial=[x for x in response.json()['entries'] if x['stage']=='Initial Editing']
        assert len(initial)==1 and initial[0]['review_round']==1
        record=f.db.query(models.ReviewRoundFile).filter_by(manuscript_id=f.mid,review_round=1).one()
        # Corrupt only this disposable fixture's association, never a real file.
        record.file_path=f'uploads/initial_editing/{f.mid}/different.pdf';f.db.commit()
        response=f.client.get(url);assert response.status_code==200
        initial=[x for x in response.json()['entries'] if x['stage']=='Initial Editing']
        assert len(initial)==1 and initial[0]['review_round'] is None
        confirmation=f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one()
        confirmation.file_path=f'uploads/initial_editing/{f.mid}/unrelated.pdf';f.db.commit()
        response=f.client.get(url);assert response.status_code==200
        assert not any(x['stage']=='Initial Editing' for x in response.json()['entries'])
        assert 'initial editing evidence inconsistent' in response.json()['unavailable_sources']
        assert 'unrelated.pdf' not in response.text and 'different.pdf' not in response.text
        f.current=f.other
        assert f.client.get(url).status_code==403  # Reviewer cannot use the Author route.
    finally:f.tearDown()
