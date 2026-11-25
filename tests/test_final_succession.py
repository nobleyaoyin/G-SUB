"""Offline signed succession and emergency recovery with synthetic principals."""
import hashlib,importlib,json,os,sqlite3,time
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from app.models import User
from app.lifecycle_prototype import lifecycle_change
from app.lifecycle_succession import succeed,validate_approval,current_admin,SuccessionError
from test_batch38_eic_proof import fixture
from test_sprint12_lifecycle_admin import approval,reserved_bootstrap,fixture_reserve
from tests.test_lifecycle_prototype import principal,AUTHORITY

m39=importlib.import_module('migrations.039_lifecycle_administration');m40=importlib.import_module('migrations.040_lifecycle_succession')

def signed_succession(path,previous,prior,sequence,target,owner,operator,nonce):
 st=path.stat();now=int(time.time());op=operator.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
 with sqlite3.connect(path) as raw: state=raw.execute('SELECT state,sequence,auth_generation FROM account_lifecycle WHERE user_id=?',(target.user_id,)).fetchone()
 action='activate' if state is None else ('require_active' if state[0]=='active' else 'reactivate')
 p={'version':1,'purpose':'succession','database':str(path),'device':st.st_dev,'inode':st.st_ino,'previous_admin_user_id':previous,'previous_digest':prior,'sequence':sequence,'successor_user_id':target.user_id,'successor_email_sha256':hashlib.sha256(target.email.strip().lower().encode()).hexdigest(),'successor_lifecycle_action':action,'successor_expected_sequence':state[1] if state else 0,'successor_expected_generation':state[2] if state else 0,'operator_public_key':op.hex(),'approval_reference':'SYNTHETIC-SUCCESSION','issued_at':now,'expires_at':now+300,'nonce':nonce}
 message=json.dumps(p,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
 return {'payload':p,'owner_signature':owner.sign(b'GSUB-LIFECYCLE-SUCCESSION-OWNER-v1\0'+message).hex(),'operator_signature':operator.sign(b'GSUB-LIFECYCLE-SUCCESSION-OPERATOR-v1\0'+message).hex()}

def execute(raw,path,bundle,key):
 p,digest,_,op=validate_approval(bundle,key,now=int(time.time()),db_path=path)
 directory=path.parent/'synthetic-nonce-ledger';directory.mkdir(mode=0o700,exist_ok=True)
 fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
 try:reservation=fixture_reserve(fd,p['nonce'],digest,op)
 finally:os.close(fd)
 return succeed(raw,bundle,key,path,reservation=reservation)

def test_successor_and_emergency_recovery_are_owner_authorized(fixture):
 f,chief,headers,_,_,_,_=fixture;m39.migrate(f.db_path);m40.migrate(f.db_path);m40.migrate(f.db_path)
 actors=[User(name=f'Synthetic {i}',email=f'succession-{i}@example.com',password_hash='x',role='eic') for i in range(3)]
 f.db.add_all(actors);f.db.commit();admin,successor,recovery=actors
 owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate();key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate')
  reserved_bootstrap(raw,approval(f.db_path,admin.user_id,admin.email,owner,operator),key,f.db_path,admin.user_id,'SYNTHETIC-APPROVAL');raw.commit()
 def activate(actor,target,suffix):
  endpoint=f'/lifecycle-admin/eics/{target.user_id}/actions';body={'action':'enroll','request_id':'enroll-'+suffix,'reason':'Synthetic','expected_sequence':0,'expected_generation':0}
  assert f.client.post(endpoint,headers=headers(actor),json=body).status_code==200
  body.update(action='activate',request_id='activate-'+suffix)
  assert f.client.post(endpoint,headers=headers(actor),json=body).status_code==200
 activate(admin,successor,'one')
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');old,seq,digest=current_admin(raw);raw.rollback()
 signed=signed_succession(f.db_path,old,digest,seq+1,successor,owner,operator,'2'*64)
 bad={**signed,'owner_signature':'00'*64}
 with pytest.raises(SuccessionError):validate_approval(bad,key,now=int(time.time()),db_path=f.db_path)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');result=execute(raw,f.db_path,signed,key);raw.commit()
 assert result['admin_user_id']==successor.user_id
 assert f.client.get('/lifecycle-admin/eics',headers=headers(admin)).status_code==403
 assert f.client.get('/lifecycle-admin/eics',headers=headers(successor)).status_code==200
 # A newly signed approval based on the old chain head is still stale.
 stale=signed_succession(f.db_path,old,digest,seq+1,successor,owner,operator,'4'*64)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate')
  with pytest.raises(SuccessionError):execute(raw,f.db_path,stale,key)
  raw.rollback()
 # A non-EIC cannot become administrator even with a valid owner signature.
 wrong=signed_succession(f.db_path,successor.user_id,result['event_digest'],2,f.reviewer,owner,operator,'5'*64)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate')
  with pytest.raises(SuccessionError):execute(raw,f.db_path,wrong,key)
  raw.rollback()
 activate(successor,recovery,'two')
 assert len(f.client.get('/lifecycle-admin/successions',headers=headers(successor)).json())==1
 # Synthetic prototype action models an unavailable current administrator; no production policy is inferred.
 with sqlite3.connect(f.db_path,timeout=.2) as raw:
  raw.execute('pragma foreign_keys=ON');lifecycle_change(raw,principal(chief.user_id),successor.user_id,'disable',authority=AUTHORITY,expected_sequence=1,expected_generation=1)
 assert f.client.get('/lifecycle-admin/eics',headers=headers(successor)).status_code==403
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');old,seq,digest=current_admin(raw);raw.rollback()
 emergency=signed_succession(f.db_path,old,digest,seq+1,recovery,owner,operator,'3'*64)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');result=execute(raw,f.db_path,emergency,key);raw.commit()
 assert result['admin_user_id']==recovery.user_id
 assert f.client.get('/lifecycle-admin/eics',headers=headers(recovery)).status_code==200
 with sqlite3.connect(f.db_path) as raw:
  assert raw.execute('select count(*) from lifecycle_admin_bootstrap').fetchone()[0]==1
  assert raw.execute('select count(*) from lifecycle_admin_successions').fetchone()[0]==2
  with pytest.raises(sqlite3.IntegrityError):raw.execute('delete from lifecycle_admin_successions')
  raw.rollback()
 # Simulate a privileged history edit, restore the trigger, and fail closed.
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('DROP TRIGGER lifecycle_admin_successions_no_update')
  raw.execute("UPDATE lifecycle_admin_successions SET event_digest=? WHERE sequence=1",('0'*64,))
  raw.execute(m40.DDL['lifecycle_admin_successions_no_update'])
 assert f.client.get('/lifecycle-admin/eics',headers=headers(recovery)).status_code==403


def test_succession_cli_with_synthetic_trust_and_exact_confirmations(fixture,monkeypatch):
 import sys
 cli=importlib.import_module('scripts.succeed_lifecycle_admin')
 f,chief,headers,_,_,_,_=fixture;m39.migrate(f.db_path);m40.migrate(f.db_path)
 admin=User(name='CLI Synthetic Admin',email='cli-succ-admin@example.com',password_hash='x',role='eic')
 target=User(name='CLI Synthetic Successor',email='cli-succ-target@example.com',password_hash='x',role='eic')
 f.db.add_all([admin,target]);f.db.commit()
 owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate();key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');reserved_bootstrap(raw,approval(f.db_path,admin.user_id,admin.email,owner,operator),key,f.db_path,admin.user_id,'SYNTHETIC-APPROVAL');raw.commit()
 with sqlite3.connect(f.db_path,timeout=.2) as raw:
  raw.execute('pragma foreign_keys=ON');lifecycle_change(raw,principal(chief.user_id),target.user_id,'enroll',authority=AUTHORITY,expected_sequence=0,expected_generation=0)
 data_dir=f.root/'.test-data';data_dir.mkdir(mode=0o700)
 path=data_dir/'collaboration.sqlite'
 with sqlite3.connect(f.db_path) as src,sqlite3.connect(path) as dst:src.backup(dst)
 path.chmod(0o600)
 with sqlite3.connect(path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');prev,seq,digest=current_admin(raw);raw.rollback()
 bundle=signed_succession(path,prev,digest,seq+1,target,owner,operator,'9'*64)
 approval_file=f.root/'succession.json';approval_file.write_text(json.dumps(bundle));approval_file.chmod(0o600)
 ledger=f.root/'succession-cli-ledger';ledger.mkdir(mode=0o700)
 monkeypatch.setattr(cli,'ROOT',f.root);monkeypatch.setattr(cli,'trusted_owner_key',lambda:key)
 monkeypatch.setenv('COLLABORATION_DATABASE',str(path))
 monkeypatch.setattr(cli,'open_trusted_ledger',lambda:os.open(ledger,os.O_RDONLY|os.O_DIRECTORY));monkeypatch.setattr(cli,'reserve_nonce',fixture_reserve)
 args=['succession','--database',str(path),'--current-admin-id',str(admin.user_id),'--successor-id',str(target.user_id),'--confirm-successor-id',str(target.user_id),
       '--approval-reference','SYNTHETIC-SUCCESSION','--confirm-approval-reference','SYNTHETIC-SUCCESSION','--signed-approval',str(approval_file),'--confirm-application-stopped']
 wrong=args.copy();wrong[wrong.index('--confirm-successor-id')+1]=str(target.user_id+1)
 monkeypatch.setattr(sys,'argv',wrong);assert cli.main()==1
 monkeypatch.setattr(sys,'argv',args);assert cli.main()==0;assert cli.main()==1
 with sqlite3.connect(path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');assert current_admin(raw)[0]==target.user_id;raw.rollback()


def test_owner_recovery_enrolls_inactive_successor_and_reports_offline_actor(fixture):
 f,chief,headers,_,_,_,_=fixture;m39.migrate(f.db_path);m40.migrate(f.db_path)
 admin=User(name='Synthetic unavailable admin',email='recovery-admin@example.com',password_hash='x',role='eic')
 target=User(name='Synthetic recovery successor',email='recovery-target@example.com',password_hash='x',role='eic')
 f.db.add_all([admin,target]);f.db.commit()
 owner=Ed25519PrivateKey.generate();operator=Ed25519PrivateKey.generate();key=owner.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');reserved_bootstrap(raw,approval(f.db_path,admin.user_id,admin.email,owner,operator),key,f.db_path,admin.user_id,'SYNTHETIC-APPROVAL');raw.commit()
 with sqlite3.connect(f.db_path,timeout=.2) as raw:
  raw.execute('pragma foreign_keys=ON');lifecycle_change(raw,principal(chief.user_id),admin.user_id,'disable',authority=AUTHORITY,expected_sequence=1,expected_generation=1)
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');previous,seq,digest=current_admin(raw);raw.rollback()
 bundle=signed_succession(f.db_path,previous,digest,seq+1,target,owner,operator,'8'*64)
 assert bundle['payload']['successor_lifecycle_action']=='activate'
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');execute(raw,f.db_path,bundle,key);raw.commit()
 response=f.client.get(f'/lifecycle-admin/eics/{target.user_id}/history',headers=headers(target))
 assert response.status_code==200
 event=response.json()['events'][0]
 assert event['actor_kind']=='offline_operator' and event['actor_user_id'] is None
 assert event['bootstrap_approval_reference']=='SYNTHETIC-SUCCESSION'
 with sqlite3.connect(f.db_path,timeout=.2) as raw:
  from app.lifecycle_prototype import lifecycle_read
  raw.execute('pragma foreign_keys=ON')
  history=lifecycle_read(raw,principal(chief.user_id),target.user_id,authority=AUTHORITY,history=True)
  assert history[0][4]['kind']=='offline_operator'
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');previous,seq,digest=current_admin(raw);raw.rollback()
 restore=signed_succession(f.db_path,previous,digest,seq+1,admin,owner,operator,'6'*64)
 assert restore['payload']['successor_lifecycle_action']=='reactivate'
 with sqlite3.connect(f.db_path) as raw:
  raw.execute('pragma foreign_keys=ON');raw.execute('begin immediate');execute(raw,f.db_path,restore,key);raw.commit()
 fresh={'Authorization':'Bearer '+__import__('app.security',fromlist=['create_access_token']).create_access_token(admin.user_id,lifecycle_generation=3)}
 response=f.client.get(f'/lifecycle-admin/eics/{admin.user_id}/history',headers=fresh)
 assert response.status_code==200 and response.json()['events'][-1]['actor_kind']=='offline_operator'
 assert response.json()['events'][-1]['actor_user_id'] is None
