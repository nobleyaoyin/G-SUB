"""Fresh synthetic initialization must not pre-create later migration tables."""
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class InitializerSchemaContractTests(unittest.TestCase):
    def test_fresh_initializer_respects_migration_ownership(self):
        with tempfile.TemporaryDirectory(prefix='gsub-init-contract-') as temporary:
            root = Path(temporary).resolve() / 'fresh-demo'
            result = subprocess.run([str(PROJECT / '.venv/bin/python'), str(PROJECT / 'scripts/init_demo.py'), '--data-root', str(root)],
                                    cwd=PROJECT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            with sqlite3.connect(f'file:{root / "manuscript.db"}?mode=ro', uri=True) as db:
                migrations = {row[0] for row in db.execute('SELECT migration_id FROM schema_migrations')}
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            for number, owned in {
                '007': {'notification_events', 'email_outbox', 'email_delivery_attempts'},
                '008': {'user_email_verifications', 'email_verification_challenges'},
                '009': {'account_lifecycle_events', 'account_lifecycle', 'reviewer_invitation_invalidations'},
            }.items():
                if not any(value.startswith(number + '_') for value in migrations):
                    self.assertFalse(tables & owned, f'Migration {number} is absent but its tables exist: {sorted(tables & owned)}')


if __name__ == '__main__':
    unittest.main()
