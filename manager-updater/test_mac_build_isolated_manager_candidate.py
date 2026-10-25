import ast,unittest
from mac_build_isolated_manager_candidate import transform
class TestTransform(unittest.TestCase):
 def test_raises_on_different_call_count(self):
  with self.assertRaises(AssertionError):transform(b"from pathlib import Path\nPath.home()\n")
 def test_transform_eight_home_five_popen(self):
  data=("from pathlib import Path\nfrom subprocess import Popen\n"+ "x = Path.home()\n"*8 + "Popen(['x'])\n"*5).encode()
  result,homes,popens=transform(data)
  self.assertEqual((homes,popens),(8,5))
  tree=ast.parse(result)
  self.assertEqual(sum(1 for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="_rb_disabled_popen"),5)
  self.assertIn(b"BLOCKED: isolated Manager process spawn",result)
 def test_future_import_preserved(self):
  data=("# coding: utf-8\nfrom __future__ import annotations\nfrom pathlib import Path\n"+"Path.home()\n"*8+"Popen([])\n"*5).encode()
  patched,_,_=transform(data)
  compile(patched,"candidate.py","exec")
if __name__=="__main__":unittest.main()
