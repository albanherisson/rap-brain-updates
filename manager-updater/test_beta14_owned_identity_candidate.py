import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from beta14_owned_identity_candidate import prepare
from test_beta14_runtime_token_candidate import FIXTURE


class IdentityLauncherTests(unittest.TestCase):
    def test_exact_beta14_copy_compiles_and_source_stays_unchanged(self):
        paths = list(Path(__file__).parents[2].glob(
            'beta14_disposable/**/Contents/Resources/launch_manager.py'))
        if not paths:
            self.skipTest('owner archive unavailable in checkout')
        original = paths[0].read_bytes()
        output = prepare(original)
        self.assertIn(b"state['process_start_token']=None", output)
        self.assertEqual(original, paths[0].read_bytes())

    def test_handle_token_source_hash_and_os_start_stay_private(self):
        output = prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())
        scope = {'__name__': 'fixture'}
        exec(output, scope)
        class Child:
            pid = 5100
            def poll(self): return None
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            script = root / 'server.py'
            script.write_bytes(b'# fixture\n')
            backup = root / 'backup'
            backup.mkdir()
            state = {}
            result = types.SimpleNamespace(returncode=0, stderr='',
                                           stdout='Tue Oct 27 21:36:22 2026\n')
            with (patch.object(scope['subprocess'], 'Popen', return_value=Child()),
                  patch.object(scope['subprocess'], 'run', return_value=result)):
                scope['handle_launch_request'](root, root, backup, state)
            self.assertNotIn('error', state)
            self.assertEqual(state['server_sha256'], hashlib.sha256(script.read_bytes()).hexdigest())
            self.assertEqual(state['process_start_token'], '5100:Tue Oct 27 21:36:22 2026')
            self.assertEqual(len(state['runtime_token']), 64)
            state.clear()
            result.returncode = 1
            with (patch.object(scope['subprocess'], 'Popen', return_value=Child()),
                  patch.object(scope['subprocess'], 'run', return_value=result)):
                scope['handle_launch_request'](root, root, backup, state)
            self.assertNotIn('error', state)
            self.assertIsNone(state['process_start_token'])


if __name__ == '__main__':
    unittest.main()
