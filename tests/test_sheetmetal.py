"""Sheet metal, held to Inventor's own numbers.

Every expected value below was read from Inventor 2026 through its API
(inventor-explore/explore-sheetmetal2.ps1): the same 100 x 60 plate, 2 mm
thick, bend radius 2 mm, K-factor 0.44, flanged 30 mm high from its edge,
with Inventor's default Bend Position, inside the base face's extents.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox                   # noqa: E402

from datum.core import kernel, sheetmetal as sm                   # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (                                 # noqa: E402
    FlangeFeature, SheetFaceFeature, SketchFeature,
)
from datum.core.naming import RefSet                              # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402

FAILS = []
T, R, K = 2.0, 2.0, 0.44


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


def edge_where(shape, test):
    for e in kernel.explore(shape, kernel.TopAbs_EDGE):
        if sm._is_line(e) and all(test(p) for p in sm._edge_ends(e)):
            return e
    return None


def top_edge(shape, y=None, x=None, z=T):
    return edge_where(shape, lambda p: abs(p[2] - z) < 1e-9 and (
        (y is not None and abs(p[1] - y) < 1e-9)
        or (x is not None and abs(p[0] - x) < 1e-9)))


PLATE = BRepPrimAPI_MakeBox(100, 60, T).Shape()

# ==========================================================================
print("a flange, as Inventor makes it")

INVENTOR = {
    # angle: (y min, y max, z max, flat width), Inventor 2026
    90: (0.0, 60.0, 30.0, 86.524),
    45: (-21.213, 60.0, 22.627, 88.948),
    135: (5.657, 60.0, 21.213, 77.472),
}
for angle, (ylo, yhi, ztop, flat_w) in INVENTOR.items():
    body = sm.flange(PLATE, top_edge(PLATE, y=0.0), T, R, angle, 30.0)
    box = kernel.bounding_box(body)
    check("%d deg: one valid solid" % angle,
          kernel.BRepCheck_Analyzer(body).IsValid()
          and len(kernel.explore(body, kernel.TopAbs_SOLID)) == 1)
    check("%d deg: where Inventor puts it" % angle,
          near(box[1], ylo, 0.02) and near(box[4], yhi, 0.02)
          and near(box[5], ztop, 0.02),
          [round(c, 3) for c in box])
    flat = sm.unfold(body, K)
    w, l = sorted(flat.extents())
    check("%d deg: flat %.3f x 100, as Inventor's" % (angle, flat_w),
          near(w, flat_w) and near(l, 100.0), (w, l))
    check("%d deg: one outline, one bend at %d" % (angle, angle),
          len(flat.faces) == 1 and len(flat.bends) == 1
          and near(flat.bends[0][2], angle, 1e-6))

print("a U channel")
channel = sm.flanges(PLATE, [top_edge(PLATE, y=0.0), top_edge(PLATE, y=60.0)],
                     T, R, 90, 30)
w, l = sm.unfold(channel, K).extents()
check("flat 113.048 x 100, as Inventor's", near(w, 113.048) and near(l, 100),
      (w, l))

print("the bend's own length, worked by hand")
ba = (math.pi / 2) * (R + K * T)
check("90 deg bend lays out at (r + K t) x angle",
      near(86.524, 60 - (R + T) + (30 - (R + T)) + ba))

print("from the adjacent face: the base is left whole")
body = sm.flange(PLATE, top_edge(PLATE, y=0.0), T, R, 90, 30.0,
                 position=sm.ADJACENT)
box = kernel.bounding_box(body)
check("the wall stands outside the edge", near(box[1], -(R + T), 0.02), box)
w, l = sm.unfold(body, K).extents()
check("so the flat is the plate and all the flange",
      near(w, 60 + (30 - (R + T)) + ba), w)

print("flipped: the wall goes down")
body = sm.flange(PLATE, top_edge(PLATE, y=0.0), T, R, 90, 30.0, flip=True)
box = kernel.bounding_box(body)
check("below the plate", near(box[2], -(30 - T), 0.02), box)
check("and lays out the same", near(sorted(sm.unfold(body, K).extents())[0],
                                    86.524))

print("a flange on a flange")
lip_edge = edge_where(channel, lambda p: abs(p[2] - 30) < 1e-9
                      and abs(p[1]) < 1e-9)
lipped = sm.flange(channel, lip_edge, T, R, 90, 10.0)
flat = sm.unfold(lipped, K)
check("three bends, one outline", len(flat.bends) == 3
      and len(flat.faces) == 1, (len(flat.bends), len(flat.faces)))

print("a tray: four flanges stopping short at the corners")
edges = [top_edge(PLATE, y=0.0), top_edge(PLATE, y=60.0),
         top_edge(PLATE, x=0.0), top_edge(PLATE, x=100.0)]
tray = sm.flanges(PLATE, edges, T, R, 90, 20.0)
check("one valid solid", kernel.BRepCheck_Analyzer(tray).IsValid()
      and len(kernel.explore(tray, kernel.TopAbs_SOLID)) == 1)
flat = sm.unfold(tray, K)
check("one outline with four bends", len(flat.faces) == 1
      and len(flat.bends) == 4, (len(flat.faces), len(flat.bends)))
check("the flat is the plate and four walls laid out",
      near(flat.extents()[0], 100 - 2 * (R + T) + 2 * (20 - (R + T))
           + 2 * ba) or near(flat.extents()[1], 100 - 2 * (R + T)
                             + 2 * (20 - (R + T)) + 2 * ba),
      flat.extents())

print("two flanges at a corner, against Inventor's own")
# Inventor 2026, inventor-explore/explore-sheetmetal-corner3.ps1: one
# Flange on two edges meeting at a corner, 30 high.  Its gap there was its
# inch template's style thickness, 0.120 in, so that is the gap given here.
CORNERS = {(2, 2): (20069.492, 126.524), (2, 4): (19757.873, 125.665),
           (3, 3): (29144.093, 124.786), (2, 1): (20202.325, 126.953),
           (1, 2): (10282.153, 127.833)}
for (t, r), (volume, flat_l) in CORNERS.items():
    plate = BRepPrimAPI_MakeBox(100, 60, t).Shape()
    body = sm.flanges(plate, [top_edge(plate, y=0.0, z=t),
                              top_edge(plate, x=0.0, z=t)],
                      t, r, 90, 30, gap=3.048)
    flat = sm.unfold(body, K)
    check("t %g r %g: Inventor's volume, %.3f" % (t, r, volume),
          near(kernel.volume(body), volume, 0.01), kernel.volume(body))
    check("t %g r %g: and its flat, %.3f long, in one piece" % (t, r, flat_l),
          near(max(flat.extents()), flat_l) and len(flat.faces) == 1,
          (flat.extents(), len(flat.faces)))

print("the flat pattern to DXF")
path = sm.flat_to_dxf(sm.unfold(sm.flange(PLATE, top_edge(PLATE, y=0.0), T, R,
                                          90, 30), K),
                      os.path.join(tempfile.mkdtemp(), "flat.dxf"))
text = open(path).read()
check("four sides on OUTER_PROFILE and a bend on BEND_CENTERLINE",
      text.count("\nLINE\n") == 5 and "BEND_CENTERLINE" in text
      and "OUTER_PROFILE" in text)

# ==========================================================================
print("a part converted to sheet metal")

doc = Document()
sm.convert(doc)
check("it gains Sheet Metal Defaults", doc.sheet_metal is not None)
check("and Inventor's default thickness, 0.5 mm, as Thickness",
      near(doc.parameter_scope()["Thickness"], 0.5))
check("BendRadius is the thickness",
      near(doc.parameter_scope()["BendRadius"], 0.5))
doc.params.set_expression("Thickness", "2")
sk = SketchFeature(name="Sketch1")
sk.sketch = Sketch(SketchPlane(), "Sketch1")
sk.sketch.add_rectangle((0.0, 0.0), (100.0, 60.0))
doc.add_feature(sk)
face = SheetFaceFeature()
face.sketch_id = sk.id
doc.add_feature(face)
report = doc.rebuild()
check("a Face is the profile, Thickness thick", report.ok and near(
    kernel.bounding_box(doc.shape)[5], 2.0, 0.02), report.message)
flange = FlangeFeature()
flange.edges = RefSet()
flange.edges.capture_from(doc.shape, "edge", [top_edge(doc.shape, y=0.0)])
flange.height = "30"
doc.add_feature(flange)
report = doc.rebuild()
check("a Flange builds", report.ok, report.message)
w, l = sm.flat_pattern(doc).extents()
check("and the part lays flat as Inventor's does", near(w, 86.524)
      and near(l, 100.0), (w, l))
doc.params.set_expression("Thickness", "3")
report = doc.rebuild()
check("a new thickness flows through every feature", report.ok and near(
    kernel.bounding_box(doc.shape)[5], 30.0, 0.02)
    and near(sm.unfold(doc.shape, K).thickness, 3.0, 1e-4), report.message)
data = doc.to_dict()
again = Document()
again.load_dict(data)
check("saved and loaded, still sheet metal",
      again.sheet_metal is not None and again.rebuild().ok)
sm.convert_to_standard(again)
check("Convert to Standard Part keeps the features",
      again.sheet_metal is None and again.rebuild().ok
      and len(again.features) == len(doc.features))

print("an existing plate converts at its own thickness")
plain = Document()
sk = SketchFeature(name="Sketch1")
sk.sketch = Sketch(SketchPlane(), "Sketch1")
sk.sketch.add_rectangle((0.0, 0.0), (50.0, 40.0))
plain.add_feature(sk)
from datum.core.features import ExtrudeFeature                    # noqa: E402
ex = ExtrudeFeature()
ex.sketch_id = sk.id
ex.distance = "1.5"
plain.add_feature(ex)
plain.rebuild()
sm.convert(plain)
check("Thickness is 1.5", near(plain.parameter_scope()["Thickness"], 1.5),
      plain.parameter_scope().get("Thickness"))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
