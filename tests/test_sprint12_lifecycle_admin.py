"""Synthetic offline approval and lifecycle administration tests."""
import hashlib,importlib,json,os,sqlite3,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from app.models import User
from app.lifecycle_bootstrap import bootstrap,validate_approval
from app.bootstrap_nonce_ledger import reserve_nonce
from test_batch38_eic_proof import fixture

migration=importlib.import_module('migrations.039_lifecycle_administration')

def fixture_reserve(fd,nonce,digest,operator):
    # Emulate a privileged ledger directory only in the synthetic fixture.
    original=os.fstat
    def synthetic_stat(item):
        info=original(item)
        return SimpleNamespace(st_mode=info.st_mode,st_uid=0) if item==fd else info
    with patch('app.bootstrap_nonce_ledger.os.fstat',side_effect=synthetic_stat):
        return reserve_nonce(fd,nonce,digest,operator)

def reserved_bootstrap(raw,bundle,key,path,target,reference):
    payload,digest,_,operator=validate_approval(bundle,key,path,target,reference)
    directory=path.parent/'synthetic-nonce-ledger';directory.mkdir(mode=0o700,exist_ok=True)
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:reservation=fixture_reserve(fd,payload['nonce'],digest,operator)
    finally:os.close(fd)
    return bootstrap(raw,bundle,key,path,target,reference,reservation=reservation)

def approval(path,uid,email,owner,operator):
    st=path.stat();now=int(time.time())
    pub=operator.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    data={'version':1,'database':str(path),'device':st.st_dev,'inode':st.st_ino,'target_user_id':uid,
          'target_email_sha256':hashlib.sha256(email.strip().lower().encode()).hexdigest(),
          'operator_public_key':pub.hex(),'approval_reference':'SYNTHETIC-APPROVAL','issued_at':now,'expires_at':now+300,'nonce':'1'*64}
    msg=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
    return {'payload':data,'owner_signature':owner.sign(b'GSUB-LIFECYCLE-OWNER-v1\0'+msg).hex(),
            'operator_signature':operator.sign(b'GSUB-LIFECYCLE-OPERATOR-v1\0'+msg).hex()}

