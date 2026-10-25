"""Syntax and no-side-effects import checks for macOS disposable rollback test."""
import ast
from pathlib import Path
import unittest
class Tests(unittest.TestCase):
    def test_parses(self):
        source=Path(__file__).with_name("mac_distinct_signed_rollback_check.py").read_text()
        ast.parse(source)
    def test_no_private_key_path(self):
        source=Path(__file__).with_name("mac_distinct_signed_rollback_check.py").read_text()
        self.assertNotIn("publisher_ed25519.key",source)
    def test_explicit_lab_only(self):
        source=Path(__file__).with_name("mac_distinct_signed_rollback_check.py").read_text()
        self.assertIn("LAB ONLY",source)
        self.assertIn("install_allowed",source)
if __name__=="__main__":unittest.main()
