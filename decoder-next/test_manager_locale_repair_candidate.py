import ast
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import zipfile

from manager_locale_repair_candidate import launcher, identity


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'manager-updater'))
from creative_release import Refused


def signed_sources():
    with zipfile.ZipFile(ROOT.parent / 'upload/RapBrain_Manager_Finish_Publication.zip') as public:
        with zipfile.ZipFile(io.BytesIO(public.read('manager-stable/update-3.zip'))) as app:
            original_launcher = app.read('app/launch_manager.py')
    with zipfile.ZipFile(ROOT.parent / 'upload/RapBrain_Manager_Postcommit_Publication.zip') as public:
        with zipfile.ZipFile(io.BytesIO(public.read('manager-postcommit/repair-3.zip'))) as outer:
            with zipfile.ZipFile(io.BytesIO(outer.read('helper.zip'))) as helper:
                original_identity = helper.read('helper/process_start_identity.py')
    return original_launcher, original_identity


class LocaleRepairTests(unittest.TestCase):
    def test_retain_exact_child_identity_in_french_mac_locale(self):
        app_raw, identity_raw = signed_sources()
        candidate = launcher(app_raw)
        self.assertNotEqual(candidate, app_raw)
        self.assertEqual(hashlib.sha256(app_raw).hexdigest(),
                         '0175fa828072b999760570c6a7609bc424d2ea229977202a9880df7aaa742db6')
        tree = ast.parse(candidate)
        handler = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and
                       node.name == 'handle_launch_request')
        module = ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[]))
        scope = {'json': json, 'os': os, 'subprocess': subprocess,
                 'sys': sys, 'time': time, 'port_in_use': lambda: False,
                 '__rb_ordinary_launch_guard_v1': lambda *_: None}
        exec(compile(module, 'launch_manager.py', 'exec'), scope)

        class Child:
            pid = 13346
            def poll(self): return None

        stamp = 'Sat Nov\u00a0 7 08:34:51 2026\n'
        ps = types.SimpleNamespace(returncode=0, stdout=stamp, stderr='')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / 'backup'
            backup.mkdir()
            (root / 'server.py').write_bytes(b'fixture')
            (root / 'launch-request.json').write_text(
                json.dumps({'action': 'start', 'script': 'server.py'}))
            state = {}
            with (patch.object(subprocess, 'Popen', return_value=Child()),
                  patch.object(subprocess, 'run', return_value=ps) as run):
                scope['handle_launch_request'](root, root, backup, state)
            self.assertEqual(state['process_start_token'],
                             '13346:Sat Nov 7 08:34:51 2026')
            self.assertIs(state['process'].pid, Child.pid)
            self.assertEqual(len(state['runtime_token']), 64)
            self.assertEqual(state['server_sha256'], hashlib.sha256(b'fixture').hexdigest())
            self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

        helper = {'__name__': 'process_start_identity', 'Refused': Refused}
        exec(identity(identity_raw), helper)
        self.assertEqual(helper['parse_start'](stamp, 13346),
                         state['process_start_token'])
        with self.assertRaises(Refused):
            helper['parse_start']('sam.\u00a0 7 nov. 08:34:51 2026', 13346)
        with self.assertRaises(Refused):
            helper['parse_start'](stamp + stamp, 13346)
        with patch.object(subprocess, 'run', return_value=ps) as run:
            self.assertEqual(helper['read_start'](13346), state['process_start_token'])
            self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

    def test_other_base_or_missing_anchor_is_refused(self):
        app, helper = signed_sources()
        with self.assertRaisesRegex(ValueError, 'baseline_changed'):
            launcher(app + b' ')
        with self.assertRaisesRegex(ValueError, 'baseline_changed'):
            identity(helper + b' ')


if __name__ == '__main__':
    unittest.main()
