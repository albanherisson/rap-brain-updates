import subprocess
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mac_manager_page_request import PageUnverified, URL, advance_page_task, open_page, parse_page_task


class ManagerPageTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "schema": "rapbrain-remote-task-v7", "id": "page-test",
            "action": "manager_open_page", "expected_server_sha256": "a" * 64,
            "expires_at": int(time.time()) + 3600, "authorization_commit": "b" * 40,
        }

    def test_task_requires_private_authorization_and_fixed_action(self):
        request = parse_page_task(self.task)
        self.assertEqual(request["schema"], "rapbrain-manager-page-v1")
        authorize = Mock(side_effect=ValueError("refused"))
        open_ui = Mock()
        with self.assertRaisesRegex(ValueError, "refused"):
            advance_page_task(self.task, authorize=authorize, open_ui=open_ui)
        open_ui.assert_not_called()
        for field, value in (("action", "other"), ("authorization_commit", "bad"),
                             ("expires_at", int(time.time()) - 1)):
            bad = self.task | {field: value}
            with self.assertRaises(ValueError):
                parse_page_task(bad)
        with self.assertRaises(ValueError):
            parse_page_task(self.task | {"url": "https://example.com"})

    def test_opens_exact_local_url_only_after_server_health_and_checks_front_document(self):
        call = Mock(side_effect=[
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=0, stdout=URL + "\n"),
        ])
        ready = Mock(return_value=True)
        outcome = open_page(Path("/tmp/rapbrain-test"), parse_page_task(self.task),
                            start=Mock(return_value="already_running"), ready=ready,
                            call=call, http=Mock())
        self.assertEqual(outcome, {"state": "opened", "server": "already_running",
                                   "page_url_verified": True})
        self.assertEqual(call.call_args_list[0].args[0],
                         ["/usr/bin/open", "-a", "Safari", URL])
        self.assertEqual(call.call_args_list[1].args[0][-1],
                         'tell application "Safari" to get URL of front document')

    def test_refuses_unverified_page_or_server(self):
        request = parse_page_task(self.task)
        opener = Mock(return_value=SimpleNamespace(returncode=1, stdout=""))
        with self.assertRaisesRegex(ValueError, "open_refused"):
            open_page(Path("/tmp/rapbrain-test"), request, start=Mock(return_value="started"),
                      ready=Mock(return_value=True), call=opener)
        opener.assert_called_once()
        with self.assertRaisesRegex(ValueError, "server_unverified"):
            open_page(Path("/tmp/rapbrain-test"), request, start=Mock(return_value="started"),
                      ready=Mock(return_value=False), call=Mock())

    def test_unverified_url_is_distinct_from_an_open_refusal(self):
        call = Mock(side_effect=[
            SimpleNamespace(returncode=0, stdout=""),
            subprocess.TimeoutExpired(cmd=["/usr/bin/osascript"], timeout=5),
        ])
        with self.assertRaisesRegex(PageUnverified, "url_unverified"):
            open_page(Path("/tmp/rapbrain-test"), parse_page_task(self.task),
                      start=Mock(return_value="already_running"), ready=Mock(return_value=True),
                      call=call, clock=Mock(side_effect=[0, 16]), sleep=Mock())
        self.assertEqual(call.call_args_list[0].args[0],
                         ["/usr/bin/open", "-a", "Safari", URL])


if __name__ == "__main__":
    unittest.main()
