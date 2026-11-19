# G-SUB Manuscript Submission System

G-SUB is a manuscript submission and peer-review management application for academic editorial workflows. It provides role-specific workspaces for authors, editors, reviewers, and an Editor-in-Chief (EIC), with formatting work available through the existing editor/formatter account model.

> **Development status:** This is a collaboration baseline, not a production release. Some workflows are partial. In particular, EIC prospective approval-proof issuance and valid-proof Double Blind document release are not complete.

## Project overview

The application follows a manuscript from author submission through editorial screening, initial editing, peer review, an EIC decision, author agreement, final editing, formatting, and a local publication state. Revision and rejection paths are supported where the relevant workflow handlers permit them. Available actions depend on the user's role, assignment, manuscript state, and existing records.

### Feature summary

- Author drafts, independent title and abstract editing, manuscript uploads, submission, revisions, and version history.
- EIC screening, editor invitations, review coordination, editorial decisions, stage navigation, and manuscript history.
- Initial and final editing workflows with assignment-specific document access.
- Reviewer invitations, review-round assignments, comments and recommendations, and supported reviewed-document uploads.
- Manual, version-bound document distribution and revocation for eligible editor assignments.
- Formatting assignments, in-app notifications, progress views, personal notes, and staff general comments where authorized.

These features are implemented to different levels of completeness; a listed capability does not imply that every role or workflow has passed end-to-end acceptance.

## User roles and workflows

| Role | Responsibilities and access |
| --- | --- |
| Author | Creates and submits manuscripts, manages permitted versions and revisions, and responds to applicable editorial requests. |
| EIC | Screens manuscripts, coordinates assignments and review, makes editorial decisions, and manages authorized document distribution. |
| General / Copy Editor | Works on assigned initial or final editing tasks and permitted manuscript documents. |
| Reviewer | Responds to assigned review work and submits permitted comments, recommendations, or a reviewed document. |
| Formatter | Performs assigned formatting work through the existing editor/formatter workspace model. |

The sign-in chooser groups Formatter with General / Copy Editor. This presentation does not change stored roles or grant permissions. Self-registration currently creates author accounts; other role provisioning requires an existing administrative or development process.

## Technology stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.12.13 (verified environment), FastAPI, Pydantic, SQLAlchemy, Uvicorn, PyJWT, and Argon2-based password hashing. Exact dependencies are in `requirements.txt`. |
| Frontend | React 19, Vite, Vitest, and Testing Library. Exact dependency resolution is recorded in `frontend/package-lock.json`. |
| Database and files | SQLite with foreign-key enforcement; manuscript files and artifact storage on the local filesystem. |
| Tests | pytest for backend tests; Vitest and Testing Library for frontend tests. |

## System architecture

The Vite/React frontend calls the FastAPI backend through `/api` during local development. The Vite development proxy forwards requests to the backend at `http://127.0.0.1:8000` by default. The backend applies authentication, role, manuscript, assignment, and workflow checks before accessing SQLite records or documents. SQLite stores workflow and file-reference records; file bytes are stored separately.

```text
Browser → React / Vite → FastAPI routers → SQLAlchemy / SQLite
                                      └→ local document storage
```

The repository also contains migration scripts and a collaboration-only database bootstrap. Email services exist, but a notification, an access grant, an enqueued email, and an actual delivery are different events.

## Project directory structure

```text
.
├── app/                         # FastAPI application, services, models, and routers
├── database/bootstrap/          # Collaboration Base Schema v1 and initializer
├── frontend/                    # React application, Vite configuration, and lockfile
├── migrations/                  # Numbered SQLite migration scripts
├── reports/                     # Requirements tracker and project records
├── tests/                       # Backend and integration tests
├── COLLABORATION_SETUP.md       # Collaboration setup and workflow
├── requirements.txt             # Backend dependencies
└── requirements-dev.txt         # Backend test dependency
```

## Prerequisites

- Python **3.12.13**, the verified backend environment.
- Node.js compatible with the installed Vite version: **20.19+ within Node 20, or 22.12+**. Node 25.8.1 was used in the verified environment.
- npm, Git, and a Unix-like shell for the commands below. The current database path checks and file-storage safeguards use Unix filesystem features.
- Access to the private collaboration repository.

## Installation

Clone the repository and create independent local dependency environments:

```sh
git clone https://github.com/nobleyaoyin/manuscript-submission-system-main.git
cd manuscript-submission-system-main

python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt -r requirements-dev.txt

cd frontend
npm ci
cd ..
```

## Environment configuration

The backend requires two environment variables:

| Variable | Purpose |
| --- | --- |
| `COLLABORATION_DATABASE` | Absolute path to an existing, private SQLite file directly inside this workspace's `.test-data` directory. |
| `SECRET_KEY` | Private signing key for authentication tokens. Generate a unique value for each development environment. |

`.env.example` describes the variables with placeholders. Do not use its placeholder signing key. The following generates a temporary shell key without printing it:

```sh
export SECRET_KEY="$(.venv312/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
```

