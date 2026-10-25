"""Fail-closed static checker for disabled isolated Manager candidate.

Checks that an AST-transformed candidate has precisely the expected rewritten
home calls and blocked process spawns, and records residual sensitive operations.
No imports or execution of candidate source.
"""
import ast,hashlib
EXPECTED="93277e3b11b5fb38407fab5e0833b4f7e19bc3d0ce66d44628a216a05047c40a"
SENSITIVE={"open","mkdir","replace","rename","unlink","rmtree","copytree","write_text","write_bytes"}
def inspect_candidate(data):
    tree=ast.parse(data.decode("utf-8"))
    counts={"blocked_popen":0,"isolated_home":0,"unblocked_popen":0,"native_home":0,"remaining_file_ops":0}
    for n in ast.walk(tree):
        if not isinstance(n,ast.Call):continue
        f=n.func
        name=f.id if isinstance(f,ast.Name) else f.attr if isinstance(f,ast.Attribute) else ""
        if name=="_rb_disabled_popen":counts["blocked_popen"]+=1
        elif name=="Popen":counts["unblocked_popen"]+=1
        elif name=="_rb_isolated_home":counts["isolated_home"]+=1
        elif name=="home":counts["native_home"]+=1
        if name in SENSITIVE:counts["remaining_file_ops"]+=1
    return counts
def gate(data,expected_sha=EXPECTED):
    if hashlib.sha256(data).hexdigest()!=expected_sha:raise ValueError("unrecognized candidate hash")
    counts=inspect_candidate(data)
    if counts["blocked_popen"]!=5 or counts["isolated_home"]!=8 or counts["unblocked_popen"] or counts["native_home"]:
        raise ValueError("candidate rewrite incomplete")
    return {"status":"NON_EXECUTABLE_REVIEW_ONLY","counts":counts}
