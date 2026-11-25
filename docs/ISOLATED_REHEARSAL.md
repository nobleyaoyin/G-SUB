# Disposable G-SUB rehearsal

This local-only synthetic rehearsal is separate from the existing Demo and all other application data. It creates an empty private temporary root, initializes a new SQLite database there, applies migrations 001–010 and 014 only to that new file, and starts the existing FastAPI application and Vite frontend on loopback. It is a disposable course-project fixture, not a production startup procedure. Do not upload real manuscripts or enter real accounts.

From the project root, after installing the dependencies described in the README:

```sh
.venv/bin/python -B scripts/run_isolated_rehearsal.py
```

Open the `http://127.0.0.1:…` address printed by the command. It prints a newly generated synthetic password and synthetic account names for Author, Editor, EIC, three Reviewers and Formatter; each account uses the printed local-only password. The displayed account names are combined with `@example.com`. No real credential is needed. Stop with **Ctrl-C** in the terminal. The launcher stops its servers and removes its own temporary root on normal shutdown. Abrupt termination may leave temporary artifacts; do not assume an interrupted write was committed. Each new run starts empty and does not preserve prior rehearsal data.

For a startup and five-role authentication check without leaving the servers running or displaying the generated password:

```sh
.venv/bin/python -B scripts/run_isolated_rehearsal.py --check
```

## Suggested walkthrough

1. Sign in as Reviewer and optionally add a self-reported professional profile. Sign in as Author, create a draft, upload synthetic UTF-8 TXT, open **Edit document (TXT)** and save a version, then submit.
2. Sign in as EIC, screen the manuscript and invite the Editor. As Editor, accept, open the TXT editor, save a draft and choose **Use saved draft** in the initial-editing panel. Submit it separately. Complete the Author, Editor and EIC approvals and Author pre-review confirmation.
3. As EIC, search the reviewer directory and invite two reviewers. Each Reviewer accepts, downloads the assigned document and submits a review. To demonstrate the conservative split case, use `accept` and `reject`; the EIC may then invite the third reviewer. The EIC retains the decision.
4. Accept the author agreement. Have the EIC invite a final Editor, who can similarly edit the confirmed current-round TXT, save a draft and explicitly submit it for both approvals. Invite the Formatter, who accepts and uploads a PDF proof; obtain Author and EIC approval and publish the local prototype.
5. Show the notification bell and evidence-backed timeline. Publication is local, and DOI registration remains pending.

The ordinary launcher leaves the experimental Single-Blind/Double-Blind gate disabled. The separate `tests/a6_browser_acceptance.py` and `tests/split_review_browser_acceptance.py` use synthetic-only internal overrides and preapproved synthetic artifacts; they do not activate those capabilities in this launcher or an existing environment. Do not claim production anonymity. Online editing supports UTF-8 TXT for eligible Authors and accepted Editors in the applicable stages; saving a draft does not submit or approve it. DOCX/DOC/PDF remain upload/download formats, not online-editable formats. New draft metadata is recorded by migration 014; historical files are preserved without inventing ledger entries. Real email, Google OAuth, CAPTCHA, external DOI registration and automatic document anonymization are not enabled by this launcher.

When an Editor chooses **Use saved draft**, the submission form carries the selected version to the server. Submission checks that the version and uploaded bytes still match the current draft while holding the SQLite write transaction. A changed draft must be selected again. This check applies to the online-draft selection flow; ordinary uploads remain separate. Migration 014 records new draft history; a TestClient lifecycle restart and database reconnect were tested, while a separate-process browser restart remains unverified.
