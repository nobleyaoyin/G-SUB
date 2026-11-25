import hashlib
import importlib.util
import json
import os
import pwd
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('safe_sync',Path(__file__).resolve().parents[1]/'scripts/safe_main_stable_sync.py')
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)


class SafeSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='gsub-sync-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.source=self.root/'main';self.target=self.root/'stable';self.backups=self.root/'private-backups'
        for p in (self.source,self.target,self.backups):p.mkdir(mode=0o700)
        for root in (self.source,self.target):
            (root/'frontend/public').mkdir(parents=True)
            (root/'frontend/index.html').write_text('old\n')
            (root/'frontend/public/favicon.svg').write_text('old icon\n')
        (self.source/'frontend/index.html').write_text('new\n')
        (self.source/'frontend/public/favicon.svg').write_text('new icon\n')
        self.engine=sync.Engine(self.source,self.target);self.addCleanup(self.engine.close)
        self.names=['frontend/index.html','frontend/public/favicon.svg']

    def manifest(self):
        m=self.engine.scan(self.names);raw=sync.canonical(m);p=self.root/'review.json';p.write_bytes(raw);return p,hashlib.sha256(raw).hexdigest()

    def test_dry_run_has_exact_diff_and_changes_nothing(self):
        before=(self.target/'frontend/index.html').read_bytes();m=self.engine.scan(self.names)
        self.assertEqual((self.target/'frontend/index.html').read_bytes(),before)
        self.assertIn('-old\n+new\n',m['entries'][0]['diff'])
        self.assertFalse(list(self.backups.iterdir()))

    def test_protected_and_unallowlisted_paths_are_rejected(self):
        for value in ('../x','/tmp/x','frontend/../index.html','.demo_data/accounts.json','frontend/dist/index.html',
                      'frontend/node_modules/index.html','app/credentials.py','frontend/.env','frontend/src/unknown.jsx',
                      'frontend/src/file.log','frontend//index.html','frontend/src/AuthorDashboard.jsx.before'):
            with self.subTest(value=value),self.assertRaises(ValueError):sync.validate_path(value)

    def test_intentional_difference_is_reportable_but_not_applicable(self):
        for root in (self.source,self.target):
            (root/'frontend/src').mkdir(parents=True,exist_ok=True)
            (root/'frontend/src/AuthorDashboard.css').write_text('main' if root==self.source else 'demo')
        m=self.engine.scan(['frontend/src/AuthorDashboard.css']);p=self.root/'review-only.json';raw=sync.canonical(m);p.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'review-only'):
            self.engine.apply(p,hashlib.sha256(raw).hexdigest(),self.backups)
        self.assertEqual((self.target/'frontend/src/AuthorDashboard.css').read_text(),'demo')
        self.assertFalse(list(self.backups.iterdir()))

    def test_symlink_and_hardlink_are_rejected(self):
        p=self.target/'frontend/index.html';p.unlink();p.symlink_to(self.source/'frontend/index.html')
        with self.assertRaises((OSError,ValueError)):self.engine.scan(['frontend/index.html'])
        p.unlink();os.link(self.source/'frontend/index.html',p)
        with self.assertRaises(ValueError):self.engine.scan(['frontend/index.html'])

    def test_parent_symlink_is_rejected(self):
        p=self.target/'frontend/public';p.rename(self.target/'frontend/real-public');p.symlink_to(self.target/'frontend/real-public',target_is_directory=True)
        with self.assertRaises((OSError,ValueError)):self.engine.scan(['frontend/public/favicon.svg'])

    def test_approval_and_source_target_drift_fail_before_writes(self):
        p,h=self.manifest()
        with self.assertRaises(ValueError):self.engine.apply(p,'0'*64,self.backups)
        (self.target/'frontend/index.html').write_text('concurrent')
        with self.assertRaises(ValueError):self.engine.apply(p,h,self.backups)
        self.assertFalse(list(self.backups.iterdir()))
        (self.target/'frontend/index.html').write_text('old\n');(self.source/'frontend/index.html').write_text('changed')
        with self.assertRaises(ValueError):self.engine.apply(p,h,self.backups)

    @unittest.skipUnless(sys_platform := __import__('sys').platform == 'darwin','macOS metadata API required')
    def test_apply_backup_metadata_and_rollback(self):
        target=self.target/'frontend/index.html';target.chmod(0o640);p,h=self.manifest();op=self.engine.apply(p,h,self.backups)
        self.assertEqual(target.read_text(),'new\n');self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o640)
        self.assertEqual((op/'0.backup').read_text(),'old\n')
        self.engine.rollback(op,h);self.assertEqual(target.read_text(),'old\n');self.assertTrue((op/'0.backup').exists())

    @unittest.skipUnless(sys_platform,'macOS metadata API required')
    def test_partial_failure_rollback_and_drift_conflict(self):
        p,h=self.manifest()
        def fail(phase,index):
            if phase=='replaced':raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):self.engine.apply(p,h,self.backups,fault=fail)
        op=next(self.backups.iterdir());changed=self.target/'frontend/index.html';changed.write_text('external edit')
        with self.assertRaises(ValueError):self.engine.rollback(op,h)
        self.assertEqual(changed.read_text(),'external edit')
        changed.write_text('new\n');self.engine.rollback(op,h)
        self.assertEqual(changed.read_text(),'old\n');self.assertEqual((self.target/'frontend/public/favicon.svg').read_text(),'old icon\n')

    @unittest.skipUnless(sys_platform,'macOS metadata API required')
    def test_interruption_before_replacement_leaves_original(self):
        p,h=self.manifest()
        def fail(phase,index):
            if phase=='prepared':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):self.engine.apply(p,h,self.backups,fault=fail)
        op=next(self.backups.iterdir());self.assertEqual((self.target/'frontend/index.html').read_text(),'old\n')
        self.engine.rollback(op,h);self.assertEqual((self.target/'frontend/index.html').read_text(),'old\n')

    @unittest.skipUnless(sys_platform, 'macOS metadata API required')
    def test_extended_attribute_survives_apply_and_rollback(self):
        target=self.target/'frontend/index.html'
        subprocess.run(['/usr/bin/xattr','-w','org.gsub.test','synthetic',str(target)],check=True)
        p,h=self.manifest();op=self.engine.apply(p,h,self.backups)
        def value():return subprocess.run(['/usr/bin/xattr','-p','org.gsub.test',str(target)],check=True,capture_output=True).stdout.strip()
        self.assertEqual(value(),b'synthetic');self.engine.rollback(op,h);self.assertEqual(value(),b'synthetic')

    @unittest.skipUnless(sys_platform, 'macOS metadata API required')
    def test_acl_survives_apply_and_rollback(self):
        target=self.target/'frontend/index.html';user=pwd.getpwuid(os.getuid()).pw_name
        subprocess.run(['/bin/chmod','+a',f'{user} allow read',str(target)],check=True)
        def acl():return subprocess.run(['/bin/ls','-le',str(target)],check=True,capture_output=True).stdout.splitlines()[1:]
        expected=acl();self.assertTrue(expected);p,h=self.manifest();op=self.engine.apply(p,h,self.backups)
        self.assertEqual(acl(),expected);self.engine.rollback(op,h);self.assertEqual(acl(),expected)

    @unittest.skipUnless(sys_platform, 'macOS metadata API required')
    def test_drift_after_staging_is_rejected_without_replacement(self):
        p,h=self.manifest();target=self.target/'frontend/index.html'
        def mutate(phase,index):
            if phase=='prepared' and index==0:target.write_text('external edit')
        with self.assertRaises(ValueError):self.engine.apply(p,h,self.backups,fault=mutate)
        self.assertEqual(target.read_text(),'external edit')

    @unittest.skipUnless(sys_platform, 'macOS metadata API required')
    def test_source_drift_after_staging_is_rejected(self):
        p,h=self.manifest();source=self.source/'frontend/index.html';target=self.target/'frontend/index.html'
        def mutate(phase,index):
            if phase=='prepared' and index==0:source.write_text('changed later')
        with self.assertRaises(ValueError):self.engine.apply(p,h,self.backups,fault=mutate)
        self.assertEqual(target.read_text(),'old\n')

    def test_missing_file_and_unsafe_backup_parent_rejected(self):
        (self.target/'frontend/index.html').unlink()
        with self.assertRaises(FileNotFoundError):self.engine.scan(['frontend/index.html'])
        (self.target/'frontend/index.html').write_text('old\n');p,h=self.manifest()
        with self.assertRaises(ValueError):self.engine.apply(p,h,self.target)

if __name__=='__main__':unittest.main()
