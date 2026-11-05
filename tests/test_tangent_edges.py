"""Drawing views show tangent edges, thin, as Inventor does (GitHub #15)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox                 # noqa: E402

from datum.core import hlr, kernel                              # noqa: E402

box = BRepPrimAPI_MakeBox(40, 30, 20).Shape()
rounded = kernel.fillet(box, kernel.edges(box), 3)
view = hlr.project(rounded, *hlr.ORIENTATIONS["front"])
ok = len(view.of_kind(hlr.SMOOTH)) > 0
print(("  PASS  " if ok else "  FAIL  ")
      + "where a fillet meets a face, the view draws the tangent edge")
if not ok:
    sys.exit(1)
print("all passed")
