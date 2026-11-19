"""Migration-free invitation metadata tests with isolated synthetic records."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.models import User, Manuscript, InitialEditorInvitation, FinalEditorInvitation
from app.routers import eic, final_workflow
from app.routers.users import get_current_user


def test_preview_abstract_is_returned_only_to_accepted_invited_editor():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session=sessionmaker(bind=engine,expire_on_commit=False)()
    roles={r:User(name=r,email=f'{r}@example.invalid',password_hash='synthetic',role='editor' if r in ('editor','other') else r) for r in ('author','editor','other','eic','reviewer')}
    session.add_all(roles.values());session.flush()
    manuscripts=[]
    for idx,state in enumerate(('pending','accepted','declined')):
        m=Manuscript(title=f'Title {idx}',abstract=f'Abstract {idx}',author_id=roles['author'].user_id,status='initial_editing');session.add(m);session.flush();manuscripts.append(m)
        session.add(InitialEditorInvitation(manuscript_id=m.manuscript_id,editor_id=roles['editor'].user_id,invited_by=roles['eic'].user_id,status=state))
        session.add(FinalEditorInvitation(manuscript_id=m.manuscript_id,editor_id=roles['editor'].user_id,invited_by=roles['eic'].user_id,status=state))
    draft=Manuscript(title='Draft',abstract='Private draft abstract',author_id=roles['author'].user_id,status='draft')
    session.add(draft);session.flush()
    session.add(FinalEditorInvitation(manuscript_id=draft.manuscript_id,editor_id=roles['editor'].user_id,invited_by=roles['eic'].user_id,status='accepted'))
    session.commit()
    current={'user':roles['editor']};app=FastAPI();app.include_router(eic.router);app.include_router(final_workflow.router)
    app.dependency_overrides[get_db]=lambda:session
    app.dependency_overrides[get_current_user]=lambda:current['user']
    with TestClient(app) as client:
        initial=client.get('/eic/initial-editing/my');final=client.get('/final-workflow/my')
        assert initial.status_code==200 and final.status_code==200
        initial_data={v['invitation']['status']:v for v in initial.json()}
        final_data={v['status']:v for v in final.json() if v['manuscript_id'] != draft.manuscript_id}
        assert initial_data['accepted']['invitation_abstract']=='Abstract 1'
        assert initial_data['pending']['invitation_abstract'] is None
        assert 'declined' not in initial_data
        assert final_data['accepted']['invitation_abstract']=='Abstract 1'
        assert final_data['pending']['invitation_abstract'] is None
        assert final_data['declined']['invitation_abstract'] is None
        assert next(v for v in final.json() if v['manuscript_id']==draft.manuscript_id)['invitation_abstract'] is None
        current['user']=roles['other']
        assert client.get('/eic/initial-editing/my').json()==[]
        assert client.get('/final-workflow/my').json()==[]
        current['user']=roles['reviewer']
        assert client.get('/eic/initial-editing/my').status_code==403
        assert client.get('/final-workflow/my').status_code==403
    session.close();engine.dispose()


def test_eic_overview_reports_only_matching_round_bindings():
    from app.models import ReviewAssignment, ReviewRoundFile, ReviewAssignmentFile
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session=sessionmaker(bind=engine,expire_on_commit=False)()
    users={r:User(name=r,email=f'{r}-history@example.invalid',password_hash='synthetic',role=r) for r in ('author','eic','reviewer')}
    session.add_all(users.values());session.flush()
    manuscript=Manuscript(title='Synthetic',abstract='Synthetic',author_id=users['author'].user_id,status='revised',review_round=2)
    draft=Manuscript(title='Private',abstract='Private',author_id=users['author'].user_id,status='draft')
    session.add_all([manuscript,draft]);session.flush()
    good=ReviewAssignment(manuscript_id=manuscript.manuscript_id,reviewer_id=users['reviewer'].user_id,assigned_by=users['eic'].user_id,review_round=2,status='assigned')
    wrong=ReviewAssignment(manuscript_id=manuscript.manuscript_id,reviewer_id=users['reviewer'].user_id,assigned_by=users['eic'].user_id,review_round=3,status='assigned')
    source=ReviewRoundFile(manuscript_id=manuscript.manuscript_id,review_round=2,source_kind='author_revision',file_path='private/synthetic.txt')
    session.add_all([good,wrong,source]);session.flush()
    session.add_all([ReviewAssignmentFile(assignment_id=good.assignment_id,round_file_id=source.round_file_id),ReviewAssignmentFile(assignment_id=wrong.assignment_id,round_file_id=source.round_file_id)]);session.commit()
    current={'user':users['eic']};app=FastAPI();app.include_router(eic.router)
    app.dependency_overrides[get_db]=lambda:session
    app.dependency_overrides[get_current_user]=lambda:current['user']
    with TestClient(app) as client:
        response=client.get(f'/eic/manuscripts/{manuscript.manuscript_id}/overview')
        assert response.status_code==200, response.text
        data={item['assignment_id']:item for item in response.json()['assignments']}
        assert data[good.assignment_id]['recorded_round_binding']['round_file_id']==source.round_file_id
        assert data[wrong.assignment_id]['recorded_round_binding'] is None
        assert 'private/synthetic.txt' not in response.text
        assert client.get(f'/eic/manuscripts/{draft.manuscript_id}/overview').status_code==404
        current['user']=users['reviewer']
        assert client.get(f'/eic/manuscripts/{manuscript.manuscript_id}/overview').status_code==403
        current['user']=users['author']
        assert client.get(f'/eic/manuscripts/{manuscript.manuscript_id}/overview').status_code==403
    session.close();engine.dispose()
