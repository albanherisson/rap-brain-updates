"""Build a deterministic, unsigned full bootstrap candidate in memory.

The output deliberately cannot pass the production verifier. A separate
owner-Mac signer must attest completed validations with the existing key.
"""
import io
import stat
import zipfile

from bootstrap_full_release import FILES, PRIMARY, RUNTIME_FILES
from bootstrap_runtime_resources import verify_runtime_resources
from creative_release import Refused, digest
from recovery_start_guards import prepare_server
from beta14_one_click_candidate import prepare_launcher, prepare_dashboard


def assemble(originals, runtime_sources):
    if (type(originals) is not dict or originals.keys() != set(PRIMARY) or
            type(runtime_sources) is not dict or
            runtime_sources.keys() != set(RUNTIME_FILES) or
            any(type(originals[name]) is not bytes or not originals[name]
                for name in PRIMARY)):
        raise Refused('bootstrap_packager_inputs')
    runtime_hashes = {name: digest(runtime_sources[name]) for name in RUNTIME_FILES
                      if type(runtime_sources[name]) is bytes}
    verify_runtime_resources(runtime_sources, runtime_hashes)
    candidates = {'server.py': prepare_server(originals['server.py']),
                  'launch_manager.py': prepare_launcher(originals['launch_manager.py']),
                  'dashboard_beta14.html': prepare_dashboard(originals['dashboard_beta14.html'])}
    candidates.update(runtime_sources)
    if any(type(candidates[name]) is not bytes or len(candidates[name]) > 250_000
           for name in FILES):
        raise Refused('bootstrap_packager_size')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, candidates[name], compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    raw = output.getvalue()
    if not 0 < len(raw) <= 2_000_000:
        raise Refused('bootstrap_packager_archive_size')
    return raw, {name: digest(candidates[name]) for name in FILES}, {
        name: digest(originals[name]) for name in PRIMARY}
