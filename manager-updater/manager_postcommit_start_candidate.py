"""Narrow launcher correction for the signed Manager's post-commit startup.

The Manager smoke process uses ``python -I -c``. Its update-state handler must
read the private handoff receipt without importing an updater module that is
absent from that isolated interpreter. This function only builds candidate
bytes; it never changes an installed application.
"""
import hashlib


BASELINE = '3afca9071b69a91996fe0ff1047a0ee4524cdf2f626cebd422ef30d576098bd0'
OLD = "     from pending_attempt_recovery import _private_json\n     result=_private_json(secure/'manager-handoff-result.json',4096)"
NEW = """     import stat
     receipt=secure/'manager-handoff-result.json'
     fd=os.open(receipt,os.O_RDONLY|os.O_NOFOLLOW)
     try:
      info=os.fstat(fd)
      if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or
          info.st_mode & 0o077 or not 0<info.st_size<=4096):
       raise ValueError('unsafe_manager_result')
      raw=os.read(fd,4097)
      if len(raw)!=info.st_size:raise ValueError('changed_manager_result')
     finally:os.close(fd)
     def unique_result(pairs):
      value={}
      for key,item in pairs:
       if key in value:raise ValueError('duplicate_manager_result')
       value[key]=item
      return value
     result=json.loads(raw,object_pairs_hook=unique_result)"""


def prepare_launcher(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('postcommit_launcher_baseline_changed')
    source = raw.decode('utf-8')
    if source.count(OLD) != 1:
        raise ValueError('postcommit_result_anchor_changed')
    candidate = source.replace(OLD, NEW, 1).encode('utf-8')
    compile(candidate, 'launch_manager.py', 'exec')
    return candidate
