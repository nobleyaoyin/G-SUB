# Step 128.27.11 — Account and Reviewer Invitation Lifecycle Schema Design

## 1. Existing Architecture Findings

This is a design, not an implementation or approval to migrate. Inspected `app/models.py`, `app/security.py`, `app/routers/users.py`, `app/routers/assignments.py`, `app/routers/email_verification.py`, `app/email/verification_service.py`, `app/email/invitation_eligibility.py`, `app/email/attempt_state.py`, `app/email/worker_store.py`, migration files 001–008, and isolated tests. The repository currently contains migrations 001–008; **009 is available in the inspected working tree**, but recheck before implementing. No existing environment's migration ledger was inspected.

`User` has a role and email but no active/disabled state. `get_current_user` reloads the user and verification state; legacy users without a verification row may log in, and demo has its existing compatibility policy. Current JWTs contain `sub` and `exp` only (`app/security.py`): they have neither `iat` nor a session generation. Simply checking `disabled` on requests would block a token during deactivation but would make the same unexpired token usable again after reactivation. Missing users are rejected; role is read from the database. `user_email_verifications` records the email and verified timestamp, and email mismatch invalidates verification. None of this proves an account is active.

Migration 002 restricts reviewer invitation status to pending/accepted/declined; there is no explicit cancellation or supersession. The assignment endpoint checks EIC or assigned-editor permissions, current round and file binding, and prevents same-reviewer/round duplicate assignments. Decline is a reviewer response, not a cancellation. Existing send-time eligibility checks user role, verification, pending invitation, current round and binding inside a SQLite write transaction, but has no lifecycle/invalidation state to consult. Outbox 007 has `pending`, `processing`, `retry_wait`, `blocked_verification`, `accepted`, `failed`, `unknown`, and `cancelled`; `accepted` means provider acceptance, not inbox delivery. Current attempt helpers and fake simulator can be called without eligibility. No provider/worker enablement is proposed.

Migration 001 creates round/assignment file bindings and ledger; 002 reviewer invitations; 003 review policy; 004 author agreements; 005 final-editor links; 006 formatting/publication; 007 outbox; 008 verification (whose script explicitly requires 007 but checks object existence less thoroughly than 007). For 009, require ledger entries **and compatible definitions** for all 001–008 rather than assuming a ledger row proves integrity.

## 2. Proposed Lifecycle Policies

These are recommendations requiring owner approval, not current behavior.

- Explicit rows mean `active` or `disabled`. Missing rows mean **legacy/unknown**, never explicitly active. The schema-only migration inserts no rows. Existing login/JWT behavior remains exactly as today until a separately approved enforcement release. Invitation-email eligibility must fail closed unless an explicit `active` row exists, current reviewer role and verified current email are present, and all other invitation checks pass.
- A designated account administrator (propose EIC initially) can explicitly enroll a legacy account, disable an active account, or reactivate a disabled one. Require a currently authorized, explicitly active actor, audit each transition, prohibit self-disable and disabling the last authorized EIC, and prevent EIC-on-EIC changes until the owner defines governance. No account-admin role currently exists; bootstrap of the first explicitly active administrator requires a separately authorized offline procedure. Never create a bootstrap account or bypass authorization automatically.
- Proposed enforcement release: disabled users cannot obtain new JWTs and `get_current_user` rejects their existing JWTs on every protected request. Reactivation increments a per-user authentication generation; new JWTs include that generation, and protected requests compare it to the current row. A token issued before disable must remain invalid after reactivation. Existing tokens have no generation; during an approved rollout, retain current behavior for **missing-row legacy users** only, while rejecting unversioned tokens as soon as a lifecycle row is explicitly created. Define how long that transition and demo policy apply; do not infer activation from a legacy token. Use an integer generation, not timestamps vulnerable to equal-second ambiguity. Every disable/reactivate/enrollment changes generation atomically with its audit record. Verify all paths using `decode_access_token`, including verification endpoints and role dispatch, before enabling enforcement.
- Disabled/deleted users and missing or ambiguous records fail closed for delivery; verification is separately required. Role/email changes remain independently revalidated. A disabled user’s existing review history is retained; no automatic reassignment or destruction.

