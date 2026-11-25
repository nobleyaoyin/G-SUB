# Proposed reviewer lifecycle administration

Status: design proposal only; no reviewer administration endpoint or operator
procedure is implemented or authorized by this document.

## Need and scope

Current document authorization requires active, consistent reviewer lifecycle
evidence. Legitimate historical reviewers without that evidence cannot
download assigned documents. A production release that must serve those
accounts needs an explicitly authorized enrollment and reactivation workflow;
there is no verified existing operational alternative that avoids direct
database edits. Until a workflow is implemented and approved, leave such
accounts fail-closed. Do not automatically enroll or reactivate them.

## Proposed boundary

- Permit only an authenticated, currently active EIC or explicitly appointed
  lifecycle administrator whose authority is rechecked in the transaction.
  Reject reviewers, authors, editors without that authority, disabled actors,
  stale tokens, and unverified or missing authority evidence.
- Present a specific existing reviewer identity for explicit administrative
  confirmation. Enrollment is allowed only when no lifecycle history exists;
  reactivation only when valid current history is disabled. Require an action
  reason, unique request identifier, and expected sequence and generation.
- In one transaction validate target role, full prior history, and expected
  state; append an immutable audit event identifying actor, subject, action,
  reason, timestamp, and request identifier; update the lifecycle pointer and
  generation with a conditional write. Fail closed on inconsistent history,
  competing writes, failed audit insertion, or unknown commit outcome.
- Preserve all existing accounts, assignments, reviews, and historical events.
  The new active state alone never grants document access: authorization must
  still verify the exact accepted, current-round, non-invalidated assignment,
  permitted workflow stage and applicable blind-review policy.
- Do not create an automatic expiry mechanism: invitation expiry has no
  current timestamp model and needs a separate requirements and migration
  decision.

## Required tests and release decisions

Before implementation is accepted, isolated tests must demonstrate authorized
EIC enrollment of a previously un-enrolled reviewer and authorized
reactivation of a disabled reviewer, including immutable audit evidence,
generation changes, preserved history, and unchanged assignment restrictions.
Negative tests must deny non-administrators, disabled or stale administrators,
wrong target roles, duplicate requests, stale revisions, corrupt history,
unauthorized self-service, and concurrent conflicting actions. Tests must
cover rollback on audit failure and fail-closed handling of uncertain commits.

The proposal needs owner approval, a reviewed migration and backup/restore
plan, endpoint and UI contracts, and independent security review before any
production-facing interface is implemented. Existing EIC-only administration
tests cover their current boundary; they do not validate this proposed
reviewer workflow.
