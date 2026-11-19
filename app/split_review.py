"""Conservative, read-only split summary for an authorized EIC caller."""
from collections import Counter
from sqlalchemy import inspect, select
from app.models import (Review, ReviewAssignment, ReviewAssignmentFile, ReviewerInvitation,
                        ReviewRoundFile, User, ReviewerInvitationInvalidation)


def split_review_status(db, manuscript):
    """First two distinct eligible completed reviews, ordered by submission time.

    Only accept/reject is a qualifying split. Revision or malformed recommendations
    are not interpreted. Additional attempts are other same-round assignments;
    declined/invalidated attempts do not block replacement.
    """
    round_no = manuscript.review_round
    assignments = db.scalars(select(ReviewAssignment).where(
        ReviewAssignment.manuscript_id == manuscript.manuscript_id,
        ReviewAssignment.review_round == round_no).order_by(ReviewAssignment.assignment_id)).all()
    invalidated = set()
    inspector = inspect(db.connection())
    if inspector.has_table('reviewer_invitation_invalidations'):
        columns = {col['name'] for col in inspector.get_columns('reviewer_invitation_invalidations')}
        if 'assignment_id' not in columns:
            raise ValueError('Invitation invalidation schema unavailable')
        ids = [a.assignment_id for a in assignments]
        if ids:
            invalidated = set(db.scalars(select(ReviewerInvitationInvalidation.assignment_id).where(
                ReviewerInvitationInvalidation.assignment_id.in_(ids))).all())
    candidates = []
    for assignment in assignments:
        if assignment.assignment_id in invalidated or assignment.status != 'completed': continue
        invitation = db.get(ReviewerInvitation, assignment.assignment_id)
        reviewer = db.get(User, assignment.reviewer_id)
        binding = db.get(ReviewAssignmentFile, assignment.assignment_id)
        source = db.get(ReviewRoundFile, binding.round_file_id) if binding else None
        review = db.scalar(select(Review).where(Review.assignment_id == assignment.assignment_id))
        if not (invitation and invitation.status == 'accepted' and reviewer and reviewer.role == 'reviewer'
                and source and source.manuscript_id == manuscript.manuscript_id and source.review_round == round_no
                and review and review.submitted_at and review.recommendation in ('accept','reject','revision')):
            continue
        candidates.append((assignment, review))
    counts = Counter(assignment.reviewer_id for assignment, _ in candidates)
    eligible = [(assignment, review) for assignment, review in candidates if counts[assignment.reviewer_id] == 1]
    eligible.sort(key=lambda item: (item[1].submitted_at, item[1].review_id))
    first = eligible[:2]
    recommendations = [review.recommendation for _, review in eligible]
    if len(first) < 2: classification = 'insufficient'
    elif any(review.recommendation == 'revision' for _, review in first): classification = 'ambiguous'
    elif {review.recommendation for _, review in first} == {'accept','reject'}: classification = 'split'
    else: classification = 'aligned'
    originals = {assignment.assignment_id for assignment, _ in first}
    extras = []
    if classification == 'split':
        for assignment in assignments:
            if assignment.assignment_id in originals: continue
            invitation = db.get(ReviewerInvitation, assignment.assignment_id)
            state = 'invalidated' if assignment.assignment_id in invalidated else (invitation.status if invitation else 'legacy')
            extras.append({'assignment_id': assignment.assignment_id, 'invitation_status': state,
                           'review_status': assignment.status})
    blocking = any(item['invitation_status'] not in ('declined','invalidated') for item in extras)
    return {'review_round': round_no, 'eligible_completed': len(eligible), 'recommendations': recommendations,
            'classification': classification, 'additional_assignments': extras,
            'can_invite_additional': classification == 'split' and not blocking and manuscript.status in ('ready_for_peer_review','revised')}
