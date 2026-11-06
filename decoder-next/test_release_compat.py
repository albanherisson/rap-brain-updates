"""Synthetic Manager release verifier gate for a server-only Decoder payload."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'manager-updater'))
from creative_release import canonical, digest, Refused
from manager_update_release import verify_archive, verify_manifest
from manager_update_rehearsal import rehearse_on_copy

spec=importlib.util.spec_from_file_location('mac_decoder_publisher',
 Path(__file__).with_name('mac_sign_decoder_release.py'))
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
spec=importlib.util.spec_from_file_location('mac_finderinfo_repair',
 Path(__file__).with_name('mac_repair_manager_finderinfo.py'))
finder_repair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(finder_repair)

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

 def test_decoder_publisher_rehearses_copies_and_packages_server_only(self):
  with tempfile.TemporaryDirectory(prefix='decoder-publisher-test-') as temp:
   home=Path(temp)
   source=home/'Downloads/rap-brain'
   (source/'data').mkdir(parents=True)
   original=b'synthetic installed server\n'
   (source/'server.py').write_bytes(original)
   database=source/'data/rapbrain.sqlite3'
   config=source/'data/ollama_model.json'
   database.write_bytes(b'untouched synthetic database')
   config.write_bytes(b'{"model":"untouched"}')
   app=home/'Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app'
   (app/'Contents/Resources').mkdir(parents=True)
   (app/'Contents/Resources/launch_manager.py').write_bytes(b'synthetic app')
   state=home/'Downloads/RapBrainManagerBackups/secure-update'
   state.mkdir(parents=True)
   (state/'manager-accepted.json').write_text('{"sequence":3}')
   def runner(args,**kwargs):
    if args[0]=='/usr/bin/ditto':shutil.copytree(args[1],args[2])
    return subprocess.CompletedProcess(args,0)
   rehearsal=lambda *args:publisher.rehearse_on_mac_copies(*args,runner=runner)
   signer=lambda path,message:(self.public,self.key.sign(message))
   with patch.object(publisher,'BASELINE_SHA256',digest(original)):
    public_zip=publisher.prepare(home,self.payload,signer=signer,
                                 rehearsal=rehearsal,now=int(time.time()))
   with zipfile.ZipFile(io.BytesIO(public_zip)) as outer:
    self.assertEqual(['manager-stable/manifest.json','manager-stable/update-4.zip'],
                     outer.namelist())
    manifest=verify_manifest(outer.read('manager-stable/manifest.json'),
                             minimum_sequence=3,pinned_key=digest(self.public))
    self.assertEqual(4,manifest['sequence'])
    self.assertEqual([],manifest['data_migrations'])
    self.assertEqual({'server.py':self.payload},
                     verify_archive(outer.read('manager-stable/update-4.zip'),manifest))
    self.assertNotIn(b'untouched synthetic database',public_zip)
   self.assertEqual(original,(source/'server.py').read_bytes())
   self.assertEqual(b'untouched synthetic database',database.read_bytes())
   self.assertEqual(b'{"model":"untouched"}',config.read_bytes())
   self.assertEqual(b'synthetic app',(app/'Contents/Resources/launch_manager.py').read_bytes())

 def test_decoder_publisher_refuses_wrong_active_server_before_rehearsal(self):
  with tempfile.TemporaryDirectory(prefix='decoder-publisher-refuse-') as temp:
   home=Path(temp)
   state=home/'Downloads/RapBrainManagerBackups/secure-update'
   state.mkdir(parents=True)
   (state/'manager-accepted.json').write_text('{"sequence":3}')
   source=home/'Downloads/rap-brain'
   source.mkdir(parents=True)
   (source/'server.py').write_bytes(b'wrong baseline')
   called=[]
   with self.assertRaisesRegex(ValueError,'code_baseline_mismatch'):
    publisher.prepare(home,self.payload,signer=lambda *args:called.append('sign'),
                      rehearsal=lambda *args:called.append('rehearse'))
   self.assertEqual([],called)

 def test_decoder_publisher_requires_pinned_private_key_and_private_permissions(self):
  with tempfile.TemporaryDirectory(prefix='decoder-key-test-') as temp:
   key=Path(temp)/'publisher_ed25519.key'
   key.write_bytes(self.key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()))
   key.chmod(0o600)
   with self.assertRaisesRegex(ValueError,'publisher_identity_mismatch'):
    publisher.sign(key,b'synthetic manifest')
   with patch.object(publisher,'PUBLISHER_PIN',digest(self.public)):
    public,signature=publisher.sign(key,b'synthetic manifest')
    self.assertEqual(self.public,public)
    self.key.public_key().verify(signature,b'synthetic manifest')
    key.chmod(0o644)
    with self.assertRaisesRegex(ValueError,'publisher_private_key_unsafe'):
     publisher.sign(key,b'synthetic manifest')

 def test_finderinfo_repair_preserves_private_backup_and_only_removes_root_attr(self):
  with tempfile.TemporaryDirectory(prefix='finderinfo-repair-test-') as temp:
   home=Path(temp)
   app=home/finder_repair.APP_RELATIVE
   (app/'Contents/Resources').mkdir(parents=True)
   launcher=app/'Contents/Resources/launch_manager.py'
   launcher.write_bytes(b'unchanged signed code')
   (home/'Downloads/RapBrainManagerBackups').mkdir()
   value='ab'*32
   attributes={str(app):value}
   def fake_run(args,**kwargs):
    if args[0]=='/usr/bin/ditto':
     shutil.copytree(args[1],args[2]);attributes[args[2]]=attributes.get(args[1])
    elif args[0]=='/usr/bin/xattr':
     if args[1]=='-px':
      found=attributes.get(args[3])
      return subprocess.CompletedProcess(args,0 if found else 1,
       (found or '').encode(),b'')
     if args[1]=='-d':attributes.pop(args[3],None)
     if args[1]=='-wx':attributes[args[4]]=args[3]
    elif args[0]=='/usr/bin/codesign' and attributes.get(args[-1]):
     return subprocess.CompletedProcess(args,1,b'',
      b'Disallowed xattr com.apple.FinderInfo found')
    return subprocess.CompletedProcess(args,0,b'',b'')
   with patch.object(finder_repair,'run',side_effect=fake_run), \
        patch.object(finder_repair.sys,'platform','darwin'):
    result=finder_repair.repair(home)
   self.assertEqual('repaired',result['state'])
   self.assertEqual(b'unchanged signed code',launcher.read_bytes())
   self.assertNotIn(str(app),attributes)
   backup=Path(result['backup'])
   self.assertEqual(value,attributes[str(backup/'original.app')])
   self.assertEqual(value+'\n',(backup/'finderinfo.hex').read_text())

 def test_finderinfo_repair_refuses_unrelated_signature_failure(self):
  with tempfile.TemporaryDirectory(prefix='finderinfo-other-failure-') as temp:
   home=Path(temp)
   app=home/finder_repair.APP_RELATIVE
   (app/'Contents/Resources').mkdir(parents=True)
   (app/'Contents/Resources/launch_manager.py').write_bytes(b'code')
   (home/'Downloads/RapBrainManagerBackups').mkdir()
   def fake_run(args,**kwargs):
    if args[0]=='/usr/bin/xattr':
     return subprocess.CompletedProcess(args,0,b'ab'*32,b'')
    return subprocess.CompletedProcess(args,1,b'',b'code object not signed')
   with patch.object(finder_repair,'run',side_effect=fake_run), \
        patch.object(finder_repair.sys,'platform','darwin'):
    with self.assertRaisesRegex(ValueError,'signature_failure_not_only_finderinfo'):
     finder_repair.repair(home)
   self.assertEqual(b'code',(app/'Contents/Resources/launch_manager.py').read_bytes())


if __name__=='__main__':unittest.main()
