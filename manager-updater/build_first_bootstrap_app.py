"""Build a disposable Finder app for the first signed bootstrap on macOS.

This is a packaging tool, not a production release. The app never includes a
publisher private key or a signed update payload. Publish only after the
signed release and actual Mac validation gates have been completed.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import sys

from creative_release import Refused


ROOT = Path(__file__).resolve().parent
ENTRY = 'first_bootstrap_installer'
APP_NAME = 'Installer Rap Brain.app'
APPLE_SCRIPT = '''on run
    set scriptPath to (POSIX path of (path to me)) & "Contents/Resources/updater/first_bootstrap_installer.py"
    set selectorPath to (POSIX path of (path to me)) & "Contents/Resources/updater/python_bootstrap_selector.sh"
    try
        do shell script "/bin/sh " & quoted form of selectorPath & " " & quoted form of scriptPath & " --install-signed"
        display dialog "Installation Rap Brain terminée. Tu peux ouvrir le Manager." buttons {"OK"} default button "OK"
    on error errText
        if errText contains "rapbrain_or_manager_still_running" then
            display dialog "Rap Brain est encore ouvert. Attends la fin de tes analyses, ferme Rap Brain et le Manager, puis réessaie." buttons {"OK"} default button "OK" with icon caution
        else
            display dialog "Installation arrêtée par mesure de sécurité. Aucun remplacement ne doit être tenté manuellement." & return & errText buttons {"OK"} default button "OK" with icon caution
        end if
    end try
end run
'''


def dependencies(root=ROOT, entry=ENTRY):
    """Use only local static imports; fail if the source tree is incomplete."""
    modules = {path.stem: path for path in root.glob('*.py')
               if not path.name.startswith('test_')}
    discovered = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in discovered:
            continue
        if name not in modules:
            raise Refused('installer_module_missing')
        discovered.add(name)
        source = modules[name].read_bytes()
        compile(source, modules[name].name, 'exec')
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                dependency = node.module.split('.')[0]
                if dependency in modules:
                    pending.append(dependency)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    dependency = alias.name.split('.')[0]
                    if dependency in modules:
                        pending.append(dependency)
    return tuple(sorted(modules[name] for name in discovered))


def build(destination, *, source=ROOT, compiler='/usr/bin/osacompile',
          signer='/usr/bin/codesign'):
    if sys.platform != 'darwin':
        raise Refused('macos_required_for_finder_app')
    destination = Path(destination).absolute()
    if destination.name != APP_NAME or destination.exists() or destination.is_symlink():
        raise Refused('installer_destination_not_empty')
    if destination.parent.is_symlink() or not destination.parent.is_dir():
        raise Refused('installer_destination_parent')
    files = dependencies(source)
    script = destination.parent / (destination.stem + '.applescript')
    if script.exists() or script.is_symlink():
        raise Refused('installer_script_already_exists')
    try:
        script.write_text(APPLE_SCRIPT, encoding='utf-8')
        subprocess.run([compiler, '-o', str(destination), str(script)],
                       check=True, capture_output=True, timeout=90)
        resources = destination / 'Contents' / 'Resources' / 'updater'
        resources.mkdir(mode=0o700)
        for path in files:
            shutil.copyfile(path, resources / path.name)
        shutil.copyfile(source / 'python_bootstrap_selector.sh',
                        resources / 'python_bootstrap_selector.sh')
        shutil.copyfile(source / 'verify_ed25519.swift',
                        resources / 'verify_ed25519.swift')
        subprocess.run([signer, '--force', '--deep', '--sign', '-', str(destination)],
                       check=True, capture_output=True, timeout=90)
        subprocess.run([signer, '--verify', '--deep', '--strict', str(destination)],
                       check=True, capture_output=True, timeout=90)
        return {'app': str(destination), 'modules': len(files),
                'signature_verified': True}
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('installer_build_failed') from exc
    finally:
        script.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: build_first_bootstrap_app.py DESTINATION_APP')
    print(build(sys.argv[1]))
