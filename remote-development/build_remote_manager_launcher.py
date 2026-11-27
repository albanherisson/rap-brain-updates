"""Build the launcher's remote entry point from the exact installed baseline."""

import hashlib
from pathlib import Path


LAUNCHER_BASELINE_SHA = "dac886a0f3a311b8067c5d9a44a438fc19f6c4eb1ceb69b7c4ffd3dabf9b12ac"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("remote_launcher_anchor_changed")
    return source.replace(old, new, 1)


def build_launcher(baseline, protocol, adapter):
    if hashlib.sha256(baseline).hexdigest() != LAUNCHER_BASELINE_SHA:
        raise ValueError("remote_launcher_baseline_changed")
    source = baseline.decode("utf-8")
    source = replace_once(source, """def handle_manager_update_request(root, rap_dir, backup_dir, state):
    req=root/'manager-update-request.json'
    if not req.exists():return False
    out=root/'manager-update-result.json'
    try:
        if req.is_symlink() or req.stat().st_size>1024:raise RuntimeError('invalid_manager_request')
        data=json.loads(req.read_bytes())
        req.unlink()
        if data!={'action':'install-signed-manager'}:raise RuntimeError('invalid_manager_request')
""", """def handle_manager_update_request(root, rap_dir, backup_dir, state, remote=None):
    req=root/'manager-update-request.json'
    if remote is None and not req.exists():return False
    out=root/'manager-update-result.json'
    try:
        if remote is None:
            if req.is_symlink() or req.stat().st_size>1024:raise RuntimeError('invalid_manager_request')
            data=json.loads(req.read_bytes())
            req.unlink()
            if data!={'action':'install-signed-manager'}:raise RuntimeError('invalid_manager_request')
""")
    source = replace_once(source, """        signed=fetch(CHANNEL,65536)
        latest=verify_manifest(signed)
        if latest['sequence']<=accepted:
""", """        if remote is None:
            signed=fetch(CHANNEL,65536)
            latest=verify_manifest(signed)
        else:
            directory, request, signed, latest = remote
        if latest['sequence']<=accepted:
            if remote is not None:
                save_remote_receipt(directory, request, 'up_to_date')
                return False
""")
    source = replace_once(source, """        handoff=prepare_handoff(rap_dir,stable_launcher,secure_state,
            state,secure_state/'helper'/'manager_update_helper.py')
        out.write_text(json.dumps({'state':'handoff','installation_performed':False}))
""", """        if remote is not None:
            from manager_update_release import MAX_ARCHIVE, verify_archive
            archive = fetch(latest['archive_url'], MAX_ARCHIVE)
            files = verify_archive(archive, latest)
            validate_remote_request(request)
            save_remote_receipt(directory, request, 'dispatching')
            handoff=prepare_handoff(rap_dir,stable_launcher,secure_state,
                state,secure_state/'helper'/'manager_update_helper.py',
                downloader=lambda: (signed, archive, files))
            try:
                save_remote_receipt(directory, request, 'handoff', attempt=handoff.identifier)
            except (OSError, ValueError):
                # Preserve the dispatch record and let the authenticated helper finish.
                pass
            handoff.release_for_parent_exit()
            return True
        handoff=prepare_handoff(rap_dir,stable_launcher,secure_state,
            state,secure_state/'helper'/'manager_update_helper.py')
        out.write_text(json.dumps({'state':'handoff','installation_performed':False}))
""")
    source = replace_once(source, """    except Exception as exc:
        out.write_text(json.dumps({'state':'refused','installation_performed':False,
            'reason':type(exc).__name__,'detail':str(exc)[:160]},ensure_ascii=False))
        return False

def main():
""", """    except Exception as exc:
        if remote is not None:
            save_remote_receipt(remote[0], remote[1], 'refused', reason=str(exc))
            return False
        out.write_text(json.dumps({'state':'refused','installation_performed':False,
            'reason':type(exc).__name__,'detail':str(exc)[:160]},ensure_ascii=False))
        return False

""" + protocol.decode("utf-8") + "\n" + adapter.decode("utf-8") + "\n\ndef main():\n")
    source = replace_once(source,
        "                if handle_manager_update_request(root,rap_dir,backup_dir,supervisor_state):return 42\n",
        "                if handle_manager_update_request(root,rap_dir,backup_dir,supervisor_state):return 42\n"
        "                if handle_remote_manager_update(root,rap_dir,backup_dir,supervisor_state):return 42\n")
    compile(source, "launch_manager.py", "exec")
    return source.encode("utf-8")


def build_from_resources(resources):
    source = Path(__file__).resolve().parent
    return build_launcher((resources / "launch_manager.py").read_bytes(),
                          (source / "manager_remote_request.py").read_bytes(),
                          (source / "manager_remote_launcher.py").read_bytes())
