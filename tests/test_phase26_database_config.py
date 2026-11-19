"""Validate database confinement in isolated subprocesses."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VALID = Path(os.environ['COLLABORATION_DATABASE'])


def run(value):
    env = os.environ.copy()
    if value is None: env.pop('COLLABORATION_DATABASE', None)
    else: env['COLLABORATION_DATABASE'] = str(value)
    code = "from app.database import engine; c=engine.connect(); print(c.exec_driver_sql('PRAGMA database_list').fetchone()[2]); print(c.exec_driver_sql('PRAGMA foreign_keys').scalar()); c.close()"
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)


def test_configured_database_and_foreign_keys():
    result = run(VALID)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [str(VALID), '1']


def test_missing_and_outside_configuration_are_rejected():
    assert run(VALID).returncode == 0
    assert run(None).returncode != 0
    assert run(ROOT / 'requirements.txt').returncode != 0
    assert run('relative.sqlite').returncode != 0


def test_symlink_database_rejected():
    from uuid import uuid4
    assert run(VALID).returncode == 0
    link = ROOT / '.test-data' / ('symlink-' + uuid4().hex + '.sqlite')
    link.symlink_to(VALID)
    assert run(link).returncode != 0


def test_non_collaboration_mode_rejected():
    assert run(VALID).returncode == 0
    env = os.environ.copy()
    env['COLLABORATION_DATABASE'] = str(VALID)
    env['MANUSCRIPT_MODE'] = 'staging'
    result = subprocess.run([sys.executable, '-c', 'import app.config'], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
