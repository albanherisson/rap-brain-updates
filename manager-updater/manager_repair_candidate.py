"""Copy-only launcher repair after a terminal Manager update attempt.

The published capability and update-1 bytes remain immutable. A new signed
offline repair can use this candidate only after its Mac backup/rollback gate.
"""
import hashlib

from manager_version_label_candidate import prepare_launcher as version_label


BASELINE = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'
OLD_CHECK = "if code!=200 or json.loads(body).get('state')!='idle':raise RuntimeError('Manager update state invalid')"
NEW_CHECK = ("if code!=200 or json.loads(body).get('state') not in "
             "('idle','aborted','committed','rolled_back','restored_stopped','check_required'):"
             "raise RuntimeError('Manager update state invalid')")


def prepare_launcher(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('manager_repair_baseline_changed')
    source = version_label(raw).decode('utf-8')
    if source.count(OLD_CHECK) != 1:
        raise ValueError('manager_repair_smoke_anchor_changed')
    candidate = source.replace(OLD_CHECK, NEW_CHECK, 1).encode('utf-8')
    compile(candidate, 'launch_manager.py', 'exec')
    return candidate
