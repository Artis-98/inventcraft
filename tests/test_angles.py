"""Angles that read the corner you mean (card #336: "89 or 91").

A sketch's angle dimension between two lines used to measure between the
directions they were drawn in, so an 89 degree corner could read 91 and
nothing would turn it round.  Now the corner is the one between the arms
on the side the label is placed, and the constraint keeps to it.  Measure
gives the corner where two edges or faces meet, 0 to 180, and shows it
there in the view.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtWidgets                                     # noqa: E402

from datum.core import kernel                                     # noqa: E402
from datum.core.sketch import Constraint, Sketch, SketchPlane     # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-4):
    return abs(a - b) < tol


def corner_sketch(angle_deg):
    """Two lines meeting at the origin, both drawn toward it, opening at
    ``angle_deg``: the way that read the other angle before."""
    s = Sketch(SketchPlane(), "Corner")
    a = math.radians(angle_deg)
    first = s.add_line((100.0, 0.0), (0.0, 0.0))
    second = s.add_line((100.0 * math.cos(a), 100.0 * math.sin(a)),
                        (0.0, 0.0))
    return s, first, second


print("the constraint")
s, l1, l2 = corner_sketch(89.0)
plain = Constraint(id=1, kind="angle", entities=[l1, l2])
flipped = Constraint(id=2, kind="angle", entities=[l1, l2], flip=True)
check("measured between the drawn directions, the corner reads 89",
      near(s.measure(plain), 89.0) or near(s.measure(plain), 271.0),
      s.measure(plain))
check("turned, it is the angle beside it",
      near(s.measure(flipped) % 180.0, 91.0) or near(
          s.measure(flipped) % 180.0, 89.0), s.measure(flipped))
check("the flag is kept in the file, and only when set",
      Constraint.from_dict(flipped.to_dict()).flip
      and "flip" not in plain.to_dict())

# the solver holds a turned angle: 80 asked of the 91 beside an 89 corner
s, l1, l2 = corner_sketch(89.0)
p0 = s.entities[l1].points[0]
p1 = s.entities[l1].points[1]
s.points[p0].fixed = s.points[p1].fixed = True
s.add_constraint("coincident", points=[s.entities[l1].points[1],
                                       s.entities[l2].points[1]])
cid = s.add_constraint("angle", entities=[l1, l2], value=100.0)
s.constraints[cid].flip = True
s.solve()
check("a turned angle is held by the solver",
      near(s.measure(s.constraints[cid]), 100.0, 1e-3),
      s.measure(s.constraints[cid]))

print("placing the dimension picks the corner")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from datum.ui.main_window import MainWindow                       # noqa: E402

win = MainWindow()
editor = win.editor
for angle in (89.0, 91.0, 60.0, 135.0):
    s, l1, l2 = corner_sketch(angle)
    editor.sketch = s
    target = {"kind": "angle", "points": [], "entities": [l1, l2],
              "current": 0.0, "flip": False, "pair": (l1, l2)}
    a = math.radians(angle / 2.0)
    inside = (50.0 * math.cos(a), 50.0 * math.sin(a))
    editor._retarget_angle(target, inside)
    check("%g degree corner, label inside it: reads %g" % (angle, angle),
          near(target["current"], angle), target["current"])
    ghost = Constraint(id=9, kind="angle", entities=target["entities"],
                       flip=target["flip"])
    check("  and the constraint made from it measures the same",
          near(s.measure(ghost), angle), s.measure(ghost))
    # just above the first line run on past the corner: between the
    # second arm and that run on
    editor._retarget_angle(target, (-50.0, 1.0))
    check("  out past the other arm it reads the angle beside, %g"
          % (180 - angle), near(target["current"], 180.0 - angle),
          target["current"])
editor.sketch = None

print("Measure")
from datum.ui.measure import angle_detail                         # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge            # noqa: E402
from OCP.gp import gp_Pnt                                         # noqa: E402


def edge(a, b):
    return BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge()


for angle in (89.0, 91.0, 30.0):
    r = math.radians(angle)
    tip = (100 * math.cos(r), 100 * math.sin(r), 0.0)
    for e1, e2 in ((edge((100, 0, 0), (0, 0, 0)), edge(tip, (0, 0, 0))),
                   (edge((0, 0, 0), (100, 0, 0)), edge(tip, (0, 0, 0)))):
        found = angle_detail(e1, e2)
        check("two edges meeting at %g degrees read %g, however drawn"
              % (angle, angle), found and near(found[0], angle)
              and found[1] is not None, found)

block = kernel.box(100.0, 60.0, 40.0)
faces = kernel.faces(block)


def face_with(normal):
    from datum.core.constraints3d import frame_from_shape
    return next(f for f in faces
                if all(near(frame_from_shape(f).direction[i], normal[i])
                       for i in range(3)))


top, side, bottom = face_with((0, 0, 1)), face_with((1, 0, 0)), \
    face_with((0, 0, -1))
check("a box's top and side meet at 90",
      near(angle_detail(top, side)[0], 90.0))
check("its top and bottom face opposite ways, 180",
      near(angle_detail(top, bottom)[0], 180.0))
from OCP.TopAbs import TopAbs_EDGE                               # noqa: E402
from datum.ui.measure import _shared_edge                         # noqa: E402
ridge = _shared_edge(top, side)
from OCP.TopoDS import TopoDS                                 # noqa: E402
cut = kernel.chamfer(block, [TopoDS.Edge_s(ridge)], 10.0)
from datum.core.constraints3d import frame_from_shape             # noqa: E402
chamfer = next(f for f in kernel.faces(cut)
               if frame_from_shape(f) is not None
               and near(frame_from_shape(f).direction[0], math.sqrt(0.5),
                        1e-3))
new_top = next(f for f in kernel.faces(cut)
               if frame_from_shape(f) is not None
               and near(frame_from_shape(f).direction[2], 1.0))
check("a 45 degree chamfer meets the top at 135, as a protractor reads it",
      near(angle_detail(new_top, chamfer)[0], 135.0, 1e-3),
      angle_detail(new_top, chamfer))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
