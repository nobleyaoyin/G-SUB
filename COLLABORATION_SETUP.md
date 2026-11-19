# G-SUB collaboration setup

The intended private repository is `nobleyaoyin/manuscript-submission-system-main`. Its availability must be verified before using the following command:

```sh
git clone https://github.com/nobleyaoyin/manuscript-submission-system-main.git
cd manuscript-submission-system-main
```

Use Python 3.12.13 and a current Node version compatible with the lockfile. Create a fresh environment and install the declared dependencies:

```sh
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt -r requirements-dev.txt
cd frontend
npm ci
cd ..
```

For isolated local development, create a fresh database. The initializer requires an owner-controlled, non-symlink `.test-data` directory and refuses to overwrite an existing file:

```sh
mkdir -p .test-data
.venv312/bin/python -m database.bootstrap.initialize --name local.sqlite
export COLLABORATION_DATABASE="$PWD/.test-data/local.sqlite"
export SECRET_KEY="$(.venv312/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv312/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use a unique persistent local signing key if login sessions must survive restarts. Never commit or share it. Start the frontend in another terminal with `cd frontend && npm run dev`. Never point this workspace at another environment's database or uploads. Keep external email delivery disabled unless explicitly authorized.

Run focused tests with isolated temporary data, and the frontend checks:

```sh
mkdir -p .test-data/tmp
export TMPDIR="$PWD/.test-data/tmp"
PYTHONDONTWRITEBYTECODE=1 .venv312/bin/python -m pytest -p no:cacheprovider --basetemp "$PWD/.test-data/pytest-local" tests/test_phase26_backend_integration.py tests/test_main_reviewer_authority.py tests/test_main_reviewer_dependencies.py tests/test_collaboration_initializer.py tests/test_collaboration_base_v1.py -q
cd frontend
npx vitest run
npm run build
```

Use a new `--basetemp` path on subsequent runs to avoid overwriting existing test artifacts. Create a feature branch for each change, commit focused work, and open a pull request for review. Never commit credentials, databases, uploads or private manuscripts.

The EIC prospective proof workflow is incomplete. Double Blind reviewer downloads deny access when valid proof is unavailable and never fall back to original bytes. Collaboration Base Schema v1 is newly approved and does not claim to reproduce historical production schema. See `database/bootstrap/README.md` for its limitations.
