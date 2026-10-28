"""Immutable, read-only AST observations from owner's fingerprint-checked Manager.

These observations never permit signaling or installation. Existing kill() calls
cannot be classified as safe from their location alone.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Callsite:
    line: int
    name: str
    context: str
    positional: int
    keywords: int

EXPECTED_SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
OBSERVED=(
    Callsite(385,"Popen","try,function",1,6),
    Callsite(399,"Popen","try,function",1,4),
    Callsite(423,"Popen","try,function",1,6),
    Callsite(439,"kill","if,try,function",0,0),
    Callsite(459,"kill","if,except,try,function",0,0),
    Callsite(467,"Popen","try,function",1,4),
    Callsite(831,"ThreadingHTTPServer","function",2,0),
    Callsite(837,"Popen","if,if,function",1,2),
    Callsite(839,"serve_forever","try,function",0,1),
)

def lifecycle_review():
    calls={name:[x for x in OBSERVED if x.name==name]
           for name in ("kill","Popen","ThreadingHTTPServer","serve_forever")}
    if len(calls["kill"]) != 2 or len(calls["ThreadingHTTPServer"]) != 1:
        raise ValueError("Observations not recognized")
    return dict(
        existing_kill_semantics="UNKNOWN_DO_NOT_REUSE",
        server_stop_mechanism="NOT_PROVEN",
        authenticated_shutdown="NOT_PRESENT_IN_OBSERVATIONS",
        supervisor_stop_allowed=False,
        installation_allowed=False,
        all_actions="READ_ONLY",
    )
