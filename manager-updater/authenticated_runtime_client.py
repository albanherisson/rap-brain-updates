"""Read-only local proof request; no process lifecycle or update operations."""
import http.client
import json
import re
import subprocess

from creative_release import Refused

KEYS = frozenset(('parent_pid', 'worker_pid', 'audio_pid',
                  'worker_script_matches'))


def parse_response(raw, *, expected_parent_pid):
    if type(raw) is not bytes or len(raw) > 4096:
        raise Refused('runtime_proof_oversize')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused('runtime_proof_duplicate_field')
            result[key] = value
        return result

    try:
        report = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise Refused('runtime_proof_invalid_json') from exc
    if (type(report) is not dict or report.keys() != KEYS or
            type(expected_parent_pid) is not int or expected_parent_pid < 2 or
            type(report['parent_pid']) is not int or
            report['parent_pid'] != expected_parent_pid or
            type(report['worker_pid']) is not int or
            report['worker_pid'] < 2 or report['worker_pid'] == expected_parent_pid or
            report['audio_pid'] is not None or
            report['worker_script_matches'] is not True):
        raise Refused('runtime_process_identity_mismatch')
    return report


def assert_owned_listener(port, expected_parent_pid):
    """Refuse to disclose the private token to an unrelated loopback listener."""
    if (type(port) is not int or not 1 <= port <= 65535 or
            type(expected_parent_pid) is not int or expected_parent_pid < 2):
        raise Refused('listener_identity_invalid')
    try:
        result = subprocess.run(['/usr/sbin/lsof', '-nP', f'-iTCP:{port}',
                                 '-sTCP:LISTEN', '-Fp'],
                                capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('listener_identity_unavailable') from exc
    lines = result.stdout.splitlines()
    pids = [int(line[1:]) for line in lines
            if re.fullmatch(r'p[0-9]+', line)]
    if (result.stderr or len(result.stdout) > 4096 or not lines or
            any(not re.fullmatch(r'p[0-9]+', line) for line in lines) or
            len(pids) != 1 or pids[0] != expected_parent_pid):
        raise Refused('listener_not_owned')
    return True


def read_runtime_proof(port, token, *, expected_parent_pid):
    if (type(port) is not int or not 1 <= port <= 65535 or
            type(token) is not str or not re.fullmatch(r'[0-9a-f]{64}', token)):
        raise Refused('runtime_request_invalid')
    assert_owned_listener(port, expected_parent_pid)
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', '/api/manager-update-proof',
                           headers={'X-RB-Update-Token': token})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
            raise Refused('runtime_proof_not_authenticated')
        report = parse_response(response.read(4097), expected_parent_pid=expected_parent_pid)
        assert_owned_listener(port, expected_parent_pid)
        return report
    except (OSError, http.client.HTTPException) as exc:
        raise Refused('runtime_proof_unavailable') from exc
    finally:
        connection.close()
