"""Build the Finder entry for the signed, copy-tested Manager repair on macOS."""
from pathlib import Path
import shutil
import subprocess
import sys

from build_first_bootstrap_app import dependencies
from creative_release import Refused


ROOT = Path(__file__).resolve().parent
NAME = 'Réparer la date du Manager.app'
SCRIPT = '''on run
    set root to POSIX path of (path to me)
    set scriptPath to root & "Contents/Resources/updater/manager_repair_installer.py"
    set selectorPath to root & "Contents/Resources/updater/python_bootstrap_selector.sh"
    try
        do shell script "/bin/sh " & quoted form of selectorPath & " " & quoted form of scriptPath & " --install-signed"
        display dialog "Réparation terminée. Rouvre Rap Brain Manager." buttons {"OK"} default button "OK"
    on error errText
        if errText contains "rapbrain_or_manager_still_running" then
            display dialog "Ferme Rap Brain et le Manager quand aucune analyse n'est en cours, puis réessaie." buttons {"OK"} default button "OK" with icon caution
        else
            display dialog "Réparation arrêtée par sécurité. Aucun fichier ne doit être remplacé manuellement." & return & errText buttons {"OK"} default button "OK" with icon caution
        end if
    end try
end run
'''


def build(destination, *, release, archive, source=ROOT, compiler='/usr/bin/osacompile',
          signer='/usr/bin/codesign'):
    if sys.platform != 'darwin':
        raise Refused('macos_required_for_finder_app')
    destination = Path(destination).absolute()
    if (destination.name != NAME or destination.exists() or destination.is_symlink() or
            destination.parent.is_symlink() or not destination.parent.is_dir()):
        raise Refused('manager_repair_destination_invalid')
    files = dependencies(source, entry='manager_repair_installer')
    from manager_repair_release import verify_release
    verify_release(release, archive)
    script = destination.parent / (destination.stem + '.applescript')
    if script.exists() or script.is_symlink():
        raise Refused('manager_repair_script_exists')
    try:
        script.write_text(SCRIPT, encoding='utf-8')
        subprocess.run([compiler, '-o', str(destination), str(script)],
                       check=True, capture_output=True, timeout=90)
        resources = destination / 'Contents/Resources/updater'
        resources.mkdir(mode=0o700)
        for path in files:
            shutil.copyfile(path, resources / path.name)
        for name in ('python_bootstrap_selector.sh', 'verify_ed25519.swift'):
            shutil.copyfile(Path(source) / name, resources / name)
        (resources / 'signed-release.json').write_bytes(release)
        (resources / 'repair-4.zip').write_bytes(archive)
        for args in ((signer, '--force', '--deep', '--sign', '-', str(destination)),
                     (signer, '--verify', '--deep', '--strict', str(destination))):
            subprocess.run(args, check=True, capture_output=True, timeout=90)
        return {'app': str(destination), 'modules': len(files),
                'signature_verified': True}
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('manager_repair_app_build_failed') from exc
    finally:
        script.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Usage: build_manager_repair_app.py DESTINATION_APP SIGNED_JSON REPAIR_ZIP')
    print(build(sys.argv[1], release=Path(sys.argv[2]).read_bytes(),
                archive=Path(sys.argv[3]).read_bytes()))
