# Collaboration Base Schema v1 — candidate

This is a newly approved collaboration baseline. It does not claim to reproduce any historical production Pre-001 schema.

`collaboration_base_v1.sql` is explicit SQLite DDL for eleven base tables compiled from the current Main-owned ORM declarations and reviewed against migration 001 prerequisites. It creates a version marker, not historical migration ledger entries. Migrations 001–019 and 021 retain their own identities and own the remaining schema objects. No migration 020 exists.

A disposable trial exercises migrations 001–019, 021–040 and 046. Migration 046 atomically creates the submission tables and records the 041–045 identities; those five rehearsal migrations must not be applied beforehand. The legacy baseline tests separately exercise 001–019 and 021, including migration 021 downgrade protections. This is preliminary evidence, not a supported persistent installer or upgrade. Do not use this DDL on an existing database, original Main data, or production.

The DDL uses ORM-derived Python-side defaults where applicable; SQLite server defaults are only present when explicitly shown in the SQL. Foreign keys without an explicit `ON DELETE` clause use SQLite `NO ACTION`. The base defines no triggers; later migrations define their own triggers. Application code, not the SQL file, must set `PRAGMA foreign_keys=ON` on every connection. Rerunning the SQL against an initialized database fails rather than silently modifying it; the focused test verifies that the existing version record survives.

## Isolated disposable initializer

From the collaboration workspace with Python 3.12 dependencies installed, an operator can create a **new disposable** database under the already-existing, owner-controlled `.test-data` directory:

```sh
.venv312/bin/python -m database.bootstrap.initialize --name example.sqlite
```

The initializer accepts only a simple new `.sqlite` filename, rejects symlinked or unsafe roots and path escapes, requires the workspace to be inside Python's system temporary directory, uses exclusive no-follow creation, and checks schema version, exact migration ledger and foreign keys. It refuses every pre-existing file. If a migration fails, it retains the new partial file for inspection and never deletes it. Each migration has its own transaction; the entire initialization is not atomic. The file is for disposable validation only. This is not a production migration tool.

For any future persistent upgrade, first obtain an approved plan and create
independently restorable, consistent backups of the database and relevant
journal/WAL state, uploads, and all configured private artifact and attachment
stores. Preserve the corresponding protected configuration separately.
Migration 046 has not established upgrade or restore safety for existing
Main data; never use the disposable initializer or rehearsal as an upgrade.
