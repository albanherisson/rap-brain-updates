"""Observed macOS Manager isolation audit facts; never authorize launch.
Fingerprint bdd2d65c... from owner's machine 2026-10-25.
AST occurrence counts are not comprehensive path-flow analysis.
"""
from dataclasses import dataclass
@dataclass(frozen=True)
class IsolationEvidence:
    absolute_literals:int=25
    popen_count:int=5
    explicit_env:int=2
    explicit_cwd:int=2
    shell_true:int=0
    home_calls:int=8
    writes:int=22

def isolation_gate(evidence:IsolationEvidence):
    if not isinstance(evidence,IsolationEvidence):
        return "BLOCK_UNVERIFIED"
    if evidence.absolute_literals or evidence.popen_count!=evidence.explicit_env:
        return "BLOCK_EXECUTABLE_COPY_UNTIL_FULL_PATH_REVIEW"
    return "REQUIRES_INDEPENDENT_SANDBOX_VALIDATION"

EVIDENCE=IsolationEvidence()
