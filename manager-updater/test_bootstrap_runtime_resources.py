"""Verify the precise local runtime set before it can enter a signed bundle."""
import ast
from pathlib import Path
import unittest

from bootstrap_runtime_resources import RUNTIME_FILES, verify_runtime_resources
from creative_release import Refused, digest


ROOT = Path(__file__).resolve().parent


class RuntimeResourceTests(unittest.TestCase):
    def setUp(self):
        self.members = {name: (ROOT / name).read_bytes() for name in RUNTIME_FILES}
        self.hashes = {name: digest(raw) for name, raw in self.members.items()}

    def test_exact_transitive_installer_runtime_is_present_and_compiles(self):
        self.assertTrue(verify_runtime_resources(self.members, self.hashes))
        found = set()
        pending = ['creative_install_controller.py']
        while pending:
            name = pending.pop()
            if name in found:
                continue
            found.add(name)
            tree = ast.parse(self.members[name])
            imports = [node.module for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom) and node.module]
            imports += [alias.name for node in ast.walk(tree)
                        if isinstance(node, ast.Import) for alias in node.names]
            for module in imports:
                resource = module + '.py'
                if (ROOT / resource).is_file():
                    pending.append(resource)
        self.assertEqual(found, set(RUNTIME_FILES) - {'verify_ed25519.swift'})

    def test_missing_or_extra_member_refuses(self):
        for changed in ({k: v for k, v in self.members.items()
                         if k != 'verify_ed25519.swift'},
                        dict(self.members, unexpected=b'x')):
            with self.assertRaisesRegex(Refused, 'bootstrap_runtime_inventory'):
                verify_runtime_resources(changed, self.hashes)

    def test_tampered_resource_refuses(self):
        changed = dict(self.members)
        changed['creative_install_controller.py'] += b'\n# tampered\n'
        with self.assertRaisesRegex(Refused, 'bootstrap_runtime_integrity'):
            verify_runtime_resources(changed, self.hashes)


if __name__ == '__main__':
    unittest.main()
