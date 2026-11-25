# Reviewer account lifecycle and document access

Reviewer document downloads require a valid authenticated reviewer with an
active, internally consistent lifecycle record and an active, accepted,
non-invalidated assignment for the manuscript's current review round and
review stage. The same rule applies to downloads of the reviewer's own
reviewed-document versions. A historical listing is not authorization to
download bytes.

Completed, pending, declined, revoked, legacy-without-invitation, stale-round,
and explicitly expired assignment states do not satisfy the download rule.
The invitation schema has no expiry timestamp or implemented automatic
expiration mechanism; this rule does not infer expiry from age.

## Enrollment and reactivation limitations

An existing reviewer without valid active lifecycle evidence fails closed.
There is currently no verified production-facing reviewer enrollment or
reactivation workflow in this candidate. The exposed lifecycle administration
router targets EIC accounts, while the more general `lifecycle_change`
prototype uses a synthetic principal authority. Its tests demonstrate
enrollment and reactivation transitions; they are not an operator procedure
or proof of a production authorization integration.

A production-capable path requires a separately implemented and reviewed
administrative workflow that authenticates an authorized active administrator,
checks the target and expected lifecycle generation, records an auditable
transition, and is tested against preserved historical records. A disabled
account must not be reactivated automatically. Do not edit database records
manually or use the synthetic prototype as a substitute for that workflow.
Until such a path is available and approved, legitimate historical reviewer
accounts without active lifecycle evidence cannot use these document downloads.
