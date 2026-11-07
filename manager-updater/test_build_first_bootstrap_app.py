"""The Finder wrapper packages the already verified updater code."""
from pathlib import Path
import sys
import tempfile
import unittest

from build_first_bootstrap_app import APPLE_SCRIPT, APP_NAME, build, dependencies
from creative_release import Refused


class FirstBootstrapAppTests(unittest.TestCase):
    def test_static_import_closure_includes_transaction_and_signature_verifier(self):
        names = {path.name for path in dependencies()}
        self.assertIn('first_bootstrap_installer.py', names)
        self.assertIn('bootstrap_full_transaction.py', names)
        self.assertIn('ed25519_runtime.py', names)
        self.assertIn('mac_offline_bootstrap_gate.py', names)
        self.assertFalse(any(name.startswith('test_') for name in names))

    def test_finder_selects_supported_python_before_install_entrypoint(self):
        self.assertIn('python_bootstrap_selector.sh', APPLE_SCRIPT)
        self.assertNotIn('do shell script "/usr/bin/python3', APPLE_SCRIPT)

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS osacompile')
    def test_builds_signed_disposable_finder_app_without_running_it(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / APP_NAME
            result = build(app)
            self.assertTrue(result['signature_verified'])
            self.assertEqual(result['modules'], len(dependencies()))
            self.assertTrue((app / 'Contents' / 'Resources' / 'updater' /
                             'first_bootstrap_installer.py').is_file())
            self.assertTrue((app / 'Contents' / 'Resources' / 'updater' /
                             'verify_ed25519.swift').is_file())
            self.assertTrue((app / 'Contents' / 'Resources' / 'updater' /
                             'python_bootstrap_selector.sh').is_file())

    def test_refuses_build_on_non_mac(self):
        if sys.platform == 'darwin':
            self.skipTest('Mac build is exercised separately')
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(Refused, 'macos_required'):
                build(Path(temp) / APP_NAME)


if __name__ == '__main__':
    unittest.main()
