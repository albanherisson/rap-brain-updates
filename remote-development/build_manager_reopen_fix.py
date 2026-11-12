"""Build the Manager reopening correction against the reviewed P0 sources."""

import hashlib
from pathlib import Path

LAUNCHER_SHA = "ceda87b7655d643ca6e9dc66afa0f5d3e0d20857abd2e8c202b8a1978b86a660"
HELPER_PINS = {
    "manager_offline_lifecycle.py": "8f798aa4fcd2397ef96dfcf2b5635bf16364ddd03c92c5dd34e772ffc3a7fcd8",
    "manager_update_helper.py": "8780cfa32a101528da10a50c8fe3347b1a03c6328b42fa613788bfcbe630edc4",
    "manager_update_transaction.py": "9490a2ed92076370b0dff45187fe3f7db2b8aaf1686236043a9701b1539d103a",
}


def replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError("manager_reopen_fix_anchor_changed")
    return source.replace(old, new, 1)


def checked_text(raw, expected):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("manager_reopen_fix_baseline_changed")
    return raw.decode("utf-8")


def checked_code(source, name):
    raw = source.encode("utf-8")
    compile(raw, name, "exec")
    return raw


START_GUARD = """def yield_to_manager_update(backup_dir):
    state = backup_dir / 'secure-update'
    if not any(os.path.lexists(state / name)
               for name in ('maintenance.ticket', 'bootstrap-intent.json')):
        return False
    print('Mise à jour du Manager en cours. Réessaie après sa fin.', flush=True)
    return True


"""


def build_launcher(raw):
    source = checked_text(raw, LAUNCHER_SHA)
    source = replace(source, "def main():\n", START_GUARD + "def main():\n")
    source = replace(source, """    backup_dir=backup_dir.resolve()
    demo=source.parent/'demo_release'/'manifest.json'
""", """    backup_dir=backup_dir.resolve()
    # The native launcher treats exit 42 as an instruction to close.
    if yield_to_manager_update(backup_dir):return 42
    demo=source.parent/'demo_release'/'manifest.json'
""")
    source = replace(source, """            if code!=200 or json.loads(body).get('state') not in ('idle','aborted','committed','rolled_back','restored_stopped'):raise RuntimeError('Manager update state invalid')
""", """            if code!=200 or json.loads(body).get('state') not in ('idle','aborted','committed','rolled_back','restored_stopped','check_required'):raise RuntimeError('Manager update state invalid')
            if yield_to_manager_update(backup_dir):return 42
""")
    return checked_code(source, "launch_manager.py")


GRACE = """MANAGER_EXIT_GRACE_SECONDS = 4
MANAGER_EXIT_POLL_SECONDS = 0.1
_MANAGER_ONLY = {'server_process_seen': False, 'manager_process_seen': True,
                 'port_8765_listening': False}


def wait_for_manager_exit(inspector, source, resources):
    deadline = time.monotonic() + MANAGER_EXIT_GRACE_SECONDS
    while True:
        report = inspector(source, resources)
        if (type(report) is not dict or report != _MANAGER_ONLY
                or any(type(value) is not bool for value in report.values())):
            return report
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return report
        time.sleep(min(MANAGER_EXIT_POLL_SECONDS, remaining))


"""


def build_lifecycle(source):
    source = replace(source, "import os\n", "import os\nfrom functools import partial\nimport time\n")
    source = replace(source, "class MacOfflineManagerLifecycle", GRACE + "class MacOfflineManagerLifecycle")
    return replace(source, """        super().__init__(source, launcher, state, shape, **kwargs)
""", """        super().__init__(source, launcher, state, shape, **kwargs)
        # All existing offline checks still require a clear inventory. Give a
        # Manager opening during maintenance time to honor its clean exit.
        self.inspector = partial(wait_for_manager_exit, self.inspector)
""")


REASON = """def refusal_reason(error):
    detail = str(error)
    if isinstance(error, ValueError) and re.fullmatch(r'[a-z][a-z0-9_]{0,99}', detail):
        return detail
    return type(error).__name__


"""


def build_transaction(source):
    source = replace(source, "from pathlib import Path\n", "from pathlib import Path\nimport re\n")
    source = replace(source, "class ManagerUpdateTransaction", REASON + "class ManagerUpdateTransaction")
    return replace(source, """        except Exception:
            if ((folder / 'app-backup.json').is_file() and
                    (folder / 'backup.json').is_file()):
                return self._restore(record, folder, manifest, lease)
""", """        except Exception as exc:
            if ((folder / 'app-backup.json').is_file() and
                    (folder / 'backup.json').is_file()):
                result = self._restore(record, folder, manifest, lease)
                return result | {'reason': refusal_reason(exc)}
""")


def build_helper(source):
    source = replace(source,
                     "from manager_update_transaction import ManagerUpdateTransaction\n",
                     "from manager_update_transaction import ManagerUpdateTransaction, refusal_reason\n")
    source = replace(source, """            return result | {'reason': type(exc).__name__}
        except Exception:
            raise
""", """            return result | {'reason': refusal_reason(exc)}
        except Exception:
            # The pre-journal fallback can itself refuse after a write.
            # Keep the cause of the failed transaction for recovery.
            raise exc from None
""")
    return replace(source, "{'state': 'check_required', 'reason': type(exc).__name__}",
                   "{'state': 'check_required', 'reason': refusal_reason(exc)}")


def build_helpers(directory):
    directory = Path(directory)
    builders = {
        "manager_offline_lifecycle.py": build_lifecycle,
        "manager_update_helper.py": build_helper,
        "manager_update_transaction.py": build_transaction,
    }
    return {
        name: checked_code(build(checked_text((directory / name).read_bytes(), HELPER_PINS[name])), name)
        for name, build in builders.items()
    }
