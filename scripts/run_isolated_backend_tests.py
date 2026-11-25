#!/usr/bin/env python3
"""Run the shared backend regression slice without accessing project data.

Install requirements-dev.txt in a disposable development environment, then run
this script with that environment's Python. --pytest-path permits an explicit
local, disposable pytest package directory; it never installs dependencies.
"""
import argparse
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
TESTS = (
    'test_isolated_backend_smoke.py', 'test_reviewer_download.py',
    'test_reviewer_invitations.py', 'test_two_reviewer_policy.py',
    'test_author_agreement.py', 'test_final_workflow.py', 'test_formatting.py',
    'test_online_text_editor.py', 'test_online_version_ledger.py',
    'test_workflow_notifications_demo.py', 'test_email_domain_compatibility.py',
    'test_secure_word_uploads.py', 'test_initial_editing_progress_api.py',
    'test_initial_editing.py', 'test_eic_dashboard.py', 'test_demo_backend_boundaries.py',
    'test_isolated_runner_safety.py', 'test_demo_security.py', 'test_initializer_schema_contract.py',
    'test_onlyoffice_gsub_integration.py',
)


def reject_symlinks(directory):
    for root, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            if (Path(root) / name).is_symlink():
                raise RuntimeError(f'Refusing symlink in test source: {Path(root) / name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pytest-path', type=Path, help='Explicit local pytest package directory')
    args = parser.parse_args()
    runner = args.pytest_path.resolve(strict=True) if args.pytest_path else None
    if runner and not (runner / 'pytest' / '__init__.py').is_file():
        parser.error('--pytest-path must contain a pytest package')
    for name in TESTS:
        if not (PROJECT / 'tests' / name).is_file():
            raise RuntimeError(f'Missing selected test: {name}')
    with tempfile.TemporaryDirectory(prefix='gsub-backend-regression-') as temporary:
        root = Path(temporary).resolve()
        for folder in ('app', 'migrations'):
            source = PROJECT / folder
            reject_symlinks(source)
            shutil.copytree(source, root / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '.env*', '*.before*'))
        (root / 'tests').mkdir()
        for name in TESTS:
            source = PROJECT / 'tests' / name
            if source.is_symlink(): raise RuntimeError(f'Refusing symlink: {source}')
            shutil.copy2(source, root / 'tests' / name)
        probe = PROJECT / 'tests' / 'demo_security_probe.py'
        document_fixture = PROJECT / 'tests' / 'academic_docx_fixture.py'
        initializer = PROJECT / 'scripts' / 'init_demo.py'
        if any(p.is_symlink() or not p.is_file() for p in (probe, document_fixture, initializer)):
            raise RuntimeError('Missing or unsafe initializer test sources')
        shutil.copy2(probe, root / 'tests' / probe.name)
        shutil.copy2(document_fixture, root / 'tests' / document_fixture.name)
        (root / 'scripts').mkdir()
        shutil.copy2(Path(__file__).resolve(), root / 'scripts' / Path(__file__).name)
        shutil.copy2(initializer, root / 'scripts' / initializer.name)
        # The existing initializer tests invoke PROJECT/.venv/bin/python.
        # This private wrapper delegates to the chosen interpreter without
        # exposing a project environment or credentials to the test copy.
        (root / '.venv' / 'bin').mkdir(parents=True)
        wrapper = root / '.venv' / 'bin' / 'python'
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        wrapper.chmod(0o700)
        (root / 'frontend' / 'dist').mkdir(parents=True)
        (root / 'frontend' / 'dist' / 'index.html').write_text('<!doctype html><title>Synthetic test</title>')
        paths = ([str(runner)] if runner else []) + [str(root), str(root / 'tests')]
        env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': os.pathsep.join(paths),
               'PYTHON_DOTENV_DISABLED':'1', 'PYTHONDONTWRITEBYTECODE':'1',
               'PYTHONNOUSERSITE':'1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1',
               'SECRET_KEY':secrets.token_hex(32), 'MANUSCRIPT_MODE':'development',
               'GSUB_CAPTCHA_MODE':'off', 'GSUB_ONLYOFFICE_ENABLED':'0'}
        if os.environ.get('TMPDIR'): env['TMPDIR'] = os.environ['TMPDIR']
        print('Running isolated backend regression slice in a disposable project copy.', flush=True)
        return subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', *[f'tests/{n}' for n in TESTS]], cwd=root, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
