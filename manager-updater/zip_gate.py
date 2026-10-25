"""Read-only ZIP content gate. No extraction or execution."""
import stat
import zipfile
MAX_FILE=2_000_000
ENTRY="Contents/Resources/manager.py"
class UnsafeArchive(ValueError): pass
def verify_zip(path):
    try:
        with zipfile.ZipFile(path) as z:
            info=z.infolist()
            if len(info)!=1 or info[0].filename!=ENTRY:
                raise UnsafeArchive("Unexpected ZIP layout")
            member=info[0]
            if member.is_dir() or member.file_size>MAX_FILE or member.flag_bits & 1:
                raise UnsafeArchive("Unsafe ZIP entry")
            mode=member.external_attr >> 16
            if stat.S_IFMT(mode) not in (0,stat.S_IFREG):
                raise UnsafeArchive("Nonregular ZIP entry")
            with z.open(member) as src:
                data=src.read(MAX_FILE+1)
                if len(data)!=member.file_size:
                    raise UnsafeArchive("ZIP entry size mismatch")
            return len(data)
    except (zipfile.BadZipFile,RuntimeError,OSError,EOFError) as exc:
        raise UnsafeArchive("Damaged ZIP") from exc
