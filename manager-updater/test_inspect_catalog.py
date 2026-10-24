import json
import unittest
from inspect_catalog import Reject, check_catalog_bytes

VALID = {"payload": {
 "schema":1, "channel":"manager-stable", "product":"Rap Brain Manager",
 "version":"1.0.6", "install_allowed":False,
 "archive":{"filename":"Rap_Brain_Manager_1.0.6.zip","size":100,"sha256":"a"*64,
 "url":"https://github.com/albanherisson/rap-brain-updates/releases/download/v1.0.6/Rap_Brain_Manager_1.0.6.zip"}
},"signature":"A"*86+"=="}

def check(payload):
    return check_catalog_bytes(json.dumps(payload).encode(), verifier=lambda sig, b: None)

class Tests(unittest.TestCase):
    def test_valid_structure(self):
        self.assertEqual(check(VALID)["version"], "1.0.6")
    def test_install_disallowed(self):
        v=json.loads(json.dumps(VALID));v["payload"]["install_allowed"]=True
        with self.assertRaises(Reject): check(v)
    def test_wrong_channel(self):
        v=json.loads(json.dumps(VALID));v["payload"]["channel"]="rapbrain"
        with self.assertRaises(Reject): check(v)
    def test_key_injection(self):
        v=json.loads(json.dumps(VALID));v["public_key"]="attacker"
        with self.assertRaises(Reject): check(v)
    def test_http_rejected(self):
        v=json.loads(json.dumps(VALID));v["payload"]["archive"]["url"]=v["payload"]["archive"]["url"].replace("https:", "http:")
        with self.assertRaises(Reject): check(v)
    def test_unsigned_rejected(self):
        v=json.loads(json.dumps(VALID));v["signature"]=""
        with self.assertRaises(Reject): check(v)
    def test_unknown_field(self):
        v=json.loads(json.dumps(VALID));v["payload"]["delete_data"]=True
        with self.assertRaises(Reject): check(v)

if __name__=="__main__": unittest.main()
