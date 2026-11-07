"""Exercise a signed Manager update and exact rollback on disposable code copies.

This is a preparatory gate, not a production installer. The caller must also
run the macOS signing and authenticated runtime gates before publication.
"""
from pathlib import Path
import os
import stat
import tempfile

from app_bundle_backup import _copy_verified, inventory, restore_app_backup, save_app_backup
from bootstrap_release import PUBLISHER_PIN
from creative_release import Refused, digest
from creative_transaction import atomic_write, safe_path
from manager_update_release import (verify_archive, verify_baseline,
                                    verify_manifest)


def rehearse_on_copy(source, launcher, state, signed_manifest, archive, *,
                     pinned_key=PUBLISHER_PIN, now=None):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    if launcher.parent.name != 'Resources' or launcher.parents[2].suffix != '.app':
        raise Refused('manager_app_layout_unknown')
    app = launcher.parents[2]
    resources = launcher.parent
    state = Path(state).absolute()
    if (state.is_relative_to(source) or source.is_relative_to(state) or
            state.is_relative_to(app) or app.is_relative_to(state)):
        raise Refused('manager_rehearsal_state_overlap')
    for path in (state, *state.parents):
        if path.is_symlink():
            raise Refused('manager_rehearsal_state_symlink')
    manifest = verify_manifest(signed_manifest, pinned_key=pinned_key, now=now)
    files = verify_archive(archive, manifest)
    originals = verify_baseline(manifest, source, resources)
    before_app = inventory(app)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
        raise Refused('manager_rehearsal_private_state_required')
    with tempfile.TemporaryDirectory(prefix='manager-rehearsal-', dir=state) as tmp:
        root = Path(tmp)
        backup = root / 'app-backup'
        backup.mkdir(mode=0o700)
        snapshot = save_app_backup(app, backup)
        if snapshot != before_app or inventory(app) != before_app:
            raise Refused('manager_rehearsal_app_changed')
        copy_app = root / 'candidate.app'
        _copy_verified(backup / 'app-original.app', copy_app, snapshot)
        copy_resources = copy_app / 'Contents' / 'Resources'
        copy_source = root / 'rap-brain'
        copy_source.mkdir(mode=0o700)
        server = source / 'server.py'
        original_server = safe_path(server).read_bytes()
        atomic_write(copy_source / 'server.py', original_server,
                     stat.S_IMODE(server.stat().st_mode))
        before_copy = inventory(copy_app)
        for entry in manifest['files']:
            name = entry['path']
            destination = (copy_resources / name[4:] if name.startswith('app/')
                           else copy_source / name)
            original = originals[name]
            atomic_write(destination, files[name],
                         stat.S_IMODE(original.stat().st_mode))
            if digest(safe_path(destination).read_bytes()) != entry['payload_sha256']:
                raise Refused('manager_rehearsal_candidate_changed')
        for entry in manifest['files']:
            name = entry['path']
            destination = (copy_resources / name[4:] if name.startswith('app/')
                           else copy_source / name)
            if digest(safe_path(destination).read_bytes()) != entry['payload_sha256']:
                raise Refused('manager_rehearsal_candidate_changed')
        if not restore_app_backup(copy_app, backup):
            raise Refused('manager_rehearsal_restore_failed')
        if inventory(copy_app) != before_copy:
            raise Refused('manager_rehearsal_app_not_identical')
        atomic_write(copy_source / 'server.py', original_server,
                     stat.S_IMODE(server.stat().st_mode))
        if digest(safe_path(copy_source / 'server.py').read_bytes()) != digest(original_server):
            raise Refused('manager_rehearsal_server_not_identical')
    if (inventory(app) != before_app or
            any(digest(safe_path(path).read_bytes()) != entry['baseline_sha256']
                for entry in manifest['files'] for name, path in originals.items()
                if name == entry['path'])):
        raise Refused('manager_rehearsal_live_code_changed')
    return {'state': 'copy_rehearsal_passed', 'live_files_modified': False,
            'live_data_opened': False}
