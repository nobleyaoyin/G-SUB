# Isolated local Demo

> **Historical, unsupported instructions:** This repository supports
> Collaboration Development only. Its configuration rejects Demo mode. The
> launcher and workflow described below are retained as historical Main/Stable
> Demo material and are not supported or validated by this release.
> The commands below are historical reference only; do not use them to start or
> initialize a Demo in this Collaboration Development repository.

The Demo uses a new synthetic SQLite database and upload directory, with separate generated accounts and signing key. It does not need the Development database or uploads. The gateway listens on localhost only; registration, API documentation and real email delivery are disabled in Demo mode. Do not start a public tunnel or expose the application without separate explicit approval.

Author uploads support PDF, DOCX, DOC and UTF-8 TXT up to 10 MiB. Initial editing and the confirmed first review-round file support these same formats. Final editing accepts PDF, DOCX, DOC or UTF-8 TXT source documents; formatter proof uploads and local prototype publication remain PDF-only.

Run these commands from the repository root after installing the dependencies in [README](../README.md). Build the React frontend first:

```bash
cd frontend
npm ci
npm run build
cd ..
```

## Historical reference: official Demo launcher

The official Demo is `../Manuscript-Stable-Demo/.demo_data`. From the Main project root run:

```bash
.venv/bin/python scripts/run_official_demo.py
```

This launcher selects that fixed data root and the Stable Demo's own runtime. The gateway enables Demo mode and binds to `127.0.0.1:8765`. It fails if the designated data or runtime is missing; it does not create or initialize a database. The old project-local Demo roots in Main and `Manuscript-Upgrade-Test` are retired, retained in place and backed up. Synthetic test roots remain supported by `run_demo.py`.

Check the printed database and upload paths, then visit `http://127.0.0.1:8765`. The gateway serves the built frontend and `/api` on the same origin. The EIC and Formatter dashboards are available through their respective role-selection cards. Log in using the locally generated Demo account for the desired role.

After sign-in, use the shared sidebar to return to the dashboard, access available manuscript and notification sections, or log out. The Author dashboard lists manuscripts before its workflow panels.

Stop the gateway with Ctrl-C. Restart it with the **same** data-root path to retain committed Demo records. Do not rerun initialization, delete the directory, regenerate keys or migrate it without specific authorization. If records appear missing, first verify the selected root, API origin and signed-in account; do not reset data. Login is rate-limited in memory per process and connecting address. This local limiter is not a public access gate.

If a public meeting setup is requested later, obtain separate approval and complete a security review before any tunnel or external exposure. This guide does not authorize or start one.

## Local ONLYOFFICE integration

When the official Stable Demo has a private, mode-0600 `.onlyoffice-stable.env`, the official launcher reads its explicitly supported settings without printing credentials. The ONLYOFFICE service must already be running locally with the matching JWT secret. The launcher uses the official gateway's container-reachable backend URL `http://host.docker.internal:8765/api`; the browser editor service origin remains separately configured in that private file. If the file is absent, editing remains disabled unless settings are provided in the process environment. Do not start a public tunnel, expose credentials, or initialize a Demo database to troubleshoot the editor.

A save creates a document version. Test editing and callbacks with a disposable synthetic fixture; obtain approval before creating test versions in the existing Demo. A successful local synthetic test does not by itself verify every existing document or role.
