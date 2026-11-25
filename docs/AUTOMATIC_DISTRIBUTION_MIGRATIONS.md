# Automatic distribution migration entrypoint

For an explicitly selected SQLite database already upgraded through migration
027, `scripts/upgrade_automatic_distribution.py DATABASE` is the supported
forward-aware 028–030 upgrade and validation entrypoint. It does not run at
application startup and refuses the persistent Main `manuscript.db` path.
Apply migrations only under the project's separate database-change controls;
the Batch 76 tests used disposable databases.

Migration 028's original standalone entrypoint is historical: it verifies its
original trigger literally and therefore rejects the legitimate replacement
installed by 029. Do not rerun that old entrypoint on an upgraded database.
The supported entrypoint uses `scripts/validate_028_forward.py` for the
forward-aware 028/029 schema and validates 030 on upgrade/reapplication.
Empty downgrades must be performed in reverse order using the individual
migration functions; retained evidence prevents destructive downgrade.
