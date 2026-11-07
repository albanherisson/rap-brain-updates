"""Fixed code-only inventory of the one-time Finder capability."""

APP_SUPPORT_FILES = (
    'beta14_launch_gate.py', 'beta14_owned_identity_candidate.py',
    'beta14_runtime_token_candidate.py', 'bootstrap_release.py',
    'manager_helper_inventory.py', 'manager_helper_release.py',
    'recovery_start_guards.py', 'server_graceful_shutdown_candidate.py',
    'server_lifetime_guard.py', 'server_worker_resume_candidate.py',
)
APP_CODE_FILES = ('launch_manager.py', 'dashboard_beta14.html') + APP_SUPPORT_FILES
