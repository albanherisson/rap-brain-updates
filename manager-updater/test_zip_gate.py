import io,stat,unittest,zipfile
from zip_gate import verify_zip,UnsafeArchive
ENTRY="Contents/Resources/manager.py"
def archive(entries):
    f=io.BytesIO()
    with zipfile.ZipFile(f,"w") as z:
        for name,data in entries:z.writestr(name,data)
    f.seek(0);return f
class Tests(unittest.TestCase):
    def test_valid(self):self.assertEqual(verify_zip(archive([(ENTRY,b"a")])),1)
    def test_empty(self):
        with self.assertRaises(UnsafeArchive):verify_zip(archive([]))
    def test_traversal(self):
        with self.assertRaises(UnsafeArchive):verify_zip(archive([("../manager.py",b"a")]))
    def test_duplicate(self):
        with self.assertRaises(UnsafeArchive):verify_zip(archive([(ENTRY,b"a"),(ENTRY,b"b")]))
    def test_extra(self):
        with self.assertRaises(UnsafeArchive):verify_zip(archive([(ENTRY,b"a"),("other",b"x")]))
    def test_oversize(self):
        with self.assertRaises(UnsafeArchive):verify_zip(archive([(ENTRY,b"x"*2000001)]))
    def test_corrupt(self):
        with self.assertRaises(UnsafeArchive):verify_zip(io.BytesIO(b"not a zip"))
    def test_symlink(self):
        f=io.BytesIO()
        with zipfile.ZipFile(f,"w") as z:
            i=zipfile.ZipInfo(ENTRY);i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(i,b"/tmp/target")
        f.seek(0)
        with self.assertRaises(UnsafeArchive):verify_zip(f)
if __name__=="__main__":unittest.main()
