"""Sketch ellipses: drawn with three clicks, extruded, held by constraints,
and written to DXF."""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import dxf, kernel                              # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.features import ExtrudeFeature, SketchFeature   # noqa: E402
from datum.core.sketch import Sketch, SketchPlane               # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("an ellipse extrudes")
doc = Document()
sk = SketchFeature(name="S")
sk.sketch = Sketch(SketchPlane(), "S")
e = sk.sketch.add_ellipse((10.0, 5.0), (40.0, 5.0), 12.0)
doc.add_feature(sk)
ex = ExtrudeFeature()
ex.sketch_id, ex.distance = sk.id, "8"
doc.add_feature(ex)
doc.rebuild()
check("its volume is pi a b h", doc.shape is not None and abs(
    kernel.volume(doc.shape) - math.pi * 30 * 12 * 8) < 0.5,
    kernel.volume(doc.shape) if doc.shape else ex.error)

print("turned, and with the short axis first")
s = Sketch(SketchPlane(), "s")
s.add_ellipse((0.0, 0.0), (6.0, 8.0), 20.0)
face = kernel.sketch_regions_faces(s)
check("one region, its area pi a b",
      len(face) == 1 and abs(kernel.face_area(face[0])
                             - math.pi * 10 * 20) < 0.1,
      [kernel.face_area(f) for f in face])

print("held by constraints")
s = Sketch(SketchPlane(), "s")
el = s.add_ellipse((0.0, 0.0), (30.0, 0.0), 10.0)
c, m = s.entities[el].points
s.points[c].fixed = True
s.add_constraint("radius", entities=[el], value=15.0)
s.add_constraint("distance", points=[c, m], value=50.0)
p = s.add_point(0.0, 12.0)
s.add_constraint("point_on", points=[p], entities=[el])
s.solve()
(_cx, _cy), a, b, _turn = s.ellipse_axes(el)
check("its half axes take their dimensions", abs(a - 50) < 1e-5
      and abs(b - 15) < 1e-5, (a, b))
q = s.points[p]
check("a point held on it lies on it",
      abs((q.x / a) ** 2 + (q.y / b) ** 2 - 1) < 1e-5, (q.x, q.y))

print("in DXF")
path = os.path.join(tempfile.mkdtemp(), "e.dxf")
dxf.sketch_to_dxf(s, path)
text = open(path).read() if os.path.exists(path) else ""
check("written as a closed polyline", "LWPOLYLINE" in text, path)

print("drawn with three clicks")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from datum.ui.main_window import MainWindow                     # noqa: E402

win = MainWindow()
win.show()
win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
for _ in range(30):
    app.processEvents()
ed = win.editor
win.set_sketch_tool("ellipse")
ed.begin_change()
for pt in ((0.0, 0.0), (25.0, 0.0), (3.0, 9.0)):
    ed._tool_ellipse(pt, QtCore.Qt.NoModifier)
made = [x for x in ed.sketch.entities.values() if x.kind == "ellipse"]
check("an ellipse 25 by 9", len(made) == 1 and abs(made[0].radius - 9) < 1e-6
      and abs(ed.sketch.ellipse_axes(made[0].id)[1] - 25) < 1e-6)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
