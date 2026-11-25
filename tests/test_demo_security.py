import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import importlib
import sqlite3

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT / ".venv/bin/python"

class DemoSecurityTest(unittest.TestCase):
    def test_demo_initialization_and_security(self):
        with tempfile.TemporaryDirectory(prefix="demo-security-") as temporary:
            root = Path(temporary).resolve() / "demo"
            command = [str(PYTHON), str(PROJECT / "scripts/init_demo.py"), "--data-root", str(root)]
            created = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(subprocess.run(command, cwd=PROJECT, capture_output=True).returncode, 1)
            # The isolated legacy initializer creates empty comment tables but
            # the current gateway requires their migration-owned definitions.
            # Repair only this freshly initialized temporary test database.
            self.assertTrue(root.resolve().is_relative_to(Path(temporary).resolve()))
            fixture_db = root / 'manuscript.db'
            with sqlite3.connect(fixture_db) as db:
                for table in ('general_comments', 'personal_notes'):
                    self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
                    db.execute(f'DROP TABLE {table}')
            for migration in ('014_online_document_versions', '017_ai_prescreening',
                              '018_general_comments', '019_personal_notes'):
                importlib.import_module('migrations.' + migration).migrate(fixture_db)
            env = os.environ.copy()
            env.update(MANUSCRIPT_MODE="demo", MANUSCRIPT_DEMO_ROOT=str(root), PYTHONPATH=str(PROJECT))
            probe = subprocess.run([str(PYTHON), str(PROJECT / "tests/demo_security_probe.py")], cwd=PROJECT, env=env, capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            (root / "accounts.json").rename(root / "accounts.hidden")
            missing_accounts = subprocess.run([str(PYTHON), "-c", "import app.demo_gateway"], cwd=PROJECT, env=env, capture_output=True)
            self.assertNotEqual(missing_accounts.returncode, 0)

    def test_unsafe_roots_and_missing_credentials_fail(self):
        with tempfile.TemporaryDirectory(prefix="demo-invalid-") as temporary:
            root = Path(temporary).resolve()
            unsafe_link = root / "link"
            unsafe_link.symlink_to(PROJECT, target_is_directory=True)
            for candidate in ("", str(PROJECT), str(PROJECT / "uploads"), str(unsafe_link), str(root)):
                env = os.environ.copy()
                env.update(MANUSCRIPT_MODE="demo", MANUSCRIPT_DEMO_ROOT=candidate, PYTHONPATH=str(PROJECT))
                result = subprocess.run([str(PYTHON), "-c", "import app.security"], cwd=PROJECT, env=env, capture_output=True)
                self.assertNotEqual(result.returncode, 0, candidate)

if __name__ == "__main__":
    unittest.main()
