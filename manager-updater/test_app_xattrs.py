"""macOS xattr commands preserve arbitrary signature bytes via hex mode."""
import subprocess
import unittest
from unittest.mock import patch

from app_xattrs import get_attr, list_attrs, set_attr
from creative_release import Refused


class AppXattrTests(unittest.TestCase):
    def test_mac_binary_attribute_round_trip_uses_system_hex_mode(self):
        calls = []
        responses = [b'com.apple.cs.CodeDirectory\n', b'00 ff 10\n', b'']
        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, responses.pop(0), b'')
        with (patch('app_xattrs.sys.platform', 'darwin'),
              patch('app_xattrs.subprocess.run', side_effect=runner)):
            self.assertEqual(list_attrs('/tmp/fixture'), ['com.apple.cs.CodeDirectory'])
            self.assertEqual(get_attr('/tmp/fixture', 'com.apple.cs.CodeDirectory'),
                             b'\x00\xff\x10')
            set_attr('/tmp/copy', 'com.apple.cs.CodeDirectory', b'\x00\xff\x10')
        self.assertEqual(calls[1][:3], ['/usr/bin/xattr', '-px',
                                        'com.apple.cs.CodeDirectory'])
        self.assertEqual(calls[2][1:4], ['-wx', 'com.apple.cs.CodeDirectory',
                                         '00ff10'])

    def test_mac_xattr_failure_refuses_without_silent_metadata_loss(self):
        with (patch('app_xattrs.sys.platform', 'darwin'),
              patch('app_xattrs.subprocess.run', return_value=
                    subprocess.CompletedProcess([], 1, b'', b'failed'))):
            with self.assertRaisesRegex(Refused, 'app_xattr_tool_refused'):
                list_attrs('/tmp/fixture')


if __name__ == '__main__':
    unittest.main()
