import unittest
from strict_json import parse_signed_json,InvalidSignedJSON
class Tests(unittest.TestCase):
    def test_valid(self):self.assertEqual(parse_signed_json(b'{"a":{"b":3}}'),{"a":{"b":3}})
    def test_duplicate_top(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b'{"a":1,"a":2}')
    def test_duplicate_nested(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b'{"payload":{"install_allowed":false,"install_allowed":true}}')
    def test_nan(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b'{"a":NaN}')
    def test_infinity(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b'{"a":Infinity}')
    def test_invalid_utf8(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(bytes([255]))
    def test_oversize(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b" "*65537)
    def test_float(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b'{"size":1.5}')
    def test_exponent_overflow(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b'{"size":1e999}')
    def test_empty(self):
        with self.assertRaises(InvalidSignedJSON):parse_signed_json(b"")
if __name__=="__main__":unittest.main()
