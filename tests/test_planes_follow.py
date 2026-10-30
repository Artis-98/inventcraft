"""Sketches follow the planes they are on, projections follow the sketches
they came from, and one Work Plane command works a plane out from what is
picked: two lines, three points, a line and a point, or a line at an angle
to a plane.

From a real table skeleton: a work plane offset half the table's depth
off XZ, a sketch of the legs on it, and the sketch staying behind when the
depth changed, with its projected line too.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core.document import Document                         # noqa: E402
from datum.core.features import (                                # noqa: E402
    SketchFeature, WorkPlaneFeature)
from datum.core.sketch import Sketch, SketchPlane                # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_planes_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


def table():
    """The table's top as a rectangle on XY, a work plane half its depth
    off XZ, and a sketch of two legs on that plane with the XY plane's
    line projected onto it."""
    doc = Document()
    top = SketchFeature(name="Top")
    top.sketch = Sketch(SketchPlane(), "Top")
    top.sketch.add_rectangle((-350.0, -250.0), (350.0, 250.0))
    doc.add_feature(top)
    doc.params.add("depth", "500")
    wp = WorkPlaneFeature(name="Front")
    wp.base, wp.offset = "XZ", "depth/2"
    doc.add_feature(wp)
    doc.rebuild()
    legs = SketchFeature(name="Legs")
    legs.sketch = Sketch(SketchPlane(doc.planes["Front"].origin,
                                     doc.planes["Front"].normal,
                                     doc.planes["Front"].xdir, "Front"),
                         "Legs")
    legs.sketch.add_line((-300.0, 0.0), (-300.0, 700.0))
    legs.sketch.add_line((300.0, 0.0), (300.0, 700.0))
    doc.add_feature(legs)
    doc.rebuild()
    return doc, top, wp, legs


print("a sketch follows its plane")
doc, top, wp, legs = table()
legs.plane_ref = "Front"
doc.set_parameter("depth", "800")
doc.rebuild()
y = legs.sketch.plane.origin[1]
check("the depth from 500 to 800: the legs' sketch moves with its plane",
      near(abs(y), 400.0), y)
saved = doc.save(os.path.join(WORK, "kept"))
again = Document.load(saved)
again.rebuild()
check("and keeps its plane through a save",
      next(f for f in again.features if f.name == "Legs").plane_ref
      == "Front")

print("a sketch from before keeps its plane")
doc, top, wp, legs = table()
check("a sketch from before has no plane kept", legs.plane_ref == "Front"
      or legs.sketch.plane.name == "Front")
doc.set_parameter("depth", "800")
doc.rebuild()
check("it is found by the plane's name, and follows it",
      legs.plane_ref == "Front"
      and near(abs(legs.sketch.plane.origin[1]), 400.0),
      (legs.plane_ref, legs.sketch.plane.origin))

print("a projection follows the sketch it came from")
doc, top, wp, legs = table()
s = legs.sketch
# the top's front edge, cast onto the legs' sketch, as Project Geometry
# with no source used to leave it
front = next(eid for eid, e in top.sketch.entities.items()
             if all(near(top.sketch.points[p].y, -250.0) for p in e.points))
ends = [top.sketch.plane.to_3d(top.sketch.points[p].x,
                               top.sketch.points[p].y)
        for p in top.sketch.entities[front].points]
flat = [s.plane.to_2d(p) for p in ends]
line = s.add_line(flat[0], flat[1])
for pid in s.entities[line].points:
    s.points[pid].fixed = True
s.add_projection({}, [line])
doc.rebuild()
record = s.projections[0]
check("one made with no source is tied to the line it lies on",
      record.source == {"sketch": top.id, "entity": front}, record.source)
for point in top.sketch.points.values():
    if near(point.x, 350.0):
        point.x = 500.0
doc.rebuild()
xs = sorted(s.points[p].x for p in s.entities[line].points)
check("the top made wider: the projected line goes with it",
      near(xs[1], 500.0), xs)

print("Work Plane from picks")
doc, top, wp, legs = table()
t = top.sketch
bottom, right, upper, left = [eid for eid in t.entities
                              if t.entities[eid].kind == "line"][:4]
corner = [t.entities[bottom].points[0], t.entities[bottom].points[1],
          t.entities[right].points[1]]
leg = next(iter(legs.sketch.entities))
cases = [
    ("two_lines", [{"sketch": top.id, "entity": bottom},
                   {"sketch": top.id, "entity": upper}], (0, 0, 1)),
    ("three_points", [{"sketch": top.id, "point": p} for p in corner],
     (0, 0, 1)),
    ("line_point", [{"sketch": top.id, "entity": bottom},
                    {"sketch": top.id, "point": corner[1]}], (1, 0, 0)),
    ("line_plane", [{"sketch": top.id, "entity": bottom}, {"plane": "XY"}],
     (0, -1, 0)),
    # a leg at the front and the top's back edge: skew, no plane holds both
    ("two_lines", [{"sketch": top.id, "entity": upper},
                   {"sketch": legs.id, "entity": leg}], None),
]
made = []
for i, (mode, refs, _n) in enumerate(cases):
    plane = WorkPlaneFeature(name="P%d" % i)
    plane.mode, plane.refs, plane.offset, plane.angle = mode, refs, "0", "90"
    doc.add_feature(plane)
    made.append(plane)
report = doc.rebuild()
for (mode, refs, normal), plane in zip(cases[:4], made):
    n = doc.planes[plane.name].normal
    check("%s makes the plane it should" % mode,
          all(near(abs(a), abs(b)) for a, b in zip(n, normal)), n)
check("two lines that do not lie in one plane are told, not guessed",
      any("do not lie in one plane" in m for _i, m in report.errors),
      report.errors)
xs_before = doc.planes["P2"].origin[0]
for point in t.points.values():
    if near(point.x, 350.0):
        point.x = 450.0
doc.rebuild()
check("the plane square to a line through its corner follows the corner",
      near(doc.planes["P2"].origin[0] - xs_before, 100.0),
      doc.planes["P2"].origin)
again = Document.load(doc.save(os.path.join(WORK, "planes")))
again.rebuild()
check("planes from picks keep what they were made from through a save",
      [(f.mode, f.refs) for f in again.features
       if isinstance(f, WorkPlaneFeature) and f.mode != "offset"]
      == [(f.mode, f.refs) for f in made])

print("in the window")
from datum.ui.main_window import MainWindow                      # noqa: E402

app = QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1400, 900)
win.show()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


doc, top, wp, legs = table()
path = doc.save(os.path.join(WORK, "table"))
win.open_path(path)
settle(900)
win.viewport.set_view("iso")
settle(500)
win.viewport.finish_animation()
win.start_sketch_on_plane("Front")
settle(900)
win.viewport.finish_animation()
d = win.viewport.view.Camera().Direction()
check("a sketch started on a plane away from the origin, in a part with no "
      "solid, is looked at square on",
      near(abs(d.Y()), 1.0, 1e-9) and near(d.X(), 0.0, 1e-9),
      (d.X(), d.Y(), d.Z()))
sketch = win.document.features[-1]
check("and keeps that plane", sketch.plane_ref == "Front")
editor = win.editor
snaps = [snap for snap in editor._model_snap_points() if snap[4]]
check("the other sketches' ends and middles are there to snap to",
      len(snaps) >= 12 and {snap[0] for snap in snaps} >= {"corner", "mid"},
      len(snaps))
leg_end = next(i for i, snap in enumerate(editor._model_snap_points())
               if snap[4] and snap[4]["sketch"] == legs.id
               and snap[0] == "corner")
editor.begin_change()
target = editor._take_model_snap(leg_end)
record = editor.sketch.projections[-1]
check("taking one projects its line as construction, tied to it",
      target is not None and record.construction
      and record.source.get("sketch") == legs.id, record.source)
win.finish_sketch()
settle(300)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