def test_offline_bootstrap_and_admin_operations(fixture):
    from test_batch40_reviewer_candidates import ready, CHECKS
    from test_sprint7_candidate_provenance import submit
    from test_sprint6_docx_preparation import word_document
    f,chief,headers,aid,sid,_,_=ready(fixture)
    migration.migrate(f.db_path);migration.migrate(f.db_path)
    importlib.import_module('migrations.038_candidate_preparation_provenance').migrate(f.db_path)
    admin=User(name='Synthetic Admin',email='admin-sprint12@example.com',password_hash='x',role='eic')
    target=User(name='Synthetic Target',email='target-sprint12@example.com',password_hash='x',role='eic')
    f.db.add_all([admin,target]);f.db.commit()
    owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate()
    key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    signed=approval(f.db_path,admin.user_id,admin.email,owner,operator)
    with sqlite3.connect(f.db_path) as raw:
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
        result=reserved_bootstrap(raw,signed,key,f.db_path,admin.user_id,'SYNTHETIC-APPROVAL');raw.commit()
    assert result['status']=='active'
    with sqlite3.connect(f.db_path) as raw:
        assert json.loads(raw.execute('select approval_bundle from lifecycle_admin_bootstrap').fetchone()[0])==signed
    with sqlite3.connect(f.db_path) as raw:
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
        try:reserved_bootstrap(raw,signed,key,f.db_path,admin.user_id,'SYNTHETIC-APPROVAL')
        except (ValueError,FileExistsError):raw.rollback()
        else:raise AssertionError('Bootstrap replay accepted')
    endpoint=f'/lifecycle-admin/eics/{target.user_id}/actions'
    body={'action':'enroll','request_id':'synthetic-enroll','reason':'Synthetic appointment','expected_sequence':0,'expected_generation':0}
    assert f.client.post(endpoint,headers=headers(f.author),json=body).status_code==403
    assert f.client.post(endpoint,headers=headers(f.reviewer),json=body).status_code==403
    assert f.client.post(endpoint,headers=headers(f.editor),json=body).status_code==403
    assert f.client.post(endpoint,headers=headers(chief),json=body).status_code==403
    assert f.client.post(endpoint,headers=headers(admin),json={**body,'reason':'   '}).status_code==409
    # EIC-only administration must not silently enroll another role.
    with sqlite3.connect(f.db_path) as raw:
        before = raw.execute("SELECT count(*) FROM lifecycle_eic_enrollments").fetchone()[0]
        reviewer_state = raw.execute("SELECT * FROM account_lifecycle WHERE user_id=?", (f.reviewer.user_id,)).fetchone()
    reviewer_endpoint=f'/lifecycle-admin/eics/{f.reviewer.user_id}/actions'
    assert f.client.post(reviewer_endpoint,headers=headers(admin),json=body).status_code==409
    with sqlite3.connect(f.db_path) as raw:
        assert raw.execute("SELECT count(*) FROM lifecycle_eic_enrollments").fetchone()[0] == before
        assert raw.execute("SELECT * FROM account_lifecycle WHERE user_id=?", (f.reviewer.user_id,)).fetchone() == reviewer_state
    assert f.client.post(endpoint,headers=headers(admin),json=body).json()['status']=='enrolled_not_active'
    assert f.client.post(endpoint,headers=headers(admin),json=body).status_code==409
    body.update(action='activate',request_id='synthetic-activate')
    assert f.client.post(endpoint,headers=headers(admin),json=body).json()['status']=='active'
    old=headers(target)
    candidate=f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation'
    importlib.import_module('migrations.023_reviewer_candidate_intake').migrate(f.db_path)
    assert f.client.get(candidate,headers=old).status_code==200
    body.update(action='disable',request_id='synthetic-disable',expected_sequence=1,expected_generation=1)
    assert f.client.post(endpoint,headers=headers(admin),json=body).json()['status']=='disabled'
    assert f.client.get(candidate,headers=old).status_code==403
    body.update(action='reactivate',request_id='synthetic-reactivate',expected_sequence=2,expected_generation=2)
    assert f.client.post(endpoint,headers=headers(admin),json=body).json()['status']=='active'
    assert f.client.get(candidate,headers=old).status_code==403
    assert f.client.get(candidate,headers=headers(target)).status_code==200
    history=f.client.get(f'/lifecycle-admin/eics/{target.user_id}/history',headers=headers(admin))
    assert history.status_code==200 and [e['to_state'] for e in history.json()['events']]==['active','disabled','active']
    bootstrap_history=f.client.get(f'/lifecycle-admin/eics/{admin.user_id}/history',headers=headers(admin))
    assert bootstrap_history.status_code==200
    assert bootstrap_history.json()['events'][0]['actor_kind']=='offline_operator'
    assert bootstrap_history.json()['events'][0]['actor_user_id'] is None
    assert f.client.get('/lifecycle-admin/eics',headers=headers(admin)).status_code==200
    prepared=submit(f,admin,headers,sid)
    assert prepared.status_code==201
    candidate_base=f"/eic/manuscripts/{f.mid}/reviewer-candidates/{prepared.json()['candidate_id']}"
    info=f.client.get(candidate_base+'/processing',headers=headers(admin)).json()
    context={'expected_sha256':info['prepared_sha256'],'expected_artifact_version':info['artifact_version'],'expected_review_round':info['review_round']}
    assert f.client.post(candidate_base+'/verify',headers=headers(admin),json={**CHECKS,'filename_verified':True,**context}).status_code==200
    assert f.client.post(candidate_base+'/approve',headers=headers(admin),json={**context,'confirmed':True}).status_code==200
    assert f.client.post(candidate_base+'/publish',headers=headers(admin)).status_code==200
    assert f.client.post(candidate_base+f'/bind/{aid}',headers=headers(admin)).status_code==200
    delivered=f.client.get(f'/assignments/{aid}/download',headers=headers(f.reviewer))
    assert delivered.status_code==200 and hashlib.sha256(delivered.content).hexdigest()==info['prepared_sha256']
    rejected=f.client.post(f'/eic/manuscripts/{f.mid}/reviewer-candidates',headers=headers(admin),
        data={'review_round':1,'source_id':sid,'artifact_version':2,'fmt':'docx','metadata_preparation':'docx-v1'},
        files={'file':('synthetic.docx',word_document(),'application/octet-stream')})
    assert rejected.status_code==201
    rejected_base=f"/eic/manuscripts/{f.mid}/reviewer-candidates/{rejected.json()['candidate_id']}"
    assert f.client.post(rejected_base+'/reject',headers=headers(admin),json={'reason':'Synthetic identity remains'}).status_code==200
    assert f.client.get(rejected_base+'/content',headers=headers(f.reviewer)).status_code==403
    assert f.client.post(rejected_base+'/publish',headers=headers(admin)).status_code==409
    self_disable={**body,'action':'disable','request_id':'self-disable','expected_sequence':1,'expected_generation':1}
    assert f.client.post(f'/lifecycle-admin/eics/{admin.user_id}/actions',headers=headers(admin),json=self_disable).status_code==409
    with sqlite3.connect(f.db_path) as raw:
        raw.execute('PRAGMA ignore_check_constraints=ON')
        raw.execute('DROP TRIGGER lifecycle_events_no_update')
        raw.execute("UPDATE account_lifecycle_events SET occurred_at='2026-99-99T00:00:00.000000Z' WHERE user_id=? AND sequence=1",(target.user_id,))
        raw.execute(importlib.import_module('migrations.009_account_invitation_lifecycle').DDL['lifecycle_events_no_update'])
    assert f.client.get(f'/lifecycle-admin/eics/{target.user_id}/history',headers=headers(admin)).status_code==409
    body.update(action='disable',request_id='corrupt-history',expected_sequence=3,expected_generation=3)
    assert f.client.post(endpoint,headers=headers(admin),json=body).status_code==409
    with sqlite3.connect(f.db_path) as raw:
        for table in ('lifecycle_admin_bootstrap','lifecycle_eic_enrollments','lifecycle_administration_actions'):
            try:raw.execute('delete from '+table)
            except sqlite3.IntegrityError:raw.rollback()
            else:raise AssertionError('Immutable ledger accepted deletion')


