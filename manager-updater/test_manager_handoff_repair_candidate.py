import hashlib
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from manager_repair_candidate import prepare_launcher
from manager_native_handoff_candidate import prepare as native_source
from manager_handoff_repair_candidate import prepare_proof, prepare_helper


HERE = Path(__file__).resolve().parent


class HandoffRepairCandidateTests(unittest.TestCase):
    def test_exact_launcher_has_stable_path_and_coordinated_exit(self):
        with ZipFile(HERE.parent / 'manager-capability' / 'capability-1.zip') as package:
            source = prepare_launcher(package.read('app/launch_manager.py')).decode()
        self.assertIn('prepare_handoff(rap_dir,stable_launcher,secure_state,', source)
        self.assertIn("raise RuntimeError('stable_manager_app_changed')", source)
        self.assertIn('if handle_manager_update_request(root,rap_dir,backup_dir,supervisor_state):return 42', source)
        self.assertIn("'aborted','committed','rolled_back'", source)

    def test_native_app_quits_only_after_handoff_exit_code(self):
        original = Path(__file__).parents[2] / 'beta14_inspection' / 'RapBrainManagerNative.swift'
        source = native_source(original.read_bytes()).decode()
        self.assertIn('proc.terminationReason == .exit && proc.terminationStatus == 42', source)
        self.assertIn('NSApp.terminate(nil)', source)
        with self.assertRaises(ValueError):
            native_source(original.read_bytes() + b' ')

    def test_helper_waits_for_native_app_before_reading_stage(self):
        source = prepare_helper((HERE / 'manager_update_helper.py').read_bytes()).decode()
        self.assertLess(source.index('offline(source, launcher)'), source.index('signed, archive = staged_release'))
        self.assertIn('time.monotonic() + 10', source)
        with self.assertRaises(ValueError):
            prepare_helper(source.encode())

    def test_parent_identity_uses_c_locale(self):
        source = prepare_proof((HERE / 'manager_handoff_proof.py').read_bytes())
        namespace = {'__name__': 'candidate_proof'}
        exec(compile(source, 'candidate_proof.py', 'exec'), namespace)
        with patch('subprocess.run', return_value=subprocess.CompletedProcess(
                [], 1, '', '')) as run:
            self.assertTrue(namespace['parent_has_exited'](123, '123:Thu Nov 5 13:00:06 2026'))
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')


if __name__ == '__main__':
    unittest.main()