## 3. Proposed Invitation Invalidation Policies

EIC or an editor currently authorized for the manuscript may explicitly cancel or supersede a **pending** invitation, provided current state, target identity, role and current round are rechecked in the same short SQLite write transaction. A cancellation has no replacement; supersession refers to an already-created replacement reviewer invitation on the same manuscript and same round, for a different reviewer. Create replacement and invalidation atomically where appropriate. Same-reviewer duplicates remain subject to existing duplicate rules. Service must check the replacement remains eligible/pending and not invalidated, and prevent cycles. An append-only row records actor, UTC time and allowlisted reason code. No free-text manuscript or personal content in the audit.

Accepted invitations, completed reviews and declined invitations are historical: **proposed initial scope rejects invalidation requests for them** until the owner approves a separate accepted-reviewer removal workflow. A declined invitation remains declined and is never backfilled as cancelled. Existing invitations receive no invalidation rows. Round advance or changed reviewer/email/verification makes an email ineligible but is not itself an explicit cancellation. Supersession across rounds is rejected, and a separate new-round assignment is not automatically a supersession.

Future reviewer response, assigned-file and review authorization must check the invalidation row under a consistent transaction; otherwise a cancelled pending invitation could still be accepted. A future sender checks the row in the same transaction as `start_eligible_attempt`. Pending or retry-wait outbox rows known not to have an uncertain earlier attempt may eventually be conditionally marked cancelled under the approved policy. Never rewrite accepted, unknown, or started outcomes as definitely unsent. A started attempt can represent an in-flight request: preserve it and reconcile conservatively. Define recipient-facing notices and reassignment separately.

## 4. Complete Proposed Migration 009 Design

