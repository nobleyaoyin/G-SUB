"""Safety checks for the retired project-local Demo entry point."""
import subprocess
import sys
from pathlib import Path


def test_main_retired_demo_root_fails_closed():
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, '-B', str(project / 'scripts' / 'run_demo.py'),
         '--data-root', str(project / '.demo_data')],
        cwd=project, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert 'retired' in result.stderr


def test_official_launcher_routes_onlyoffice_via_gateway(tmp_path):
    project = tmp_path / 'Project 2'
    scripts = project / 'scripts'
    scripts.mkdir(parents=True)
    original = Path(__file__).resolve().parents[1] / 'scripts' / 'run_official_demo.py'
    launcher = scripts / original.name
    launcher.write_bytes(original.read_bytes())
    stable = tmp_path / 'Manuscript-Stable-Demo'
    root = stable / '.demo_data'
    (root / 'uploads').mkdir(parents=True)
    for name in ('accounts.json', 'manuscript.db', 'jwt.key'):
        (root / name).write_text('synthetic')
    (stable / 'frontend' / 'dist').mkdir(parents=True)
    (stable / 'frontend' / 'dist' / 'index.html').write_text('synthetic')
    (stable / 'scripts').mkdir()
    (stable / 'scripts' / 'run_demo.py').write_text('synthetic')
    runtime = stable / '.venv' / 'bin' / 'python'
    runtime.parent.mkdir(parents=True)
    runtime.write_text('#!/bin/sh\nprintf "%s\\n" "$GSUB_ONLYOFFICE_APP_ORIGIN"\n')
    runtime.chmod(0o700)
    settings = stable / '.onlyoffice-stable.env'
    settings.write_text('GSUB_ONLYOFFICE_ENABLED=1\nGSUB_ONLYOFFICE_APP_ORIGIN=http://host.docker.internal:8000\nGSUB_ONLYOFFICE_SECRET=synthetic-secret-not-real\nGSUB_ONLYOFFICE_SERVER_ORIGIN=http://127.0.0.1:8080\n')
    settings.chmod(0o600)
    result = subprocess.run([sys.executable, '-B', str(launcher)], env={'PATH': '/usr/bin:/bin'},
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'http://host.docker.internal:8765/api'
    settings.chmod(0o644)
    result = subprocess.run([sys.executable, '-B', str(launcher)], env={'PATH': '/usr/bin:/bin'},
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert 'private' in result.stderr
