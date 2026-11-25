"""Disposable localhost-only A6 browser fixture; never point at existing data."""
import os
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['SECRET_KEY']='synthetic-browser-only-signing-key-32482942'
from pathlib import Path
import tempfile
import uvicorn
import app.main as main
from app.security import hash_password
from app import reviewer_artifact_service as service, reviewer_artifact_evidence as evidence
from app.reviewer_artifact_storage import ArtifactStorage
from app.reviewer_demo_download import DemoArtifactContext, reviewer_demo_artifact_context
from tests import test_blind_demo_eic_http as fixture, test_reviewer_artifact_service as af, test_artifact_evidence as ef
from tests.test_reviewer_artifact_binding import T

f=fixture.EICDemoHTTPTests('test_disabled_and_authorization');f.setUp()
root=f.root.resolve()
if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith('gsub-outbox-'):
    raise RuntimeError('Refusing non-disposable root')
f.f.enable()
db=f.db
password_hash=hash_password('Synthetic-Test-Password-472!')
db.execute("UPDATE users SET password_hash=? WHERE user_id IN (1,2,5)",(password_hash,))
db.execute("UPDATE users SET email='eic@example.com' WHERE user_id=5")
db.execute("UPDATE users SET name='Synthetic Unique Reviewer' WHERE user_id=2")
db.execute("UPDATE users SET name='Synthetic Manuscript Author' WHERE user_id=1")
for uid in (7, 8):
    db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (?,?,?,?, 'reviewer',?)", (uid, f'Synthetic Reviewer {uid}', f'reviewer{uid}@example.com', password_hash, T))
    db.execute("INSERT INTO account_lifecycle_events VALUES (?,?,1,NULL,'active',1,5,?,'initial_enrollment')", (f'split-active-{uid}', uid, T))
    db.execute("INSERT INTO account_lifecycle VALUES (?,'active',1,1,?)", (uid, f'split-active-{uid}'))
db.execute("UPDATE manuscripts SET title='Synthetic blind manuscript', abstract='Synthetic abstract' WHERE manuscript_id=3")
db.execute("INSERT INTO review_round_files(round_file_id,manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (3,3,1,'initial_editing',3,'uploads/initial_editing/3/source.pdf',?)",(T,)); db.commit()
source=af.SyntheticProvenance(root,3,3,'uploads/initial_editing/3/source.pdf')
proof=ef.SyntheticPriorProof(source);proof.proof='b'*32
private=root/'browser-private';private.mkdir(mode=0o700); storage=ArtifactStorage(private)
auth=af.SyntheticAuthority(3,5)
db.execute('BEGIN IMMEDIATE');sid=evidence.capture_source(db,auth.eic,auth,proof,source,3,3,0)
artifact=service.prepare(db,auth.editor,auth,source,storage,3,3,b'Anonymous synthetic browser document','txt',1)
evidence.approve_with_evidence(db,auth.eic,auth,source,storage,artifact.artifact_id,sid,1,checklist_acknowledged=True);db.commit()
context=DemoArtifactContext(proof,source,storage)
main.app.dependency_overrides[reviewer_demo_artifact_context]=lambda:context
try:
    uvicorn.run(main.app,host='127.0.0.1',port=int(os.environ['A6_BROWSER_PORT']),log_level='error',access_log=False)
finally:
    storage.close();f.doCleanups()
