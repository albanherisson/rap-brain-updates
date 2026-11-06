"""Synthetic Manager release verifier gate for a server-only Decoder payload."""
import base64
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'manager-updater'))
from creative_release import canonical, digest, Refused
from manager_update_release import verify_archive, verify_manifest
from manager_update_rehearsal import rehearse_on_copy

SERVER=Path(__file__).with_name('server.py')
BASELINE='e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'


class ServerOnlyReleaseCompatibility(unittest.TestCase):
 def setUp(self):
  self.payload=SERVER.read_bytes()
  self.key=Ed25519PrivateKey.generate()  # Disposable test key, never a publisher key.
  self.public=self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
  stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w') as archive:archive.writestr('server.py',self.payload)
  self.archive=stream.getvalue()
  now=int(time.time())
  self.signed={'schema':'rapbrain-manager-production-v1','sequence':4,
   'issued_at':now-1,'expires_at':now+3600,
   'production_install_authorized':True,'data_migrations':[],
   'validation':{'macos_copy_install':'passed','rollback':'passed','runtime':'passed'},
   'files':[{'path':'server.py','baseline_sha256':BASELINE,
     'payload_sha256':digest(self.payload)}],
   'required_server_sha256':BASELINE,
   'archive_url':('https://raw.githubusercontent.com/albanherisson/'
    'rap-brain-updates/main/manager-stable/decoder-test.zip'),
   'archive_sha256':digest(self.archive),'archive_bytes':len(self.archive)}

 def envelope(self):
  return canonical({'signed_payload':self.signed,'signature_algorithm':'Ed25519',
   'signature_base64':base64.b64encode(self.key.sign(canonical(self.signed))).decode(),
   'public_key_base64':base64.b64encode(self.public).decode()})

 def test_existing_manager_verifier_accepts_only_candidate_server(self):
  manifest=verify_manifest(self.envelope(),minimum_sequence=3,
   pinned_key=digest(self.public))
  self.assertEqual({'server.py':self.payload},verify_archive(self.archive,manifest))
  self.assertEqual(BASELINE,manifest['required_server_sha256'])

 def test_data_path_and_extra_archive_member_are_refused(self):
  self.signed['files'][0]['path']='data/rapbrain.sqlite3'
  with self.assertRaises(Refused):
   verify_manifest(self.envelope(),minimum_sequence=3,pinned_key=digest(self.public))
  self.signed['files'][0]['path']='server.py'
  manifest=verify_manifest(self.envelope(),minimum_sequence=3,
   pinned_key=digest(self.public))
  extra=io.BytesIO()
  with zipfile.ZipFile(extra,'w') as archive:
   archive.writestr('server.py',self.payload)
   archive.writestr('data/ollama_model.json',b'{}')
  manifest['archive_sha256']=digest(extra.getvalue())
  manifest['archive_bytes']=len(extra.getvalue())
  with self.assertRaises(Refused):verify_archive(extra.getvalue(),manifest)

 def test_candidate_server_swap_and_exact_rollback_on_disposable_copy(self):
  with tempfile.TemporaryDirectory(prefix='decoder-manager-copy-') as temp:
   root=Path(temp).resolve()
   source=root/'rap-brain'
   (source/'data').mkdir(parents=True)
   original=b'original synthetic server\n'
   (source/'server.py').write_bytes(original)
   database=source/'data/rapbrain.sqlite3'
   config=source/'data/ollama_model.json'
   database.write_bytes(b'synthetic SQLite placeholder; never opened')
   config.write_bytes(b'{"model":"synthetic"}')
   resources=root/'Manager.app/Contents/Resources'
   resources.mkdir(parents=True)
   launcher=resources/'launch_manager.py'
   launcher.write_bytes(b'original synthetic launcher\n')
   self.signed['required_server_sha256']=digest(original)
   self.signed['files'][0]['baseline_sha256']=digest(original)
   result=rehearse_on_copy(source,launcher,root/'private-state',
    self.envelope(),self.archive,pinned_key=digest(self.public))
   self.assertEqual('copy_rehearsal_passed',result['state'])
   self.assertEqual(original,(source/'server.py').read_bytes())
   self.assertEqual(b'original synthetic launcher\n',launcher.read_bytes())
   self.assertEqual(b'synthetic SQLite placeholder; never opened',database.read_bytes())
   self.assertEqual(b'{"model":"synthetic"}',config.read_bytes())


if __name__=='__main__':unittest.main()