A new key invalidates tokens created with an earlier key. If local login sessions must survive restarts, store a separately generated key securely in an ignored local environment file. Never commit credentials or copy another developer's key.

## Database initialization

**Collaboration Base Schema v1 is a newly established collaboration baseline; it is not a reconstruction of a historical pre-001 production schema.** The initializer applies the baseline and migrations 001–019 and 021 to a new disposable SQLite file. There is no migration 020.

Create an independent local database from the repository root:

```sh
mkdir -p .test-data
.venv312/bin/python -m database.bootstrap.initialize --name local.sqlite
export COLLABORATION_DATABASE="$PWD/.test-data/local.sqlite"
```

The initializer requires an owner-controlled, non-symlink `.test-data` directory and refuses an existing filename. If initialization fails, it retains the partial file for inspection; choose a new filename for a subsequent attempt. Each migration has its own transaction. Never point the application or migrations at an original Main or production database. See [database/bootstrap/README.md](database/bootstrap/README.md) for schema ownership and limitations.

## Backend startup

With `SECRET_KEY` and `COLLABORATION_DATABASE` set in the same shell:

```sh
.venv312/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The health endpoint is available at `http://127.0.0.1:8000/health`. In development mode, FastAPI's interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Frontend startup

In a second terminal, from the repository root:

```sh
cd frontend
npm run dev
```

Open the local URL printed by Vite. Set `VITE_API_PROXY_TARGET` if the backend is running at a different local address.

## Testing instructions

Use synthetic accounts and files only. Ensure the environment variables above point to your **independent local** database, and choose a new pytest base directory for each run:

```sh
mkdir -p .test-data/tmp
export TMPDIR="$PWD/.test-data/tmp"
PYTHONDONTWRITEBYTECODE=1 .venv312/bin/python -m pytest -p no:cacheprovider \
  --basetemp "$PWD/.test-data/pytest-local" \
  tests/test_phase26_backend_integration.py \
  tests/test_main_reviewer_authority.py \
  tests/test_main_reviewer_dependencies.py \
  tests/test_collaboration_initializer.py \
  tests/test_collaboration_base_v1.py -q

cd frontend
npx vitest run
npm run build
```

Replace `pytest-local` with an unused name on subsequent runs: pytest may remove an existing base directory. Tests and browser workflows must not use real manuscripts, persistent Main data, or real email delivery. The published test set does not include all local development fixtures.

## Security and privacy

- The backend enforces role-based and manuscript-level access checks; frontend visibility alone is not authorization.
- Reviewer document access checks the authenticated reviewer, assignment, invitation, review round, policy, and applicable invalidation state.
- Private artifact storage uses bounded reads and integrity checks; document access must still be authorized by the relevant backend endpoint.
- Double Blind reviewer downloads **fail closed** when valid EIC approval proof is unavailable. They do not fall back to original manuscript bytes.
- Manual distribution grants, notifications, email delivery, and downloads are separate states; an access grant is not proof of delivery.
- Keep local databases, uploads, `.env` files, keys, and credentials out of Git. Use only synthetic documents in development and tests.

These controls do not replace independent security review before deployment.

## Current limitations

| Status | Limitation |
| --- | --- |
| **Incomplete** | The prospective EIC approval-proof issuer and complete valid-proof Double Blind release workflow are not yet connected. |
| **Partially implemented** | Single Blind downloads require an active, assigned, accepted, current-round reviewer. Historical or completed assignments that do not meet those checks are denied and need policy review. |
| **Prototype** | The author-agreement text is a placeholder and is not approved legal terms. Publication is recorded locally as a prototype; an external DOI or journal publication is not established. |
| **Limited** | Email and document distribution have distinct status and authorization rules; automatic distribution is not enabled as a general release policy. |
| **Development** | The collaboration bootstrap and overall application require further integration and security review before production use. |

## Roadmap

The [47-item requirements tracker](reports/PROJECT_47_REQUIREMENTS_MASTER_TRACKER.md) records implementation progress. Near-term work includes the EIC proof lifecycle, reviewer document privacy and authorization, historical assignment handling, and remaining workflow and acceptance-test gaps. Treat tracker statuses as development evidence, not user acceptance.

## Team collaboration

1. Keep `main` stable and create a feature branch, such as `feature/reviewer-proof` or `fix/document-access`.
2. Make focused commits with clear messages, for example `feat: add reviewer proof validation` or `fix: restrict document access`.
3. Run the tests relevant to the change, plus the frontend build when applicable; record actual results and unresolved failures.
4. Open a pull request against `main`, describe the behavior and security impact, and request review before merging.
5. Do not commit local secrets, databases, uploads, or private manuscripts.

Additional setup details are in [COLLABORATION_SETUP.md](COLLABORATION_SETUP.md).

## License and third-party notices

No project license file is currently included in this repository. Ask the repository owner about permissions before redistributing project source. Third-party packages retain their respective licenses; consult the dependency manifests, lockfile, and installed package notices. A complete legal or third-party attribution review has not been completed.
