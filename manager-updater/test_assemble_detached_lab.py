import base64,hashlib,json,unittest
from mac_assemble_detached_lab import assemble
ZIP=b"zip-lab"
NAME="Rap_Brain_Manager_1.0.6_lab_distinct.zip"
PAYLOAD={
"schema":1,"channel":"manager-stable","product":"Rap Brain Manager",
"version":"1.0.6","install_allowed":False,
"archive":{"filename":NAME,"size":len(ZIP),"sha256":hashlib.sha256(ZIP).hexdigest(),
"url":"https://github.com/albanherisson/rap-brain-updates/releases/download/lab-1.0.6/"+NAME}}
SIGNATURE=base64.b64encode(bytes(64)).decode()
def canonical(d):return json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
class Tests(unittest.TestCase):
 def test_valid(self):
  result=assemble(canonical(PAYLOAD),SIGNATURE,ZIP,NAME)
  self.assertFalse(result["payload"]["install_allowed"])
 def test_refuses_noncanonical(self):
  with self.assertRaises(ValueError):assemble(json.dumps(PAYLOAD).encode(),SIGNATURE,ZIP,NAME)
 def test_refuses_installable(self):
  d=json.loads(json.dumps(PAYLOAD));d["install_allowed"]=True
  with self.assertRaises(ValueError):assemble(canonical(d),SIGNATURE,ZIP,NAME)
 def test_refuses_changed_zip(self):
  with self.assertRaises(ValueError):assemble(canonical(PAYLOAD),SIGNATURE,ZIP+b"!",NAME)
 def test_refuses_wrong_zip_name(self):
  with self.assertRaises(ValueError):assemble(canonical(PAYLOAD),SIGNATURE,ZIP,"evil.zip")
 def test_refuses_invalid_signature(self):
  with self.assertRaises(ValueError):assemble(canonical(PAYLOAD),"not-a-signature",ZIP,NAME)
 def test_refuses_unsigned(self):
  with self.assertRaises(ValueError):assemble(canonical(PAYLOAD),"",ZIP,NAME)
 def test_refuses_duplicate_metadata(self):
  raw=canonical(PAYLOAD).replace(b'"install_allowed":false',b'"install_allowed":false,"install_allowed":true')
  with self.assertRaises(ValueError):assemble(raw,SIGNATURE,ZIP,NAME)
if __name__=="__main__":unittest.main()
