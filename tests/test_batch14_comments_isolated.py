"""Migration-free staff-comment authorization with synthetic in-memory SQLite."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import get_db
from app.models import (User, Manuscript, GeneralComment, InitialEditorInvitation,
                        FinalEditorInvitation, FormatterInvitation, FinalEditingSubmission)
from app.routers.general_comments import router
from app.routers.users import get_current_user


def test_staff_comment_roles_and_wrong_manuscript():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    for model in (User, Manuscript, GeneralComment, InitialEditorInvitation, FinalEditorInvitation, FinalEditingSubmission, FormatterInvitation):
        model.__table__.create(engine, checkfirst=True)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    users = {role: User(name=role, email=f'{role}@example.invalid', password_hash='synthetic', role=('editor' if role in ('initial', 'final', 'unassigned') else role)) for role in ('author','reviewer','eic','initial','final','unassigned','formatter')}
    session.add_all(users.values()); session.flush()
    first = Manuscript(title='Synthetic', abstract='Synthetic', author_id=users['author'].user_id, status='submitted')
    second = Manuscript(title='Other', abstract='Synthetic', author_id=users['author'].user_id, status='submitted')
    session.add_all([first,second]); session.flush()
    session.add_all([InitialEditorInvitation(manuscript_id=first.manuscript_id, editor_id=users['initial'].user_id, invited_by=users['eic'].user_id, status='accepted'), FinalEditorInvitation(manuscript_id=first.manuscript_id, editor_id=users['final'].user_id, invited_by=users['eic'].user_id, status='accepted')]); session.flush()
    final = FinalEditingSubmission(manuscript_id=first.manuscript_id,editor_id=users['final'].user_id,file_path='synthetic.pdf',comments='synthetic')
    session.add(final); session.flush()
    session.add(FormatterInvitation(manuscript_id=first.manuscript_id,formatter_id=users['formatter'].user_id,invited_by=users['eic'].user_id,final_submission_id=final.submission_id,status='accepted'));session.commit()
    app=FastAPI();app.include_router(router);current={'user':users['eic']}
    app.dependency_overrides[get_db]=lambda: session
    app.dependency_overrides[get_current_user]=lambda: current['user']
    with TestClient(app) as client:
        assert client.post(f'/manuscripts/{first.manuscript_id}/general-comments', json={'content':'Staff synthetic'}).status_code == 201
        for role in ('eic','initial','final','formatter'):
            current['user']=users[role]
            response=client.get(f'/manuscripts/{first.manuscript_id}/general-comments')
            assert response.status_code == 200 and response.json()[0]['content'] == 'Staff synthetic'
        for role in ('author','reviewer','unassigned'):
            current['user']=users[role]
            assert client.get(f'/manuscripts/{first.manuscript_id}/general-comments').status_code == 403
        current['user']=users['initial']
        assert client.get(f'/manuscripts/{second.manuscript_id}/general-comments').status_code == 403
    session.close();engine.dispose()
