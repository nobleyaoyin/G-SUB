"""Verify the rehearsal fixture refuses unsafe roots before importing the application."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SERVER=ROOT/'tests/five_role_rehearsal_server.py'


def launch(path):
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONPATH':str(ROOT),
         'PYTHON_DOTENV_DISABLED':'1','REHEARSAL_ROOT':str(path),'REHEARSAL_PORT':'1'}
    if os.environ.get('TMPDIR'): env['TMPDIR']=os.environ['TMPDIR']
    return subprocess.run([sys.executable,'-B',str(SERVER)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)


class IsolatedFixtureSafetyTests(unittest.TestCase):
    def test_project_root_is_rejected_before_app_import(self):
        result=launch(ROOT)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Refusing non-disposable root',result.stderr)

    def test_nonempty_temporary_root_is_rejected_without_touching_it(self):
        with tempfile.TemporaryDirectory(prefix='gsub-rehearsal-') as tmp:
            marker=Path(tmp)/'marker';marker.write_text('synthetic')
            result=launch(tmp)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Refusing nonempty fixture root',result.stderr)
            self.assertEqual(marker.read_text(),'synthetic')

if __name__=='__main__': unittest.main()
