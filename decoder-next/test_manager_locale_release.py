"""Verify the offline repair's signed scope with disposable Ed25519 keys."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'manager-updater' / 'locale_v4'))
sys.path.insert(1, str(ROOT / 'manager-updater'))
from creative_release import Refused, canonical, digest
from manager_helper_inventory import HELPER_FILES
from manager_locale_repair_candidate import launcher, identity
from mac_prepare_manager_locale import packed
from manager_repair_release import (ARCHIVE, LAUNCHER, NATIVE_SOURCE,
                                    OLD_HELPER, SERVER, verify_release)


def envelope(payload, key, public):
    return canonical({'signed_payload': payload,
        'signature_algorithm': 'Ed25519',
        'signature_base64': base64.b64encode(key.sign(canonical(payload))).decode(),
        'public_key_base64': base64.b64encode(public).decode()})


class SignedLocaleRepairTests(unittest.TestCase):
    def test_exact_prior_releases_build_verifiable_scope(self):
        with zipfile.ZipFile(ROOT.parent / 'upload/RapBrain_Manager_Finish_Publication.zip') as publication:
            with zipfile.ZipFile(io.BytesIO(publication.read('manager-stable/update-3.zip'))) as app:
                old_launcher = app.read('app/launch_manager.py')
        with zipfile.ZipFile(ROOT.parent / 'upload/RapBrain_Manager_Postcommit_Publication.zip') as publication:
            with zipfile.ZipFile(io.BytesIO(publication.read('manager-postcommit/repair-3.zip'))) as repair:
                native = repair.read('app/RapBrainManagerNative.swift')
                old_helper = repair.read('helper.zip')
        self.assertEqual(digest(old_launcher), LAUNCHER)
        self.assertEqual(digest(native), NATIVE_SOURCE)
        self.assertEqual(digest(old_helper), OLD_HELPER)
        with zipfile.ZipFile(io.BytesIO(old_helper)) as original:
            helper_files = {name: original.read('helper/' + name)
                            for name in HELPER_FILES}
        helper_files['process_start_identity.py'] = identity(
            helper_files['process_start_identity.py'])
        helper = packed({'helper/' + name: helper_files[name] for name in HELPER_FILES})
        archive = packed({'app/RapBrainManagerNative.swift': native,
            'app/launch_manager.py': launcher(old_launcher), 'helper.zip': helper})

        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        pin = hashlib.sha256(public).hexdigest()
        now = int(time.time())
        validation = {'macos_copy_install': 'passed', 'rollback': 'passed',
                      'runtime': 'passed'}
        helper_signed = envelope({'schema': 'rapbrain-manager-helper-v1',
            'sequence': 4, 'issued_at': now - 1, 'expires_at': now + 86400,
            'production_install_authorized': True, 'validation': validation,
            'files': {name: digest(helper_files[name]) for name in HELPER_FILES},
            'archive_sha256': digest(helper), 'archive_bytes': len(helper)},
            key, public)
        files = {'app/RapBrainManagerNative.swift': native,
                 'app/launch_manager.py': launcher(old_launcher), 'helper.zip': helper}
        payload = {'schema': 'rapbrain-manager-repair-v1', 'sequence': 4,
            'issued_at': now - 1, 'expires_at': now + 86400,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': validation, 'baseline_launcher_sha256': LAUNCHER,
            'baseline_native_source_sha256': NATIVE_SOURCE,
            'baseline_helper_sha256': OLD_HELPER,
            'required_server_sha256': SERVER, 'archive_url': ARCHIVE,
            'archive_sha256': digest(archive), 'archive_bytes': len(archive),
            'files': {name: digest(files[name]) for name in files},
            'helper_manifest_base64': base64.b64encode(helper_signed).decode()}
        signed = envelope(payload, key, public)
        verified, actual, helper_manifest = verify_release(signed, archive,
                                                            pinned_key=pin, now=now)
        self.assertEqual(verified, payload)
        self.assertEqual(actual, files)
        self.assertEqual(helper_manifest, helper_signed)
        with self.assertRaises(Refused):
            verify_release(signed, archive + b' ', pinned_key=pin, now=now)
        with self.assertRaises(Refused):
            verify_release(signed, archive, pinned_key='0' * 64, now=now)
        payload['sequence'] = 3
        with self.assertRaises(Refused):
            verify_release(envelope(payload, key, public), archive,
                           pinned_key=pin, now=now)


if __name__ == '__main__':
    unittest.main()
