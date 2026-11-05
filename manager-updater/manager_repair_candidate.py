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
OLD_HANDOFF = 'handoff=prepare_handoff(rap_dir,Path(__file__).resolve(),secure_state,'
OLD_EXIT = 'if handle_manager_update_request(root,rap_dir,backup_dir,supervisor_state):return 0'
NEW_EXIT = 'if handle_manager_update_request(root,rap_dir,backup_dir,supervisor_state):return 42'
NEW_HANDOFF = '''stable_launcher=(Path.home()/'Downloads'/'RapBrainManager_App_Beta14'/
            'Rap Brain Manager Beta 14.app'/'Contents'/'Resources'/'launch_manager.py')
        running_launcher=Path(__file__).resolve()
        if (stable_launcher.is_symlink() or not stable_launcher.is_file() or
                hashlib.sha256(stable_launcher.read_bytes()).digest()!=
                hashlib.sha256(running_launcher.read_bytes()).digest()):
            raise RuntimeError('stable_manager_app_changed')
        handoff=prepare_handoff(rap_dir,stable_launcher,secure_state,'''


def prepare_launcher(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('manager_repair_baseline_changed')
    source = version_label(raw).decode('utf-8')
    if source.count(OLD_CHECK) != 1:
        raise ValueError('manager_repair_smoke_anchor_changed')
    if source.count(OLD_HANDOFF) != 1:
        raise ValueError('manager_repair_handoff_anchor_changed')
    if source.count(OLD_EXIT) != 1:
        raise ValueError('manager_repair_exit_anchor_changed')
    source = source.replace(OLD_CHECK, NEW_CHECK, 1)
    source = source.replace(OLD_HANDOFF, NEW_HANDOFF, 1)
    candidate = source.replace(OLD_EXIT, NEW_EXIT, 1).encode('utf-8')
    compile(candidate, 'launch_manager.py', 'exec')
    return candidate
