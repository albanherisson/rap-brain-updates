"""Build the exact, unsigned one-time Manager capability candidate in memory.

The Finder installer and Manager-key signature are separate gates. This module
never reads the owner's app, database, library, or publisher key.
"""
import io
from pathlib import Path
import stat
import zipfile

from bootstrap_runtime_resources import RUNTIME_FILES
from build_first_bootstrap_app import dependencies
from creative_release import Refused, digest
from manager_helper_bundle import assemble as assemble_helper
from manager_update_ui_candidate import prepare_launcher, prepare_dashboard


ROOT = Path(__file__).resolve().parent
APP_SUPPORT_FILES = (
    'beta14_launch_gate.py', 'beta14_owned_identity_candidate.py',
    'beta14_runtime_token_candidate.py', 'bootstrap_release.py',
    'manager_helper_inventory.py', 'manager_helper_release.py',
    'recovery_start_guards.py', 'server_graceful_shutdown_candidate.py',
    'server_lifetime_guard.py', 'server_worker_resume_candidate.py',
)
APP_CODE_FILES = ('launch_manager.py', 'dashboard_beta14.html') + APP_SUPPORT_FILES


def assemble(launcher, dashboard, *, root=ROOT):
    """Return deterministic candidate bytes and exact hashes; never install."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise Refused('manager_capability_source_missing')
    closure = {path.name for path in dependencies(root, entry='manager_helper_release')}
    if closure - set(RUNTIME_FILES) != set(APP_SUPPORT_FILES):
        raise Refused('manager_capability_import_inventory_changed')
    helper, helper_hashes = assemble_helper(root)
    values = {
        'app/launch_manager.py': prepare_launcher(launcher),
        'app/dashboard_beta14.html': prepare_dashboard(dashboard),
    }
    for name in APP_SUPPORT_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise Refused('manager_capability_source_unsafe')
        raw = path.read_bytes()
        if not 0 < len(raw) <= 250_000:
            raise Refused('manager_capability_member_size')
        compile(raw, name, 'exec')
        values['app/' + name] = raw
    values['helper.zip'] = helper
    if sum(map(len, values.values())) > 2_000_000:
        raise Refused('manager_capability_total_size')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name in sorted(values):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, values[name], compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    return buffer.getvalue(), {name: digest(raw) for name, raw in values.items()}, helper_hashes
