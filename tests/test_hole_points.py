"""Hole goes on sketch points, not only circles: a sketch of points made
for the holes drills every one, a click on one in the view drops it, and
a part of several solids says which solids the holes go through."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                    # noqa: E402

from datum.core import kernel                                   # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.features import (                               # noqa: E402
    NEW_BODY, HoleFeature, PrimitiveFeature, SketchFeature, hole_centres)
from datum.core.sketch import Sketch, SketchPlane               # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_hole_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def plate(doc, x, name):
    box = PrimitiveFeature()
    box.kind = "box"
    box.a, box.b, box.c = "60", "40", "10"
    box.origin = [x, 0, 0]
    box.operation, box.body_name = NEW_BODY, name
    doc.add_feature(box)


print("the centres a sketch offers")
s = Sketch(SketchPlane(), "s")
lone = s.add_point(10.0, 10.0)
s.add_line((0.0, 0.0), (5.0, 0.0))
circle = s.add_circle((30.0, 20.0), 2.0)
offered = hole_centres(s)
check("a point on its own and a circle's centre are offered",
      offered.get(lone) == "point"
      and offered.get(s.entities[circle].points[0]) == "circle", offered)
check("a line's ends are not", len(offered) == 2, offered)
line = next(e for e in s.entities.values() if e.kind == "line")
s.remove_entity(line.id)
check("deleting a line leaves the points placed on their own",
      lone in s.points)

print("a sketch of points drills every one")
doc = Document()
plate(doc, 0, "Left")
plate(doc, 100, "Right")
sk = SketchFeature(name="Holes")
sk.sketch = Sketch(SketchPlane((0.0, 0.0, 10.0)), "Holes")
for x, y in ((10, 10), (50, 10), (110, 10), (150, 30)):
    sk.sketch.add_point(float(x), float(y))
doc.add_feature(sk)
hole = HoleFeature(name="Hole")
hole.sketch_id, hole.diameter = sk.id, "4"
doc.add_feature(hole)
doc.rebuild()
full = 2 * 60 * 40 * 10
check("four points, four holes", abs(kernel.volume(doc.shape) - (
    full - 4 * 3.14159265 * 4 * 10)) < 1, kernel.volume(doc.shape))
hole.solids = ["Left"]
doc.rebuild()
check("only through the solids it is told", abs(kernel.volume(doc.shape) - (
    full - 2 * 3.14159265 * 4 * 10)) < 1, kernel.volume(doc.shape))
hole.solids = []
path = os.path.join(WORK, "holes.pdat")
doc.remove_feature(hole.id)
doc.rebuild()
doc.save(path)

print("in the dialog")
from datum.ui.main_window import MainWindow                     # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def settle(ms=200):
    end = QtCore.QTime.currentTime().addMSecs(ms)
    while QtCore.QTime.currentTime() < end:
        app.processEvents()


win = MainWindow()
win.resize(1400, 900)
win.show()
win.open_path(path)
settle(900)
win.viewport.set_view("top")
win.viewport.finish_animation()
win.viewport.fit_all()
settle(300)
win.new_feature(HoleFeature)
settle(500)
dialog = win._active_dialog
check("every point is drawn in the view", len(dialog._marks) == 4,
      len(dialog._marks))
check("the Solids pick is offered", dialog.solids is not None)
sketch = dialog._sketch_now()
pid = next(p for p in hole_centres(sketch)
           if abs(sketch.points[p].x - 150) < 1e-6)
x, y = win.viewport.project(sketch.plane.to_3d(150.0, 30.0))
for kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
    QtWidgets.QApplication.sendEvent(win.viewport, QtGui.QMouseEvent(
        kind, QtCore.QPointF(x, y), QtCore.QPointF(x, y),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
settle(300)
check("a click on a point drops it", pid not in dialog._drilled()
      and len(dialog._drilled()) == 3, dialog._drilled())
dialog.commit()
settle(400)
made = next(f for f in win.document.features if isinstance(f, HoleFeature))
check("three holes made", abs(kernel.volume(win.document.shape) - (
    full - 3 * 3.14159265 * 6.25 * 10)) < 1, kernel.volume(win.document.shape))
check("and the points go from the view with it", not dialog._marks)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
