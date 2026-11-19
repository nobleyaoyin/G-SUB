"""Local-only browser fixture: synthetic accounts, no pre-created manuscripts."""
import importlib.util
import os
from pathlib import Path
import secrets
import tempfile
root = Path(os.environ['REHEARSAL_ROOT']).resolve(strict=True)
if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith('gsub-rehearsal-'):
    raise RuntimeError('Refusing non-disposable root')
if any(root.iterdir()):
    raise RuntimeError('Refusing nonempty fixture root')
os.environ['MANUSCRIPT_MODE']='development'
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['SECRET_KEY']=secrets.token_hex(32)
import app.config as config
# Set the temporary data root before importing database, security or routers.
config.DATA_ROOT=root
config.PROJECT_ROOT=root
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
import uvicorn
from app.database import Base, get_db
from app import models
from app.security import hash_password
import app.main as main
import app.review_files as review_files
import app.routers.manuscripts as manuscripts
import app.routers.assignments as assignments
import app.routers.eic as eic
import app.routers.formatting as formatting

path = root / 'rehearsal.sqlite'
if path.exists(): raise RuntimeError('Refusing existing fixture database')
engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread':False})
@event.listens_for(engine,'connect')
def foreign_keys(connection, _): connection.execute('PRAGMA foreign_keys=ON')
excluded = {'review_round_files','review_assignment_files','reviewer_invitations','manuscript_review_policies','author_agreements','final_editor_invitations','final_editing_submission_invitations','formatter_invitations','formatting_submissions','prototype_publications','notification_events','email_outbox','email_delivery_attempts','user_email_verifications','email_verification_challenges','account_lifecycle_events','account_lifecycle','reviewer_invitation_invalidations'}
Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in excluded])
project = Path(__file__).resolve().parents[1]
for filename in ('001_reviewer_file_bindings.py','002_reviewer_invitations.py','003_two_reviewer_policy.py','004_author_agreements.py','005_final_editor_workflow.py','006_formatter_publication.py','007_email_outbox.py','008_email_verification.py','009_account_invitation_lifecycle.py','010_reviewer_profiles.py','014_online_document_versions.py'):
    spec=importlib.util.spec_from_file_location('fixture_migration_'+filename[:3],project/'migrations'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.migrate(path)
Session = sessionmaker(bind=engine,expire_on_commit=False)
with Session() as db:
    password=hash_password(os.environ.get('REHEARSAL_PASSWORD','Synthetic-Rehearsal-Password-472!'))
    for name,role in [('author','author'),('editor','editor'),('eic','eic'),('reviewer','reviewer'),('reviewer2','reviewer'),('reviewer3','reviewer'),('formatter','formatter')]:
        db.add(models.User(name=f'Synthetic {name.title()}',email=f'{name}@example.com',password_hash=password,role=role))
    db.commit()
def isolated_db():
    with Session() as db: yield db
main.engine=engine
for module in (review_files,manuscripts,assignments,eic,formatting): module.BASE_DIR=root
main.app.dependency_overrides[get_db]=isolated_db
uvicorn.run(main.app,host='127.0.0.1',port=int(os.environ['REHEARSAL_PORT']),log_level='error',access_log=False)
