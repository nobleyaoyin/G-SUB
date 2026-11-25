"""Prepare/serve one disposable, synthetic-only DOCX browser test fixture.

This does not create Docker resources. The generated stage-specific records are
synthetic setup, not evidence that a complete manuscript workflow was run.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parents[1]


def checked_root(value):
    root = Path(value)
    temporary = Path(tempfile.gettempdir()).resolve()
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or not root.name.startswith('gsub-docx-102-') or root.resolve().parent != temporary
            or stat.S_IMODE(root.stat().st_mode) & 0o077):
        raise RuntimeError('Refusing non-disposable fixture root')
    return root.resolve()


def private_write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(value)


def app_for_root(root, credentials):
    os.environ.update({'PYTHON_DOTENV_DISABLED':'1','MANUSCRIPT_MODE':'development',
        'SECRET_KEY':credentials['jwt_secret'], 'GSUB_ONLYOFFICE_ENABLED':'1',
        'GSUB_ONLYOFFICE_SECRET':credentials['onlyoffice_secret'],
        'GSUB_ONLYOFFICE_SERVER_ORIGIN':'http://127.0.0.1:8088',
        'GSUB_ONLYOFFICE_APP_ORIGIN':'http://host.docker.internal:8090'})
    import app.config as config
    config.DATA_ROOT = root
    config.PROJECT_ROOT = root
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.database import get_db
    import app.main as main
    import app.review_files as review_files
    import app.routers.manuscripts as manuscripts
    import app.routers.assignments as assignments
    import app.routers.eic as eic
    import app.routers.formatting as formatting
    import app.onlyoffice_docx as onlyoffice_docx
    engine = create_engine(f'sqlite:///{root / "fixture.sqlite"}', connect_args={'check_same_thread':False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _): connection.execute('PRAGMA foreign_keys=ON')
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    def isolated_db():
        with Session() as db: yield db
    main.engine = engine
    for module in (review_files, manuscripts, assignments, eic, formatting, onlyoffice_docx): module.BASE_DIR = root
    main.app.dependency_overrides[get_db] = isolated_db
    return main.app, engine, Session


def prepare():
    root = Path(tempfile.mkdtemp(prefix='gsub-docx-102-')).resolve()
    os.chmod(root, 0o700)
    creds = {'password':secrets.token_urlsafe(24)+'Aa1!', 'jwt_secret':secrets.token_hex(32),
             'onlyoffice_secret':secrets.token_hex(32)}
    private_write(root/'fixture.json', json.dumps(creds))
    private_write(root/'onlyoffice.env', 'JWT_ENABLED=true\nJWT_SECRET='+creds['onlyoffice_secret']+'\n')
    app, engine, Session = app_for_root(root, creds)
    from app.database import Base
    from app import models
    from app.security import hash_password
    from synthetic_onlyoffice.academic_fixture import academic_docx
    excluded = {'review_round_files','review_assignment_files','reviewer_invitations','manuscript_review_policies','author_agreements','final_editor_invitations','final_editing_submission_invitations','formatter_invitations','formatting_submissions','prototype_publications','notification_events','email_outbox','email_delivery_attempts','user_email_verifications','email_verification_challenges','account_lifecycle_events','account_lifecycle','reviewer_invitation_invalidations'}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in excluded])
    for name in ('001_reviewer_file_bindings','002_reviewer_invitations','003_two_reviewer_policy','004_author_agreements','005_final_editor_workflow','006_formatter_publication','007_email_outbox','008_email_verification','009_account_invitation_lifecycle','010_reviewer_profiles','014_online_document_versions','016_onlyoffice_sessions'):
        spec=importlib.util.spec_from_file_location('fixture_'+name, PROJECT/'migrations'/f'{name}.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.migrate(root/'fixture.sqlite')
    with Session() as db:
        password=hash_password(creds['password'])
        users={}
        for name,role in [('author','author'),('editor','editor'),('eic','eic'),('reviewer','reviewer'),('other','author')]:
            user=models.User(name=f'Synthetic {name.title()}',email=f'{name}@example.com',password_hash=password,role=role)
            db.add(user); db.flush(); users[name]=user
        documents=[]
        for title,status,round_no in [('Author DOCX revision','revision_required',1),('Initial Editor DOCX','initial_editing',1),('Final Editor DOCX','final_editing',2)]:
            m=models.Manuscript(title=title,abstract='Synthetic test manuscript.',author_id=users['author'].user_id,status=status,review_round=round_no)
            db.add(m);db.flush()
            directory=root/'uploads'/'manuscripts'/str(m.manuscript_id); directory.mkdir(parents=True,mode=0o700)
            path=directory/'round_2_synthetic.docx'; path.write_bytes(academic_docx()); os.chmod(path,0o600)
            m.file_path=str(path.relative_to(root)); documents.append(m)
        initial, final = documents[1:]
        db.add(models.InitialEditorInvitation(manuscript_id=initial.manuscript_id,editor_id=users['editor'].user_id,invited_by=users['eic'].user_id,status='accepted'))
        db.add(models.FinalEditorInvitation(manuscript_id=final.manuscript_id,editor_id=users['editor'].user_id,invited_by=users['eic'].user_id,status='accepted'))
        decision=models.EICDecision(manuscript_id=final.manuscript_id,eic_id=users['eic'].user_id,review_round=2,decision='accept',comments='Synthetic stage fixture')
        db.add(decision);db.flush()
        db.add(models.AuthorAgreement(manuscript_id=final.manuscript_id,decision_id=decision.decision_id,author_id=users['author'].user_id,agreement_version='fixture',agreement_text='Synthetic fixture',status='accepted',responded_at=datetime.now(timezone.utc)))
        db.add(models.ReviewRoundFile(manuscript_id=final.manuscript_id,review_round=2,source_kind='author_revision',confirmation_id=None,file_path=final.file_path))
        db.commit()
        ids=[m.manuscript_id for m in documents]
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        tokens={}
        for name in ('author','editor','eic','reviewer','other'):
            response=client.post('/users/login',json={'email':f'{name}@example.com','password':creds['password']})
            if response.status_code != 200: raise RuntimeError(f'Synthetic login failed: {name}: {response.status_code}')
            tokens[name]=response.json()['access_token']
        for role,index,stage in [('author',0,'author'),('editor',1,'initial'),('editor',2,'final')]:
            response=client.get(f'/onlyoffice/manuscripts/{ids[index]}/{stage}/availability',headers={'Authorization':'Bearer '+tokens[role]})
            if response.status_code != 200 or not response.json().get('available'): raise RuntimeError(f'Synthetic {stage} fixture unavailable: {response.status_code}')
        for role in ('reviewer','other','eic'):
            response=client.get(f'/onlyoffice/manuscripts/{ids[0]}/author/availability',headers={'Authorization':'Bearer '+tokens[role]})
            if response.status_code == 200 and response.json().get('available'): raise RuntimeError('Unexpected synthetic access')
    engine.dispose()
    print('Prepared disposable synthetic fixture:', root)
    print('Synthetic roles and credentials are in its private fixture.json; document stages were seeded for targeted tests.')
    return root


def serve(root):
    root=checked_root(root)
    path=root/'fixture.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError('Unsafe synthetic credentials file')
    database=root/'fixture.sqlite'
    if database.is_symlink() or not database.is_file() or database.stat().st_nlink != 1:
        raise RuntimeError('Missing or unsafe synthetic database')
    creds=json.loads(path.read_text())
    app, _, _ = app_for_root(root,creds)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8090,log_level='warning',access_log=False)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('prepare')
    server=sub.add_parser('serve'); server.add_argument('root')
    args=parser.parse_args()
    if args.action == 'prepare': prepare()
    else: serve(args.root)
