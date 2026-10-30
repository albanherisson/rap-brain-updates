"""Build a disposable Finder installer for the signed Creative trust rotation."""
from pathlib import Path
import shutil
import subprocess
import sys

from build_first_bootstrap_app import dependencies
from creative_release import Refused


ROOT = Path(__file__).resolve().parent
NAME = 'Installer Creative Rap Brain.app'
SCRIPT = '''on run
    set root to POSIX path of (path to me)
    set scriptPath to root & "Contents/Resources/updater/creative_trust_installer.py"
    set selectorPath to root & "Contents/Resources/updater/python_bootstrap_selector.sh"
    try
        do shell script "/bin/sh " & quoted form of selectorPath & " " & quoted form of scriptPath & " --install-signed"
        display dialog "Clé Creative mise à jour. Ouvre ensuite Rap Brain Manager." buttons {"OK"} default button "OK"
    on error errText
        if errText contains "rapbrain_or_manager_still_running" then
            display dialog "Ferme Rap Brain et le Manager, puis réessaie quand aucune analyse n'est en cours." buttons {"OK"} default button "OK" with icon caution
        else
            display dialog "Installation arrêtée par sécurité. N'effectue aucun remplacement manuel." & return & errText buttons {"OK"} default button "OK" with icon caution
        end if
    end try
end run
'''


def build(destination, *, source=ROOT, compiler='/usr/bin/osacompile',
          signer='/usr/bin/codesign'):
    if sys.platform != 'darwin':
        raise Refused('macos_required_for_finder_app')
    destination = Path(destination).absolute()
    if (destination.name != NAME or destination.exists() or destination.is_symlink() or
            destination.parent.is_symlink() or not destination.parent.is_dir()):
        raise Refused('trust_rotation_destination_invalid')
    files = dependencies(source, entry='creative_trust_installer')
    script = destination.parent / (destination.stem + '.applescript')
    if script.exists() or script.is_symlink():
        raise Refused('trust_rotation_script_exists')
    try:
        script.write_text(SCRIPT, encoding='utf-8')
        subprocess.run([compiler, '-o', str(destination), str(script)],
                       check=True, capture_output=True, timeout=90)
        resources = destination / 'Contents' / 'Resources' / 'updater'
        resources.mkdir(mode=0o700)
        for path in files:
            shutil.copyfile(path, resources / path.name)
        for name in ('python_bootstrap_selector.sh', 'verify_ed25519.swift'):
            shutil.copyfile(source / name, resources / name)
        for args in ((signer, '--force', '--deep', '--sign', '-', str(destination)),
                     (signer, '--verify', '--deep', '--strict', str(destination))):
            subprocess.run(args, check=True, capture_output=True, timeout=90)
        return {'app': str(destination), 'modules': len(files), 'signature_verified': True}
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('trust_rotation_app_build_failed') from exc
    finally:
        script.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: build_creative_trust_app.py DESTINATION_APP')
    print(build(sys.argv[1]))