**Proposed SQL below has not been executed or validated.** It assumes `PRAGMA foreign_keys=ON`, `BEGIN IMMEDIATE`, and existing 001–008 tables. It is intentionally additive and has no user-data backfill. Exact timestamp shape is application-validated in UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`; SQL checks shape and length, not calendar validity. UTC-pattern checks must be mirrored in SQLAlchemy model constraints.

```sql
CREATE TABLE account_lifecycle_events (
    event_id TEXT NOT NULL PRIMARY KEY CHECK (length(event_id) BETWEEN 1 AND 64),
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (typeof(sequence) = 'integer' AND sequence >= 1),
    from_state TEXT CHECK (from_state IS NULL OR from_state IN ('active','disabled')),
    to_state TEXT NOT NULL CHECK (to_state IN ('active','disabled')),
    auth_generation INTEGER NOT NULL CHECK (typeof(auth_generation) = 'integer' AND auth_generation >= 1),
    actor_user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    occurred_at TEXT NOT NULL CHECK (
      occurred_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'),
    reason_code TEXT NOT NULL CHECK (reason_code IN ('initial_enrollment','administrative_disable','administrative_reactivation')),
    CHECK ((sequence = 1 AND from_state IS NULL AND to_state = 'active' AND reason_code = 'initial_enrollment')
        OR (sequence > 1 AND from_state = 'active' AND to_state = 'disabled' AND reason_code = 'administrative_disable')
        OR (sequence > 1 AND from_state = 'disabled' AND to_state = 'active' AND reason_code = 'administrative_reactivation')),
    UNIQUE(user_id, sequence),
    UNIQUE(event_id, user_id, sequence, to_state, auth_generation)
);
CREATE TABLE account_lifecycle (
    user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(user_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('active','disabled')),
    sequence INTEGER NOT NULL CHECK (typeof(sequence) = 'integer' AND sequence >= 1),
    auth_generation INTEGER NOT NULL CHECK (typeof(auth_generation) = 'integer' AND auth_generation >= 1),
    last_event_id TEXT NOT NULL,
    FOREIGN KEY(last_event_id, user_id, sequence, state, auth_generation)
      REFERENCES account_lifecycle_events(event_id, user_id, sequence, to_state, auth_generation)
      ON DELETE RESTRICT
);
CREATE INDEX ix_lifecycle_events_actor_time ON account_lifecycle_events(actor_user_id, occurred_at);

CREATE TABLE reviewer_invitation_invalidations (
    invalidation_id TEXT NOT NULL PRIMARY KEY CHECK (length(invalidation_id) BETWEEN 1 AND 64),
    assignment_id INTEGER NOT NULL UNIQUE REFERENCES reviewer_invitations(assignment_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('cancelled','superseded')),
    replacement_assignment_id INTEGER REFERENCES reviewer_invitations(assignment_id) ON DELETE RESTRICT,
    actor_user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    occurred_at TEXT NOT NULL CHECK (
      occurred_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'),
    reason_code TEXT NOT NULL CHECK (reason_code IN ('editorial_cancellation','reviewer_unavailable','replacement_selected')),
    CHECK ((kind = 'cancelled' AND replacement_assignment_id IS NULL
              AND reason_code IN ('editorial_cancellation','reviewer_unavailable'))
        OR (kind = 'superseded' AND replacement_assignment_id IS NOT NULL
              AND replacement_assignment_id <> assignment_id AND reason_code = 'replacement_selected'))
);
CREATE INDEX ix_reviewer_invalidation_actor_time ON reviewer_invitation_invalidations(actor_user_id, occurred_at);
CREATE INDEX ix_reviewer_invalidation_replacement ON reviewer_invitation_invalidations(replacement_assignment_id);

CREATE TRIGGER lifecycle_events_no_update BEFORE UPDATE ON account_lifecycle_events
BEGIN SELECT RAISE(ABORT, 'lifecycle events are append-only'); END;
CREATE TRIGGER lifecycle_events_no_delete BEFORE DELETE ON account_lifecycle_events
BEGIN SELECT RAISE(ABORT, 'lifecycle events are append-only'); END;
CREATE TRIGGER reviewer_invalidations_no_update BEFORE UPDATE ON reviewer_invitation_invalidations
BEGIN SELECT RAISE(ABORT, 'reviewer invalidations are append-only'); END;
CREATE TRIGGER reviewer_invalidations_no_delete BEFORE DELETE ON reviewer_invitation_invalidations
BEGIN SELECT RAISE(ABORT, 'reviewer invalidations are append-only'); END;
```

The DDL enforces a current-state-to-audit-row foreign key, basic state transitions, uniqueness, restrictive deletion and append-only audit records. It does **not** alone enforce chronological event sequence, current-row immutability or that a valid historical event is the latest; a transaction service must lock, use compare-and-set on current `(sequence, auth_generation)`, insert exactly the next event, update the pointer and increment generation together. A direct database writer can bypass those service rules. Consider additional triggers only after isolated testing; append-only triggers alone are not tamper-proof against schema-owning database administrators. An explicit user enrollment event needs an authorized actor; bootstrap must be decided separately. The schema does not provide a deletion policy; preserve history and do not use deletion to disable.

The DDL also cannot enforce same-manuscript, same-round, different-reviewer, target pending, replacement pending/uninvalidated, actor authorization or absence of cycles with SQLite CHECK constraints. Enforce them by re-reading and conditional writes under `BEGIN IMMEDIATE`, ideally with independent database triggers after a separately reviewed decision; all later responses, file/review access and round changes must honor invalidations. Test attempts to mutate the referenced assignment after invalidation; either enforce immutable assignment identity or revalidate it. A unique source assignment alone does not stop two old invitations being superseded by one replacement; decide whether a partial unique index on non-null replacement IDs is required. The proposed schema does not enforce this unresolved policy.

### Proposed migration procedure and models

- Name tentatively `migrations/009_account_invitation_lifecycle.py`, ledger `009_account_invitation_lifecycle`. Re-enumerate filenames and live ledger first; never overwrite another 009. Explicit existing SQLite path only, no startup execution or `create_all` for an existing database.
- Enable foreign keys, verify `integrity_check` and `foreign_key_check`, validate 001–008 ledger entries and prerequisite object/column/constraint definitions, verify no new names conflict across tables/indexes/views/triggers, then `BEGIN IMMEDIATE`, create exact objects, record ledger once and validate schema, empty new tables, indexes, triggers, constraints and foreign keys before commit. On failure roll back. Repeated execution validates the exact applied schema; partial/mismatched or conflicting state fails closed. Check consistency again under lock immediately before changes, not solely before acquiring it.
- Add matching SQLAlchemy `AccountLifecycleEvent`, `AccountLifecycle`, and `ReviewerInvitationInvalidation` in `app/models.py`, with matching FK, checks, unique constraints and indexes. Map composite FK accurately; triggers remain migration DDL. Avoid ORM cascade deletes, automatic defaults that create lifecycle rows, or implicit backfills. Test model/migration parity.
- Schema application and application policy activation are separate operations: the former creates empty tables; the latter changes authentication/workflow behavior and requires its own approval and rollout plan.

### Backup and recovery

For any later authorized migration, stop only approved relevant writers, create separate unique private verified SQLite backup-API snapshots and full upload backups for each environment, verify row counts, canonical full-content fingerprints, integrity, foreign keys, hashes and temporary restore, then rehearse on separate disposable copies and compare immediately before migration. Preserve credentials and secrets. No production migration commands should be run from this design alone. Dropping tables or restoring an old snapshot after new lifecycle/invalidation events could lose decisions and history; stop writers, preserve post-migration database/uploads and logs, assess external effects and obtain separate approval for recovery. Append-only triggers and restrictive FKs require an explicit audited rollback plan. No automatic restore.

## 5. Required Application Changes

Only after policy and implementation approval: lifecycle transaction service and authorization in a new `app/` module/router; `app/models.py` and proposed migration; `app/routers/users.py` plus `app/security.py` for versioned tokens and DB-backed enforcement; `app/email/invitation_eligibility.py` to require active lifecycle and no invalidation under the existing same lock; `app/routers/assignments.py`, `app/reviewer_invitations.py`, `app/routers/reviews.py` and file authorization to prohibit responses/download/reviews for invalidated assignments while preserving historical access rules; relevant response schemas and a separate operator UX only if approved. Future fake-only orchestration must require `start_eligible_attempt`, not call `start_attempt`/`simulate_attempt` directly, and must be tested against bypass; Python module visibility alone is not a security boundary. No worker or real transport is authorized here.

## 6. Legacy Compatibility Strategy

Migration inserts zero lifecycle and invalidation records. Missing lifecycle means unknown for email; it is not explicit activation. Existing login and JWT semantics for users without lifecycle rows continue until an approved enforcement rollout, including current demo behavior. Explicit activation is an audited, authorized action, not automatic backfill; define initial admin bootstrap and old unversioned token transition before implementation. Existing invitations, reviews, files and workflow history remain unchanged. Legacy invitations lacking explicit invitation or file binding remain unavailable to the prospective email flow rather than being guessed. Declines are never converted to cancellations.

## 7. Security and Concurrency Analysis

- **Deactivate versus attempt:** same SQLite write lock orders lifecycle update and `start_eligible_attempt`; whichever commits first determines the database snapshot. After start commit, deactivation may still occur before external delivery. A final recheck reduces but cannot eliminate that gap. If exact instantaneous revocation is mandatory, external send cannot safely be enabled without a stronger coordinated delivery design; do not claim SQLite offers that guarantee.
- **Cancellation after start:** retain the started record; an expired lease or ambiguous request becomes `unknown`. Cancellation must not overwrite evidence of provider acceptance, nor assume an email was not delivered. A future pre-send check may suppress if it knows no request has begun; define how this is durably proven.
- **Supersession / round race:** lock, re-read manuscript round, source and replacement assignments, role and invitations; insert invalidation and replacement in one transaction. Conditional response/update checks prevent acceptance after invalidation. If round changes first, reject; if supersession commits first, round transition must respect it. Preserve old round and file bindings.
- **JWT:** direct DB active checks block current tokens while disabled, but cannot stop token resurrection after reactivation without generation or equivalent revocation. Proposed generation solves it only after all token issuance/decoding paths and legacy rollout are updated.
- **Outbox / provider:** no network I/O under write lock. Do not auto-retry unknown, a lost response, or a failed/ambiguous commit. Provider idempotency support, scope and retention must be verified before use; reconciliation and operator handling require approval. Do not claim exactly-once or inbox delivery. Real sending remains disabled.

## 8. Test Commands and Actual Results

Existing fixtures were inspected: SQLite databases/uploads are in temporary directories; API dependencies and app engine are overridden; authentication tests use synthetic data and patched token/password functions. No new design-validation test or SQL migration was created or executed; proposed DDL and triggers are **not yet validated**. No network or real email was used.

| Command | Result |
|---|---|
| `.venv/bin/python -B -m unittest tests.test_account_invitation_lifecycle tests.test_invitation_email_eligibility tests.test_email_attempt_state -v` | **44 passed**, 0 failed, 0 skipped. |
| `.venv/bin/python -B -m unittest tests.test_email_outbox_claims tests.test_email_outbox tests.test_email_outbox_migration tests.test_email_infrastructure tests.test_reviewer_invitation_email_integration -v` | **74 passed**, 0 failed, 0 skipped; migration fixture tests are discovered in more than one module. Expected injected-failure diagnostics were logged. |
| `PYTHONPATH=tests .venv/bin/python -B -m unittest tests.test_reviewer_invitations -v` | **15 passed**, 0 failed, 0 skipped, including inherited reviewer-download tests. An existing `datetime.utcnow()` deprecation warning appeared. |
| `git diff --check` | Passed; untracked files are not checked by Git. |

Before any deployment, add disposable-database tests for exact DDL and model parity; missing prerequisites, partial schemas, repeated execution, transactional failure, empty/no-backfill and historical content fingerprints; check/FK/unique/append-only behavior and integrity checks; lifecycle and generation CAS, explicit enrollment, disable/reactivate, old JWT rejection, missing-row and demo policy; EIC/assigned-editor authorization and self/last-admin safeguards; pending/accepted/declined, replacement identity/round, concurrent response/supersession, immutable assignment links; audit and cancellation after a started/unknown attempt; atomic eligibility, stale leases and no transport before confirmed commit; full isolated regressions. Test rollback and restore using snapshots, not real data.

## 9. Remaining Decisions Requiring Approval

Who may manage lifecycle, EIC accounts and bootstrap the first administrator? What legacy users and demo accounts can log in during rollout, and when do unversioned JWTs stop working? Should disabled reviewers retain access to past review history? Are accepted invitations cancellable and how are completed reviews handled? Is one replacement allowed for multiple cancelled invitations? Which reason codes, notification recipients, retention and privacy rules apply? How are lifecycle and invalidation events audited operationally? What provider idempotency/reconciliation guarantee and post-commit cancellation race are acceptable? These decisions cannot be inferred from current code.

## 10. Recommended Step 128.27.12

After owner decisions, perform an isolated review and design-validation of the proposed DDL and token/enrollment rollout, including cross-row and migration rollback tests, **before** creating Migration 009 or changing runtime behavior. Seek separate approval for implementation and separately for applying any migration. No real email, application source, frontend, existing database/uploads, credentials, master backlog, prior migrations or reports were changed in this step; no commit, push, deployment, worker or scheduler was initiated.
