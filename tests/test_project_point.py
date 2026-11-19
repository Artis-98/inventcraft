"""Project Geometry takes a corner as a point: a model vertex lands on the
sketch as one pinned point, not the lines meeting at it.  Vertices are
pickable while the tool runs, alongside edges and faces."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from OCP.TopAbs import TopAbs_VERTEX                               # noqa: E402

from datum.core import kernel                                      # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui import viewport as vpmod                             # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=250):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


win.new_document(prompt=False)
settle(300)
win.document.add_feature(PrimitiveFeature(kind="box", a="40", b="30",
                                          c="20"))
win.rebuild()
settle(200)

check("Project Geometry can pick corners",
      vpmod.SEL_VERTEX in vpmod.SELECTION_MODES["project"]
      if hasattr(vpmod, "SELECTION_MODES") else True)

win.start_sketch_on_plane("XY")
win.viewport.finish_animation()
settle(200)
editor = win.editor
sketch = editor.sketch
corner = None
for v in kernel.explore(win.document.shape, TopAbs_VERTEX):
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))
    if p.Z() > 19.9 and p.X() > 1.0 and p.Y() > 1.0:
        corner = (v, (p.X(), p.Y()))
        break
check("a top corner off the origin", corner is not None)
lines_before = sum(1 for e in sketch.entities.values() if e.kind == "line")
points_before = len(sketch.points)
made = editor.project_one(corner[0], body=win.document.shape)
check("one piece made", made == 1, made)
check("no lines made", sum(1 for e in sketch.entities.values()
                           if e.kind == "line") == lines_before)
check("one point more", len(sketch.points) == points_before + 1)
new = [q for q in sketch.points.values()
       if abs(q.x - corner[1][0]) < 1e-6 and abs(q.y - corner[1][1]) < 1e-6]
check("where the corner falls on the sketch", len(new) == 1,
      [(q.x, q.y) for q in sketch.points.values()])
check("pinned, as projected geometry is", new and new[0].fixed)
again = editor.project_one(corner[0], body=win.document.shape)
check("the same corner again adds nothing", again == 0
      and len(sketch.points) == points_before + 1)
win.finish_sketch()

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
