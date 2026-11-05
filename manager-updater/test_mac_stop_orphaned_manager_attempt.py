"""Reject unrelated processes before any authenticated stop request."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import mac_stop_orphaned_manager_attempt as rescue


class OrphanIdentityTest(unittest.TestCase):
    def setUp(self):
        self.source = Path('/Users/gns/Downloads/rap-brain')
        server = str(self.source / 'server.py')
        self.rows = {
            34084: (1, 34084, os.getuid(), '/usr/bin/python -u ' + server),
            34086: (34084, 34084, os.getuid(), '/usr/bin/python ' + server + ' --worker')}

    def test_exact_orphan_group(self):
        rescue.owned_orphan(self.rows, 34084, 34086, self.source)
        for rows in (
            self.rows | {34084: (42, *self.rows[34084][1:])},
            self.rows | {34086: (1, *self.rows[34086][1:])},
            self.rows | {42: (1, 34084, os.getuid(), 'other')},
            self.rows | {34086: (*self.rows[34086][:3], '/tmp/other --worker')},
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                rescue.owned_orphan(rows, 34084, 34086, self.source)

    def test_only_matching_private_ticket_yields_token(self):
        token, ticket = 'a' * 64, 'b' * 64
        output = ('python -u server.py RB_UPDATE_PROBE_TOKEN=' + token +
                  ' RB_UPDATE_LAUNCH_TICKET=' + ticket)
        with patch.object(rescue, 'ps', return_value=output):
            self.assertEqual(rescue.process_secrets(34084,
                             (ticket + '\n').encode()), (token, ticket))
            with self.assertRaises(ValueError):
                rescue.process_secrets(34084, b'c' * 64 + b'\n')

    def test_parse_requires_numeric_process_fields(self):
        sample = '34084 1 34084 501 /usr/bin/python -u /path/server.py\n'
        with patch.object(rescue, 'ps', return_value=sample):
            self.assertEqual(rescue.process_rows()[34084][0:3], (1, 34084, 501))
        with patch.object(rescue, 'ps', return_value='34084 ? 34084 501 x\n'):
            with self.assertRaises(ValueError):
                rescue.process_rows()


if __name__ == '__main__':
    unittest.main()
