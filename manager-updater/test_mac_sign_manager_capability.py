"""The Mac publisher emits public signatures without exporting its seed."""
import base64
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (Encoding, PublicFormat,
    PrivateFormat, NoEncryption)

from creative_release import digest
from manager_capability_release import verify_release
from manager_helper_bundle import assemble as assemble_helper
import manager_capability_release as release
import mac_sign_manager_capability as publisher


class PublisherTests(unittest.TestCase):
    def test_public_package_has_two_signatures_and_no_private_key(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            home = Path(temporary).resolve()
            resources = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
                'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources')
            resources.mkdir(parents=True)
            source = home / 'Downloads' / 'rap-brain'
            source.mkdir()
            original = {'launch': b'# old launcher\n',
                        'dashboard': b'<html>old</html>',
                        'server': b'# guarded fixture\n'}
            (resources / 'launch_manager.py').write_bytes(original['launch'])
            (resources / 'dashboard_beta14.html').write_bytes(original['dashboard'])
            (source / 'server.py').write_bytes(original['server'])
            (source / 'data').mkdir()
            (source / 'data' / 'rapbrain.sqlite3').write_bytes(b'never read')
            key = Ed25519PrivateKey.generate()
            seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
            key_path = home / 'manager.key'
            key_path.write_bytes(seed)
            key_path.chmod(0o600)
            pin = digest(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
            helper, _ = assemble_helper()
            members = {name: (helper if name == 'helper.zip' else
                       b'<html>candidate</html>' if name.endswith('.html') else
                       b'# candidate\n') for name in
                       sorted(['app/' + name for name in publisher.APP_FILES] +
                              ['helper.zip'])}
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, value in members.items():
                    info = zipfile.ZipInfo(name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100600 << 16
                    archive.writestr(info, value)
            candidate = buffer.getvalue()
            pins = {'LAUNCHER_SHA256': digest(original['launch']),
                    'DASHBOARD_SHA256': digest(original['dashboard']),
                    'SERVER_SHA256': digest(original['server'])}
            with patch.object(publisher, 'CANDIDATE_SHA256', digest(candidate)), \
                 patch.object(publisher, 'MANAGER_PIN', pin), \
                 patch.object(publisher.subprocess, 'run', return_value=Mock(returncode=0)):
                active = [patch.object(publisher, name, value) for name, value in pins.items()]
                active += [patch.object(release, name, value) for name, value in pins.items()]
                with active[0], active[1], active[2], active[3], active[4], active[5]:
                    package = publisher.prepare(home, candidate, key_path,
                                                now=1_800_000_000)
                    with zipfile.ZipFile(io.BytesIO(package)) as archive:
                        self.assertEqual(archive.namelist(), [
                            'manager-capability/capability-1.zip',
                            'manager-capability/manifest.json'])
                        signed, files, helper_signed = verify_release(
                            archive.read('manager-capability/manifest.json'),
                            archive.read('manager-capability/capability-1.zip'),
                            pinned_key=pin, now=1_800_000_000)
                    self.assertEqual(signed['archive_sha256'], digest(candidate))
                    self.assertEqual(files, members)
                    self.assertNotIn(seed, package)
                    self.assertEqual((source / 'data' / 'rapbrain.sqlite3').read_bytes(),
                                     b'never read')


if __name__ == '__main__':
    unittest.main()
