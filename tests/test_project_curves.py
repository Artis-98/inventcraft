"""Projected geometry is continuous: arcs, lines or one spline each.

Projecting a face with fillets onto a sketch used to bring every edge
that was not a plain line or a circle facing the sketch in as a run of
short lines: a fillet came in as twenty segments with nineteen corners
nobody drew. Every edge now comes in as one entity: a line when it is
straight, an arc or circle when its shadow is round, else one spline
that stays within a thousandth of a millimetre of it.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATUM_NO_WORKERS"] = "1"

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge           # noqa: E402
from OCP.GC import GC_MakeArcOfCircle                            # noqa: E402
from OCP.GeomAPI import GeomAPI_PointsToBSpline                  # noqa: E402
from OCP.GeomConvert import GeomConvert                          # noqa: E402
from OCP.TColgp import TColgp_Array1OfPnt                        # noqa: E402
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt               # noqa: E402

from datum.core import kernel                                    # noqa: E402
from datum.core.features import cast_onto                        # noqa: E402
from datum.core.sketch import STANDARD_PLANES, Sketch            # noqa: E402

FAILS = []
XY = STANDARD_PLANES["XY"]


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def kinds(shape, plane=XY):
    return [k for k, _d in kernel.project_to_plane(shape, plane)]


print("a circle stored as a B-spline, as fillets often are")
arc = GC_MakeArcOfCircle(gp_Circ(gp_Ax2(gp_Pnt(5, 5, 0), gp_Dir(0, 0, 1)),
                                 7.0), 0.3, 1.9, True).Value()
as_spline = GeomConvert.CurveToBSplineCurve_s(arc)
edge = BRepBuilderAPI_MakeEdge(as_spline).Edge()
out = kernel.project_to_plane(edge, XY)
check("comes in as one arc", [k for k, _ in out] == ["arc"], out[:1])
if out and out[0][0] == "arc":
    (cx, cy), r, a0, a1 = out[0][1]
    check("of the right size and place", abs(r - 7.0) < 1e-6
          and math.dist((cx, cy), (5, 5)) < 1e-6, out[0][1])

print("a free curve")
arr = TColgp_Array1OfPnt(1, 5)
for i, (x, y) in enumerate([(0, 0), (10, 6), (20, -4), (30, 3), (40, 0)],
                           start=1):
    arr.SetValue(i, gp_Pnt(x, y, 0))
free = BRepBuilderAPI_MakeEdge(GeomAPI_PointsToBSpline(arr).Curve()).Edge()
out = kernel.project_to_plane(free, XY)
check("one spline, not a run of lines", [k for k, _ in out] == ["spline"],
      [k for k, _ in out])
if out and out[0][0] == "spline":
    pts = out[0][1]
    check("from its very start to its very end",
          math.dist(pts[0], (0, 0)) < 1e-9
          and math.dist(pts[-1], (40, 0)) < 1e-9)

print("a circle seen at a slant")
tilted = BRepBuilderAPI_MakeEdge(gp_Circ(
    gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, math.sin(0.5), math.cos(0.5))),
    10.0)).Edge()
check("one closed spline", kinds(tilted) == ["spline"], kinds(tilted))

print("a filleted body's face")
a = kernel.cylinder(20.0, 10.0)
b = kernel.cylinder(12.0, 10.0, origin=(-18.0, 16.0, 0.0))
body = kernel.fuse_all([a, b])
from OCP.BRepAdaptor import BRepAdaptor_Curve              # noqa: E402
from OCP.GeomAbs import GeomAbs_CurveType                    # noqa: E402
upright = [e for e in kernel.edges(body) if BRepAdaptor_Curve(e).GetType()
           == GeomAbs_CurveType.GeomAbs_Line]
rounded = kernel.fillet(body, upright, 2.0)
top = max(kernel.faces(rounded), key=lambda f: kernel.shape_centre(f)[2])
found = kinds(top)
check("nothing comes in as a run of lines", "polyline" not in found
      and found.count("line") == 0, found)
check("an entity an edge", len(found) == len(kernel.edges(top)),
      (len(found), len(kernel.edges(top))))

print("onto a sketch")
sketch = Sketch(XY, "S")
record = cast_onto(sketch, top)
made = [sketch.entities[e].kind for e in record.entities]
check("arcs and splines, pinned", all(k in ("arc", "circle", "spline")
                                      for k in made), made)
regions = kernel.sketch_regions(sketch)
check("and they still close into one profile", len(regions) == 1,
      len(regions))

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
