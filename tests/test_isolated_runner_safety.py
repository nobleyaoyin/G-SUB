"""The isolated runner must reject linked source paths before copying."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'scripts' / 'run_isolated_backend_tests.py'
spec = importlib.util.spec_from_file_location('isolated_backend_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerSafetyTests(unittest.TestCase):
    def test_rejects_linked_source_file(self):
        with tempfile.TemporaryDirectory(prefix='gsub-runner-safety-') as temporary:
            root = Path(temporary)
            (root / 'ordinary.py').write_text('synthetic')
            (root / 'linked.py').symlink_to(root / 'ordinary.py')
            with self.assertRaisesRegex(RuntimeError, 'Refusing symlink'):
                runner.reject_symlinks(root)

    def test_selected_tests_are_local_names(self):
        self.assertGreater(len(runner.TESTS), 0)
        self.assertTrue(all(Path(name).name == name and name.startswith('test_') and name.endswith('.py') for name in runner.TESTS))