def test_bootstrap_rejects_untrusted_signatures_and_ineligible_target(fixture):
    import copy
    import pytest
    f,chief,_,_,_,_,_=fixture;migration.migrate(f.db_path)
    owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate()
    key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    target=User(name='Synthetic Pending EIC',email='pending-sprint12@example.com',password_hash='x',role='eic');f.db.add(target);f.db.commit()
    valid=approval(f.db_path,target.user_id,target.email,owner,operator)
    cases=[]
    bad=copy.deepcopy(valid);bad['owner_signature']='00'*64;cases.append((bad,key,target.user_id))
    bad=copy.deepcopy(valid);bad['operator_signature']='00'*64;cases.append((bad,key,target.user_id))
    bad=copy.deepcopy(valid);bad['payload']['target_user_id']+=1;cases.append((bad,key,target.user_id))
    bad=copy.deepcopy(valid);bad['payload']['expires_at']=int(time.time())-1;cases.append((bad,key,target.user_id))
    cases.append((valid,Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw,PublicFormat.Raw),target.user_id))
    cases.append((approval(f.db_path,f.author.user_id,f.author.email,owner,operator),key,f.author.user_id))
    for bundle,trust,uid in cases:
        with sqlite3.connect(f.db_path) as raw:
            raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
            with pytest.raises(ValueError):reserved_bootstrap(raw,bundle,trust,f.db_path,uid,'SYNTHETIC-APPROVAL')
            raw.rollback()
    with sqlite3.connect(f.db_path) as raw:
        assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==0
        assert raw.execute('select count(*) from account_lifecycle where user_id=?',(target.user_id,)).fetchone()[0]==0


