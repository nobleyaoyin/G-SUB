# Release scope and known limitations

## Supported scope

This repository supports **Collaboration Development only**, using a disposable
clone, isolated database, and local development services as described in the
[README](../README.md). It is not a production deployment. The configuration
rejects Demo mode. Legacy Demo launchers, documentation, and tests are retained
for history but are unsupported by this release.

## Verified in isolated tests

The disposable collaboration initializer creates a new private database and
applies the documented migration selection. Synthetic tests exercise reviewer
authorization, Double Blind fail-closed handling, EIC/editor permissions, author
ownership, manuscript workflow and a migration 046 rehearsal. Verification is
limited to the recorded tests; it is not a guarantee of complete workflow or
deployment security. See the release report for exact results.

## Known limitations

EIC lifecycle administration is included in this release. The offline bootstrap and succession commands
accept only the explicitly configured private collaboration database inside
the temporary clone's `.test-data` directory; it retains its independent
root-owned trust anchor, signed approval, nonce and stopped-writer checks.
Automated tests use synthetic trust and do not validate an owner's actual
trust-anchor provisioning or a persistent deployment procedure.

The bootstrap and succession commands do not independently prove that SQLite
opened the same database object identified in the signed approval. Use them
only for disposable synthetic development databases, in an isolated session
where no other process can modify the database directory, its parent paths,
the database or its SQLite sidecars. A stopped-writer confirmation and the
optional maintenance barrier do not establish that isolation. These conditions
reduce operational exposure but do not establish the missing identity guarantee;
do not use these commands on persistent data until that guarantee is reviewed
and a supported operational procedure is validated.

- Historical reviewer enrollment/reactivation management is not implemented.
  Reviewers without valid active lifecycle evidence cannot access review
  documents until a future authorized process exists. They are not
  automatically reactivated.
- Invitation records do not implement automatic time-based expiration.
- Existing Main database upgrade and restoration have not been verified.
  Migration 046 and the bootstrap are restricted to disposable databases.
- The historical full backend suite contains four legacy Demo cases outside
  the supported scope. The Collaboration Development test selection explicitly
  reports their deselection; it does not claim those tests passed.
- The owner identifies the historical mock login as a classroom test fixture;
  this has not been independently verified. Any evidence that it was used for a
  real account requires private owner investigation and credential rotation.
- A full independent line-by-line review of the large candidate is still
  required. Pattern scans cannot prove the absence of secrets or private data.

## Untested capabilities and future work

Real external providers, browser acceptance, and production ONLYOFFICE
integrations were not tested. Google sign-in, CAPTCHA, email, ONLYOFFICE, and
private storage require separate configuration; do not expose credentials or
start external services without authorization. Future work includes a
reviewed, authorized reviewer enrollment/reactivation process and a separate
persistent backup, migration, and restoration plan. See
[reviewer lifecycle limitations](REVIEWER_ACCOUNT_LIFECYCLE.md) and the
[proposal](REVIEWER_LIFECYCLE_PROPOSAL.md).
