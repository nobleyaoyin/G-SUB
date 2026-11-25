"""Rehearsal operator checks; databases and journals are disposable."""
import getpass, hashlib, importlib.util, json, os, sqlite3, subprocess, sys, tempfile
from pathlib import Path
import pytest
from test_batch38_eic_proof import fixture
from test_batch40_reviewer_candidates import ready

spec=importlib.util.spec_from_file_location('operator038',Path(__file__).resolve().parents[1]/'scripts/rehearse_migration_038.py')
operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)

@pytest.fixture
def rehearsal(fixture):
    f, *_ = ready(fixture)
    with tempfile.TemporaryDirectory(prefix='gsub-sprint10-',dir='/private/tmp') as dirname:
        root=Path(dirname).resolve(); os.chmod(root,0o700)
        target=root/'target.sqlite';backup=root/'backup.sqlite';manifest=root/'manifest.json'
        with sqlite3.connect(f.db_path) as source:
            for path in (target,backup):
                with sqlite3.connect(path) as db:source.backup(db)
                os.chmod(path,0o600)
        snapshot=operator._snapshot(target)
        manifest.write_text(json.dumps({'schema_sha256':snapshot['schema_sha256'],'migration_ids':[r[0] for r in snapshot['migrations']]}));os.chmod(manifest,0o600)
        yield {'workspace':str(root),'target':str(target),'backup':str(backup),'manifest':str(manifest),
               'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'operator':getpass.getuser(),
               'confirm_target':str(target),'application_stopped':True}


def test_success_audit_and_duplicate_refusal(rehearsal):
    assert operator.rehearse(**rehearsal)=='verified'
    target=Path(rehearsal['target'])
    with sqlite3.connect(target) as db:
        assert db.execute("select count(*) from schema_migrations where migration_id='038_candidate_preparation_provenance'").fetchone()[0]==1
        assert not db.execute('pragma foreign_key_check').fetchall()
    records=[json.loads(x) for x in (target.parent/'migration-038-audit.jsonl').read_text().splitlines()]
    assert [r['event'] for r in records]==['attempt','preflight_passed','verified']
    with pytest.raises(ValueError): operator.rehearse(**rehearsal)
    assert json.loads((target.parent/'migration-038-audit.jsonl').read_text().splitlines()[-1])['event']=='failed_or_unknown'


@pytest.mark.parametrize('field,value', [('operator','different-operator'),('backup_sha256','0'*64),('confirm_target','/wrong'),('application_stopped',False)])
def test_preflight_rejects_bad_operator_or_confirmation(rehearsal,field,value):
    with pytest.raises(ValueError):operator.rehearse(**{**rehearsal,field:value})
    with sqlite3.connect(rehearsal['target']) as db:
        assert not db.execute("select 1 from schema_migrations where migration_id='038_candidate_preparation_provenance'").fetchone()


def test_schema_history_and_backup_mismatch(rehearsal):
    manifest=Path(rehearsal['manifest']); plan=json.loads(manifest.read_text()); plan['migration_ids']=[];manifest.write_text(json.dumps(plan))
    with pytest.raises(ValueError,match='Unexpected target schema or migration history'):operator.rehearse(**rehearsal)
    plan['migration_ids']=[r[0] for r in operator._snapshot(Path(rehearsal['target']))['migrations']];plan['schema_sha256']='0'*64;manifest.write_text(json.dumps(plan))
    with pytest.raises(ValueError,match='Unexpected target schema or migration history'):operator.rehearse(**rehearsal)
    plan['schema_sha256']=operator._snapshot(Path(rehearsal['target']))['schema_sha256'];manifest.write_text(json.dumps(plan))
    with sqlite3.connect(rehearsal['target']) as db:db.execute('create table synthetic_unexpected(x)')
    with pytest.raises(ValueError,match='Backup does not represent'):operator.rehearse(**rehearsal)


def test_rejects_outside_workspace_and_symlinks(rehearsal):
    main_path=str(operator.PROJECT_ROOT/'manuscript.db')
    with pytest.raises(ValueError):operator.rehearse(**{**rehearsal,'target':main_path,'confirm_target':main_path})
    link=Path(rehearsal['workspace'])/'link.sqlite';link.symlink_to(rehearsal['target'])
    with pytest.raises(ValueError):operator.rehearse(**{**rehearsal,'target':str(link),'confirm_target':str(link)})


def test_missing_prerequisite_refused(rehearsal):
    for name in ('target','backup'):
        with sqlite3.connect(rehearsal[name]) as db:db.execute("delete from schema_migrations where migration_id='024_reviewer_publication_audit'")
    snap=operator._snapshot(Path(rehearsal['target']))
    Path(rehearsal['manifest']).write_text(json.dumps({'schema_sha256':snap['schema_sha256'],'migration_ids':[r[0] for r in snap['migrations']]}))
    rehearsal['backup_sha256']=hashlib.sha256(Path(rehearsal['backup']).read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='Missing prerequisite'):operator.rehearse(**rehearsal)


def test_real_cli_runs_with_required_explicit_arguments(rehearsal):
    script=Path(__file__).resolve().parents[1]/'scripts/rehearse_migration_038.py'
    command=[sys.executable,str(script),'--workspace',rehearsal['workspace'],'--target',rehearsal['target'],
             '--backup',rehearsal['backup'],'--manifest',rehearsal['manifest'],'--backup-sha256',rehearsal['backup_sha256'],
             '--operator',rehearsal['operator'],'--confirm-target',rehearsal['target'],'--confirm-application-stopped']
    result=subprocess.run(command,capture_output=True,text=True,timeout=20)
    assert result.returncode==0, result.stderr
    assert result.stdout.strip()=='verified'


def test_rejects_restricted_environment_path_without_opening_it(rehearsal):
    forbidden=str(Path(rehearsal['workspace'])/'demo.sqlite')
    with pytest.raises(ValueError,match='Restricted environment'):
        operator.rehearse(**{**rehearsal,'target':forbidden,'confirm_target':forbidden})
