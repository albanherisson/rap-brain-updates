"""Fail-closed release gate based on actual installed Manager AST observations.

This is a development checklist, not proof of sandboxing or a launcher.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class IsolationReview:
    pinned_manager_sha: str
    popen_lines_without_explicit_env_cwd: tuple
    unresolved_file_sink_lines: tuple
    data_root_configurable: bool=False
    children_inherit_explicit_sandbox: bool=False
    filesystem_targets_verified: bool=False
    authenticated_stop_integrated: bool=False
    restart_probe_integrated: bool=False

OBSERVED=IsolationReview(
    pinned_manager_sha="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5",
    popen_lines_without_explicit_env_cwd=(399,467,837),
    unresolved_file_sink_lines=(65,109,175,314,353,359,364),
)

def permitted_to_execute_installed_manager_copy(review):
    """Never grant solely on AST evidence: explicit independent verification required."""
    if not isinstance(review,IsolationReview):return False
    return False

def remaining_blockers(review):
    if not isinstance(review,IsolationReview):return ("missing verified review",)
    requirements={
      "data_root_configurable":"make all file targets configurable",
      "children_inherit_explicit_sandbox":"pass bounded env/cwd to all child processes",
      "filesystem_targets_verified":"verify destinations and symlink defenses",
      "authenticated_stop_integrated":"integrate authenticated stop in isolated Manager",
      "restart_probe_integrated":"check actual restarted Manager response",
    }
    return tuple(message for flag,message in requirements.items() if not getattr(review,flag))
