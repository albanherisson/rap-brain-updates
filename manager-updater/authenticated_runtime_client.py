"""Read-only local proof request; no process lifecycle or update operations."""
import http.client
import json
import re

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


def read_runtime_proof(port, token, *, expected_parent_pid):
    if (type(port) is not int or not 1 <= port <= 65535 or
            type(token) is not str or not re.fullmatch(r'[0-9a-f]{64}', token)):
        raise Refused('runtime_request_invalid')
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', '/api/manager-update-proof',
                           headers={'X-RB-Update-Token': token})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
            raise Refused('runtime_proof_not_authenticated')
        return parse_response(response.read(4097), expected_parent_pid=expected_parent_pid)
    except (OSError, http.client.HTTPException) as exc:
        raise Refused('runtime_proof_unavailable') from exc
    finally:
        connection.close()
