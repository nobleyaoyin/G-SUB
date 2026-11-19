# Collaboration Base Schema v1 manifest

Newly approved collaboration baseline; not a historical pre-001 schema. The exact columns, primary and foreign keys, unique indexes and any explicit constraints are the explicit statements in `collaboration_base_v1.sql`; this manifest does not supersede that SQL.

Base-owned: `collaboration_schema_version`, `users`, `manuscripts`, `eic_decisions`, `eic_initial_scans`, `final_editing_submissions`, `initial_editing_submissions`, `initial_editor_invitations`, `notifications`, `review_assignments`, `pre_review_confirmations`, `reviews`. Base creates no triggers and no historical `schema_migrations` rows. Migration 001 creates/validates the ledger. The SQLite `ix_users_email` index is unique; further base indexes are explicitly named in the SQL. Foreign keys default to SQLite `NO ACTION` unless the statement explicitly states otherwise. Most domain defaults remain Python ORM defaults and are not database server defaults.

Migration ownership: original scripts 001–019 and 021 create their own tables, indexes, checks and triggers. No script was replaced or superseded in the disposable candidate trial. This trial does not establish compatibility with any existing database. Migration 021 supports downgrade only when its distribution history is empty; other migrations have no general tested downgrade here.
