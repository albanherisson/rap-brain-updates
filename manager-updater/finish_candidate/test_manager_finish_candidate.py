"""Exercise the installed sequence-2 replay gate without starting a Mac server."""
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile

from manager_finish_candidate import prepare_dashboard, prepare_launcher
from manager_update_release import verify_manifest


WORK = Path(__file__).resolve().parents[2]
UPLOAD = WORK / 'upload'


def original_bytes():
    with zipfile.ZipFile(UPLOAD / 'RapBrain_Manager_Postcommit_Publication.zip') as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read('manager-postcommit/repair-3.zip'))) as inner:
            launcher = inner.read('app/launch_manager.py')
    with zipfile.ZipFile(UPLOAD / 'RapBrain_Manager_Repair_Publication(1).zip') as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read('manager-stable/update-2.zip'))) as inner:
            dashboard = inner.read('app/dashboard_beta14.html')
        signed = outer.read('manager-stable/manifest.json')
    return launcher, dashboard, signed


class FinishTest(unittest.TestCase):
    def test_exact_baselines_and_signed_current_release(self):
        launcher, dashboard, signed = original_bytes()
        self.assertEqual(verify_manifest(signed)['sequence'], 2)
        self.assertNotEqual(launcher, prepare_launcher(launcher))
        updated = prepare_dashboard(dashboard).decode()
        self.assertIn('<section class="panel section" id="updates">', updated)
        self.assertIn('Le Manager est déjà à jour.', updated)
        with self.assertRaisesRegex(ValueError, 'baseline_changed'):
            prepare_launcher(launcher + b' ')

    def test_accepted_release_skips_handoff_and_rejects_malformed_receipt(self):
        launcher, _, signed = original_bytes()
        updated = prepare_launcher(launcher)
        parsed = ast.parse(updated)
        function = next(node for node in parsed.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == 'handle_manager_update_request')
        namespace = {'Path': Path, 'json': json, 'hashlib': hashlib,
                     '__file__': '/synthetic/launch_manager.py'}
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     '<isolated candidate>', 'exec'), namespace)
        handler = namespace[function.name]

        def private_json(path, maximum):
            self.assertLessEqual(path.stat().st_size, maximum)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            return json.loads(path.read_bytes())

        helper = types.ModuleType('manager_helper_release')
        helper.verify_staged = lambda state: state
        release = types.ModuleType('manager_update_release')
        release.CHANNEL = 'signed-channel'
        release.fetch = lambda url, limit: signed
        release.verify_manifest = verify_manifest
        parent = types.ModuleType('manager_update_parent')
        def never_handoff(*args, **kwargs):
            self.fail('an accepted update must not start a server handoff')
        parent.prepare_handoff = never_handoff
        recovery = types.ModuleType('pending_attempt_recovery')
        recovery._private_json = private_json
        old = {name: sys.modules.get(name) for name in
               ('manager_helper_release', 'manager_update_release',
                'manager_update_parent', 'pending_attempt_recovery')}
        try:
            sys.modules.update(manager_helper_release=helper,
                               manager_update_release=release,
                               manager_update_parent=parent,
                               pending_attempt_recovery=recovery)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'requests'
                root.mkdir()
                backup = Path(tmp) / 'backups'
                secure = backup / 'secure-update'
                secure.mkdir(parents=True)
                receipt = secure / 'manager-accepted.json'
                receipt.write_text('{"sequence":2}')
                receipt.chmod(0o600)
                request = root / 'manager-update-request.json'
                request.write_text('{"action":"install-signed-manager"}')
                self.assertFalse(handler(root, Path(tmp), backup, {}))
                result = json.loads((root / 'manager-update-result.json').read_text())
                self.assertEqual(result, {'state': 'up_to_date',
                    'installation_performed': False, 'sequence': 2})
                self.assertFalse(request.exists())
                receipt.write_text('{"sequence":true}')
                request.write_text('{"action":"install-signed-manager"}')
                self.assertFalse(handler(root, Path(tmp), backup, {}))
                result = json.loads((root / 'manager-update-result.json').read_text())
                self.assertEqual(result['state'], 'refused')
        finally:
            for name, module in old.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == '__main__':
    unittest.main()
