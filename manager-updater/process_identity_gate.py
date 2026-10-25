#!/usr/bin/env python3
"""Conservative READ-ONLY process identity gate, never an authorization to signal a PID."""
import json
import re
from pathlib import Path

class UnsafeProcess(RuntimeError): pass

def parse_state(data: bytes):
    if not isinstance(data, bytes) or not (0 < len(data) <= 8192):
        raise UnsafeProcess("Malformed or oversized state")
    try: state=json.loads(data)
    except (ValueError, UnicodeError) as e: raise UnsafeProcess("Malformed JSON") from e
    if type(state) is not dict or set(state) != {"pid","port"}:
        raise UnsafeProcess("Unexpected state fields")
    pid,port=state["pid"],state["port"]
    if type(pid) is not int or not (2 <= pid <= 4194304):
        raise UnsafeProcess("Unsafe PID")
    if type(port) is not int or not (1024 <= port <= 65535):
        raise UnsafeProcess("Unsafe port")
    return pid,port

def exact_process_command(command: str, expected_script: Path):
    if not command or any(c in command for c in "\n\r\0"): return False
    # macOS ps -o command= can print a path with spaces without quoting.
    # Compare the ENTIRE command, not a substring or a whitespace token.
    return re.fullmatch(r"/[^\s]+/(?:python3|Python|python) " + re.escape(str(expected_script)), command) is not None

def may_prepare_restart(state: bytes, command: str, script: Path, healthy: bool):
    parse_state(state)
    if not exact_process_command(command,script):
        raise UnsafeProcess("Process does not unambiguously match Manager")
    if healthy is not True:
        raise UnsafeProcess("Health probe failed")
    return True
