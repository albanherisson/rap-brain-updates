import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from manager_locale_identity_candidate import prepare


class LocaleIdentityCandidateTest(unittest.TestCase):
    def test_french_host_still_requests_c_locale_for_start_identity(self):
        source = Path(__file__).with_name('process_start_identity.py').read_bytes()
        namespace = {'__name__': 'candidate_process_identity'}
        exec(compile(prepare(source), 'process_start_identity.py', 'exec'), namespace)
        expected = 'Thu Nov  5 13:00:06 2026\n'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess(
                [], 0, expected, '')) as run:
            self.assertEqual(namespace['read_start'](34084),
                             '34084:Thu Nov 5 13:00:06 2026')
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
        self.assertEqual(run.call_args.kwargs['env']['LANG'], 'C')
        with self.assertRaises(ValueError):
            prepare(source + b' ')


if __name__ == '__main__':
    unittest.main()
