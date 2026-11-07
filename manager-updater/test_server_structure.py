import unittest
from mac_server_structure import structural_text


class RedactionTests(unittest.TestCase):
    def test_literals_comments_and_docstrings_never_leave_mac(self):
        source = b'''# COMMENT_SECRET
"""MODULE_SECRET"""
TOKEN = "TOP_SECRET"
NUMBER = 123456789
BYTES = b"BYTES_SECRET"
def worker():
    """DOC_SECRET"""
    x = f"FSTRING_SECRET {TOKEN}"
    return {"status": "running", "password": "PASSWORD_SECRET"}
'''
        output = structural_text(source)
        for value in ['COMMENT_SECRET', 'MODULE_SECRET', 'TOP_SECRET', '123456789',
                      'BYTES_SECRET', 'DOC_SECRET', 'FSTRING_SECRET', 'PASSWORD_SECRET']:
            self.assertNotIn(value, output)
        self.assertIn("'status': 'running'", output)
        self.assertIn('def worker()', output)

    def test_only_text_analysis_no_import(self):
        output = structural_text(b'raise RuntimeError("MUST_NOT_EXECUTE")\n')
        self.assertIn('raise RuntimeError', output)
        self.assertNotIn('MUST_NOT_EXECUTE', output)


if __name__ == '__main__':
    unittest.main()
