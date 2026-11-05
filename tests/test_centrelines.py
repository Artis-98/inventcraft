"""Automated Centerlines, as Inventor's: a centre mark on every hole seen
end on, one centre line down a shaft of several diameters seen side on."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse    # noqa: E402
from OCP.BRepPrimAPI import (                                    # noqa: E402
    BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder)
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt                        # noqa: E402

from datum.core import hlr, views                                # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def cyl(x, y, z, r, h, d=(0, 0, 1)):
    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(x, y, z), gp_Dir(*d)), r, h).Shape()


plate = BRepPrimAPI_MakeBox(60, 40, 10).Shape()
for x in (15, 45):
    plate = BRepAlgoAPI_Cut(plate, cyl(x, 20, -1, 4, 12)).Shape()
top = hlr.ORIENTATIONS["top"]
projection = hlr.project(plate, *top)
marks, lines = views.centre_features(plate, *top, projection.centre)
check("two holes seen from above, two centre marks", len(marks) == 2, marks)
check("30 mm apart, as the holes are",
      len(marks) == 2 and abs(abs(marks[0][0][0] - marks[1][0][0]) - 30) < 1e-6)
check("each reaching past its hole", all(abs(m[1] - 6.0) < 1e-6 for m in marks))

shaft = BRepAlgoAPI_Fuse(cyl(0, 0, 0, 10, 30, (1, 0, 0)),
                         cyl(30, 0, 0, 6, 20, (1, 0, 0))).Shape()
front = hlr.ORIENTATIONS["front"]
projection = hlr.project(shaft, *front)
marks, lines = views.centre_features(shaft, *front, projection.centre)
check("a stepped shaft from the side: one centre line", len(lines) == 1, lines)
check("down its whole length and a little past",
      len(lines) == 1 and abs(abs(lines[0][1][0] - lines[0][0][0]) - 54) < 1e-6,
      lines)
check("and no centre marks", not marks)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
