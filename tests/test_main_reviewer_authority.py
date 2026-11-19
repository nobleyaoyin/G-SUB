"""Synthetic in-memory authority controls; no migrations or persistent data."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import User
from app.main_reviewer_authority import (
    AuthenticatedEditorialAuthority, AuthenticatedReviewerAuthority, AuthorityUnavailable,
)

@pytest.fixture
def context():
    engine = create_engine('sqlite:///:memory:')
    User.__table__.create(engine)
    with engine.begin() as c:
        for sql in (
            'CREATE TABLE account_lifecycle (user_id INTEGER, state TEXT, sequence INTEGER, auth_generation INTEGER, last_event_id TEXT)',
            'CREATE TABLE account_lifecycle_events (user_id INTEGER, event_id TEXT, sequence INTEGER, from_state TEXT, to_state TEXT, auth_generation INTEGER)',
            'CREATE TABLE manuscripts (manuscript_id INTEGER, status TEXT, review_round INTEGER)',
            'CREATE TABLE review_assignments (assignment_id INTEGER, manuscript_id INTEGER, reviewer_id INTEGER, status TEXT, review_round INTEGER)',
            'CREATE TABLE reviewer_invitations (assignment_id INTEGER, status TEXT)',
            'CREATE TABLE reviewer_invitation_invalidations (assignment_id INTEGER)',
        ): c.exec_driver_sql(sql)
        c.exec_driver_sql("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (1,'R','r@example.invalid','x','reviewer','2020-01-01'),(2,'E','e@example.invalid','x','eic','2020-01-01')")
        c.exec_driver_sql("INSERT INTO account_lifecycle VALUES (1,'active',1,1,'r'),(2,'active',1,1,'e')")
        c.exec_driver_sql("INSERT INTO account_lifecycle_events VALUES (1,'r',1,NULL,'active',1),(2,'e',1,NULL,'active',1)")
        c.exec_driver_sql("INSERT INTO manuscripts VALUES (7,'ready_for_peer_review',1),(8,'draft',1)")
        c.exec_driver_sql("INSERT INTO review_assignments VALUES (9,7,1,'assigned',1)")
        c.exec_driver_sql("INSERT INTO reviewer_invitations VALUES (9,'accepted')")
    with Session(engine) as session:
        reviewer = session.get(User, 1)
        editor = session.get(User, 2)
        raw = session.connection().connection.driver_connection
        raw.execute('BEGIN')
        yield session, raw, reviewer, editor
        session.rollback()
    engine.dispose()


def test_reviewer_scope_positive_and_negative(context):
    session, db, reviewer, _ = context
    authority = AuthenticatedReviewerAuthority(reviewer)
    assert authority.authorize(db, reviewer, 'read_artifact', 7) == 1
    for action, manuscript in [('read_artifact', 8), ('bind', 7)]:
        with pytest.raises(AuthorityUnavailable): authority.authorize(db, reviewer, action, manuscript)
    db.execute("UPDATE reviewer_invitations SET status='pending'")
    with pytest.raises(AuthorityUnavailable): authority.authorize(db, reviewer, 'read_artifact', 7)
    db.execute("UPDATE reviewer_invitations SET status='accepted'")
    assert authority.authorize(db, reviewer, 'read_artifact', 7) == 1
    db.execute('INSERT INTO reviewer_invitation_invalidations VALUES (9)')
    with pytest.raises(AuthorityUnavailable): authority.authorize(db, reviewer, 'read_artifact', 7)


def test_eic_scope_positive_and_negative(context):
    session, db, reviewer, editor = context
    authority = AuthenticatedEditorialAuthority(editor)
    assert authority.authorize(db, editor, 'bind', 7) == 2
    with pytest.raises(AuthorityUnavailable): authority.authorize(db, editor, 'bind', 8)
    with pytest.raises(AuthorityUnavailable): authority.authorize(db, reviewer, 'bind', 7)
    db.execute("UPDATE account_lifecycle SET state='disabled' WHERE user_id=2")
    with pytest.raises(AuthorityUnavailable): authority.authorize(db, editor, 'bind', 7)

@pytest.mark.parametrize('statement', [
    "UPDATE reviewer_invitations SET status='declined'",
    "UPDATE review_assignments SET review_round=2",
    "UPDATE review_assignments SET reviewer_id=2",
    "UPDATE review_assignments SET status='completed'",
    "UPDATE manuscripts SET status='revised',review_round=2",
    "DELETE FROM account_lifecycle WHERE user_id=1",
])
def test_reviewer_denials_have_positive_control(context, statement):
    _, db, reviewer, _ = context
    authority = AuthenticatedReviewerAuthority(reviewer)
    assert authority.authorize(db, reviewer, 'read_artifact', 7) == 1
    db.execute(statement)
    with pytest.raises(AuthorityUnavailable):
        authority.authorize(db, reviewer, 'read_artifact', 7)
