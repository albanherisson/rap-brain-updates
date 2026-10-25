import contextlib
import hashlib
import importlib.util
import io
import tempfile
from pathlib import Path
import unittest
import zipfile

PATH=Path(__file__).with_name("mac_prepare_distinct_unsigned_lab.py")
spec=importlib.util.spec_from_file_location("prepare_unsigned_lab",PATH)
lab=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

class Tests(unittest.TestCase):
    def test_distinct_file_and_disabled_install(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"isolated-dryrun"
            src=root/"Rap Brain Manager - Isolated Copy.app/Contents/Resources/manager.py"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"original")
            original_root,original_source,original_out,original_sha=lab.ROOT,lab.SOURCE,lab.LAB,lab.OLD_SHA
            try:
                lab.ROOT=root
                lab.SOURCE=src
                lab.LAB=root/"distinct-unsigned-lab-1.0.6"
                lab.OLD_SHA=hashlib.sha256(b"original").hexdigest()
                with contextlib.redirect_stdout(io.StringIO()):
                    lab.main()
                import json
                payload=json.loads((lab.LAB/"canonical_payload.json").read_bytes())
                self.assertIs(payload["install_allowed"],False)
                archive=lab.LAB/lab.NAME
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),payload["archive"]["sha256"])
                with zipfile.ZipFile(archive) as z:
                    self.assertEqual(z.namelist(),["Contents/Resources/manager.py"])
                    self.assertNotEqual(z.read(z.namelist()[0]),b"original")
                self.assertEqual(src.read_bytes(),b"original")
                with self.assertRaises(ValueError):lab.main()
            finally:
                lab.ROOT,lab.SOURCE,lab.LAB,lab.OLD_SHA=original_root,original_source,original_out,original_sha
    def test_marker(self):
        self.assertTrue(lab.MARKER.startswith(b"\n# RAP_BRAIN_DISTINCT"))
if __name__=="__main__": unittest.main()