def test_offline_cli_checks_confirmation_and_executes_with_injected_synthetic_trust(fixture,monkeypatch):
    import sys
    import pytest
    cli=importlib.import_module('scripts.bootstrap_lifecycle_admin')
    f,chief,_,_,_,_,_=fixture
    admin=User(name='CLI Synthetic Admin',email='cli-sprint12@example.com',password_hash='x',role='eic');f.db.add(admin);f.db.commit()
    data_dir=f.root/'.test-data';data_dir.mkdir(mode=0o700)
    from database.bootstrap import initialize as initializer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    monkeypatch.setattr(initializer,'PROJECT',f.root)
    monkeypatch.setattr(initializer,'DATA',data_dir)
    path=initializer.initialize('collaboration.sqlite')
    engine=create_engine('sqlite:///'+str(path))
    with Session(engine) as session:
        session.add(User(user_id=admin.user_id,name='CLI Synthetic Admin',email=admin.email,password_hash='x',role='eic'))
        session.commit()
    engine.dispose()
    migration.migrate(path)
    owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate()
    key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    file=f.root/'signed-approval.json';file.write_text(json.dumps(approval(path,admin.user_id,admin.email,owner,operator)));file.chmod(0o600)
    real_trust=cli.trusted_owner_key
    monkeypatch.setattr(cli,'PROJECT_ROOT',f.root);monkeypatch.setattr(cli,'trusted_owner_key',lambda:key)
    monkeypatch.setenv('COLLABORATION_DATABASE',str(path))
    assert cli.collaboration_database(str(path)) == path
    with pytest.raises(ValueError):cli.collaboration_database(str(f.db_path))
    link=data_dir/'linked.sqlite';link.symlink_to(path)
    monkeypatch.setenv('COLLABORATION_DATABASE',str(link))
    with pytest.raises(ValueError):cli.collaboration_database(str(link))
    monkeypatch.setenv('COLLABORATION_DATABASE',str(path))
    path.chmod(0o644)
    with pytest.raises(ValueError):cli.collaboration_database(str(path))
    path.chmod(0o600)
    hardlink=data_dir/'hardlink.sqlite';os.link(path,hardlink)
    with pytest.raises(ValueError):cli.collaboration_database(str(path))
    hardlink.unlink()
    ledger=f.root/'cli-nonce-ledger';ledger.mkdir(mode=0o700)
    monkeypatch.setattr(cli,'open_trusted_ledger',lambda:os.open(ledger,os.O_RDONLY|os.O_DIRECTORY))
    monkeypatch.setattr(cli,'reserve_nonce',fixture_reserve)
    args=['bootstrap','--database',str(path),'--target-user-id',str(admin.user_id),'--confirm-user-id',str(admin.user_id),
          '--approval-reference','SYNTHETIC-APPROVAL','--confirm-approval-reference','SYNTHETIC-APPROVAL','--signed-approval',str(file),'--confirm-application-stopped']
    wrong=args.copy();wrong[wrong.index('--confirm-user-id')+1]=str(admin.user_id+1)
    monkeypatch.setattr(sys,'argv',wrong)
    assert cli.main()==1
    monkeypatch.setenv('COLLABORATION_DATABASE',str(f.db_path))
    monkeypatch.setattr(sys,'argv',args)
    assert cli.main()==1
    monkeypatch.setenv('COLLABORATION_DATABASE',str(path))
    with sqlite3.connect(path) as raw:assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==0
    monkeypatch.setattr(sys,'argv',args)
    assert cli.main()==0
    assert cli.main()==1
    with sqlite3.connect(path) as raw:assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==1
    fake=f.root/'untrusted.pub';fake.write_bytes(key);monkeypatch.setattr(cli,'OWNER_KEY',fake)
    with pytest.raises(ValueError):
        real_trust()


def test_concurrent_signed_bootstrap_has_exactly_one_winner(fixture):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    f,_,_,_,_,_,_=fixture;migration.migrate(f.db_path)
    target=User(name='Concurrent Synthetic Admin',email='concurrent-admin@example.com',password_hash='x',role='eic');f.db.add(target);f.db.commit()
    owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate()
    key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    signed=approval(f.db_path,target.user_id,target.email,owner,operator);barrier=threading.Barrier(2)
    (f.root/'synthetic-nonce-ledger').mkdir(mode=0o700)
    def attempt(_):
        barrier.wait()
        with sqlite3.connect(f.db_path,timeout=5) as raw:
            raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE')
            try:reserved_bootstrap(raw,signed,key,f.db_path,target.user_id,'SYNTHETIC-APPROVAL');raw.commit();return 'success'
            except (ValueError,FileExistsError):raw.rollback();return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(attempt,range(2)))
    assert sorted(outcomes)==['denied','success']
    with sqlite3.connect(f.db_path) as raw:assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==1
