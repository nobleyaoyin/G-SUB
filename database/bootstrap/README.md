# Collaboration Base Schema v1 — candidate

This is a newly approved collaboration baseline. It does not claim to reproduce any historical production Pre-001 schema.

`collaboration_base_v1.sql` is explicit SQLite DDL for eleven base tables compiled from the current Main-owned ORM declarations and reviewed against migration 001 prerequisites. It creates a version marker, not historical migration ledger entries. Migrations 001–019 and 021 retain their own identities and own the remaining schema objects. No migration 020 exists.

A disposable `.test-data` trial and the focused tests applied the scripts in numeric order, repeated them, checked foreign keys and tested migration 021 empty downgrade and nonempty refusal. This is preliminary evidence, not a supported deployment or a validated bootstrap installer. The backend cannot yet import because its reviewer trust context is unresolved. Do not use this DDL on an existing database, original Main data, or production. A path-guarded initializer, full workflow validation, transaction/partial-failure handling and independent security review remain required before teammate setup or publication.

The DDL uses ORM-derived Python-side defaults where applicable; SQLite server defaults are only present when explicitly shown in the SQL. Foreign keys without an explicit `ON DELETE` clause use SQLite `NO ACTION`. The base defines no triggers; later migrations define their own triggers. Application code, not the SQL file, must set `PRAGMA foreign_keys=ON` on every connection. Rerunning the SQL against an initialized database fails rather than silently modifying it; the focused test verifies that the existing version record survives.

## Isolated disposable initializer

From the collaboration workspace with Python 3.12 dependencies installed, an operator can create a **new disposable** database under the already-existing, owner-controlled `.test-data` directory:

```sh
.venv312/bin/python -m database.bootstrap.initialize --name example.sqlite
```

The initializer accepts only a simple new `.sqlite` filename, rejects symlinked or unsafe roots and path escapes, uses exclusive no-follow creation, runs 001–019 and 021, and checks schema version, exact migration ledger and foreign keys. It refuses every pre-existing file. If a migration fails, it retains the new partial file for inspection and never deletes it. Each migration has its own transaction; the entire initialization is not atomic. The file is for disposable validation only. Backend development configuration still resolves the database separately, and the missing reviewer adapter prevents startup; this command is not a complete teammate setup or production migration tool.
