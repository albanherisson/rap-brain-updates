"""Fail-closed parser for signed metadata: disallow duplicate keys and nonfinite values."""
import json
class InvalidSignedJSON(ValueError):
    pass
def _pairs(items):
    obj={}
    for key,value in items:
        if key in obj:raise InvalidSignedJSON("Duplicate JSON field: "+key)
        obj[key]=value
    return obj
def _bad_constant(value):
    raise InvalidSignedJSON("Nonfinite JSON number: "+value)
def parse_signed_json(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=65536:
        raise InvalidSignedJSON("Invalid catalog size")
    try:return json.loads(raw.decode("utf-8"),object_pairs_hook=_pairs,parse_constant=_bad_constant)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise InvalidSignedJSON("Invalid JSON encoding") from exc
