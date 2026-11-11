"""Recognize the signed Creative P8 engine in the current Manager preview.

Prepare only a reviewed launcher payload for a later Manager-signed release.
The installed app and Rap Brain data are not touched by this module.
"""
import hashlib


BASELINE_LAUNCHER_SHA256 = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'
CREATIVE_P8_SHA256 = 'b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3'


def _prepare_launcher(raw, known_engine_sha256):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE_LAUNCHER_SHA256:
        raise ValueError('manager_version_launcher_baseline_changed')
    source = raw.decode('utf-8')
    anchor = 'm.SOURCE=host_source\n'
    if source.count(anchor) != 1:
        raise ValueError('manager_version_status_anchor_changed')
    candidate = source.replace(anchor, anchor + '''_original_status=m.status
def _recognized_status():
 result=_original_status()
 if result.get('version')=='Version non reconnue':
  try:
   if hashlib.sha256((host_source/'creative_engine.py').read_bytes()).hexdigest()==__KNOWN_ENGINE_SHA256__:
    result=dict(result)
    result['version']='Beta 8.8 + Creative P8'
  except OSError:pass
 return result
m.status=_recognized_status
'''.replace('__KNOWN_ENGINE_SHA256__', repr(known_engine_sha256)), 1)
    output = candidate.encode('utf-8')
    compile(output, 'launch_manager.py', 'exec')
    return output


def prepare_launcher(raw):
    return _prepare_launcher(raw, CREATIVE_P8_SHA256)
