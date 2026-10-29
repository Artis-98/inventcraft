"""Sheet metal, part two, held to Inventor's own numbers: Hem in its four
kinds, Fold, Contour Flange, Corner Seam, a STEP body converted from a
picked base face and laid flat, a sharp corner refused, and the Flat
Pattern's own feature, the Bend Perforation.

Every Inventor value was read from Inventor 2026 through its API
(inventor-explore/explore-sheetmetal3..6.ps1): a 100 x 60 plate, 2 mm
thick, bend radius 2 mm, K-factor 0.44, edited at its y = 0 edge.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox                   # noqa: E402

from datum.core import fileio, kernel, sheetmetal as sm            # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (                                 # noqa: E402
    ContourFlangeFeature, CornerSeamFeature, FlangeFeature, FoldFeature,
    HemFeature, ImportFeature, SheetFaceFeature, SketchFeature,
)
from datum.core.naming import RefSet                              # noqa: E402
from datum.core.sketch import STANDARD_PLANES, Sketch, SketchPlane  # noqa: E402

FAILS = []
T, R, K = 2.0, 2.0, 0.44
WORK = tempfile.mkdtemp(prefix="datum_sheet2_")


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
EDGE = top_edge(PLATE, y=0.0)

# ==========================================================================
print("Hem, all four kinds")

HEMS = {
    # (kind, first, second): (volume, flat width, height), Inventor's
    ("single", 1, 10): (13942.478, 69.335, 5.0),
    ("double", 1, 10): (15984.956, 79.171, 8.0),
    ("double", 1, 20): (19984.956, 99.171, 8.0),
    ("rolled", 3, 180): (13513.274, 67.189, 10.0),
    ("rolled", 3, 120): (12675.516, 63.126, 7.5),
    ("teardrop", 2, 250): (14282.835, 70.891, 8.0),
}
for (kind, a, b), (volume, flat_w, height) in HEMS.items():
    body = sm.hem(PLATE, EDGE, kind, T, a, b)
    box = kernel.bounding_box(body)
    flat = sm.unfold(body, K)
    label = "%s %g %g" % (kind, a, b)
    check("%s: Inventor's volume, %.3f" % (label, volume),
          near(kernel.volume(body), volume, 0.01), kernel.volume(body))
    check("%s: inside the plate, %g high" % (label, height),
          near(box[1], 0, 0.02) and near(box[4], 60, 0.02)
          and near(box[5], height, 0.02), [round(c, 3) for c in box])
    check("%s: lays flat at %.3f, in one piece" % (label, flat_w),
          near(min(flat.extents()), flat_w) and len(flat.faces) == 1,
          (flat.extents(), len(flat.faces)))
check("Inventor's defaults: gap and length from the thickness",
      sm.hem_defaults("single") == ("Thickness * 0.5", "Thickness * 4"))

# ==========================================================================
print("Fold")

body = sm.fold(PLATE, (0, 0, T), (0, 0, 1), (0, 30, T), (100, 30, T), T, R,
               90, K)
box = kernel.bounding_box(body)
check("Inventor's fold: volume 12037.699", near(kernel.volume(body),
                                                12037.699, 0.01))
check("and its box, 31.738 out and up",
      near(box[4], 31.738, 0.02) and near(box[5], 31.738, 0.02), box)
check("the flat is the sheet as it was, 100 x 60",
      sorted(round(c, 3) for c in sm.unfold(body, K).extents())
      == [60.0, 100.0])
down = sm.fold(PLATE, (0, 0, T), (0, 0, 1), (0, 30, T), (100, 30, T), T, R,
               45, K, flip_direction=True)
check("flipped, it goes down", kernel.bounding_box(down)[2] < -10)

# ==========================================================================
print("Contour Flange")


def xz(x, y):
    # Inventor's XZ sketch: its x is -X, its y is +Z
    return (-x, 0.0, y)


u = sm.contour_flange([xz(0, 30), xz(0, 0), xz(40, 0), xz(40, 30)], 100, T,
                      R)
box = kernel.bounding_box(u)
check("U: Inventor's volume, 20284.956", near(kernel.volume(u), 20284.956,
                                              0.01))
check("the thickness outside the path, as Inventor's",
      near(box[0], -42, 0.02) and near(box[3], 2, 0.02)
      and near(box[2], -2, 0.02), box)
check("U lays flat at 101.048", near(min(sm.unfold(u, K).extents()),
                                     100.0) and near(max(sm.unfold(
                                         u, K).extents()), 101.048))
ell = sm.contour_flange([xz(0, 30), xz(0, 0), xz(50, 0)], 100, T, R)
check("L: 16142.478 and flat 80.524",
      near(kernel.volume(ell), 16142.478, 0.01)
      and near(min(sm.unfold(ell, K).extents()), 80.524))

# ==========================================================================
print("Corner Seam")
for r in (1.0, 2.0, 4.0):
    for gap in (3.048, None):
        plate = BRepPrimAPI_MakeBox(100, 60, T).Shape()
        apart = sm.flange(plate, top_edge(plate, y=0.0), T, r, 90, 30)
        apart = sm.flange(apart, top_edge(apart, x=0.0), T, r, 90, 30)
        ea = edge_where(apart, lambda p: abs(p[0]) < 1e-9
                        and abs(p[1] - 2) < 1e-9)
        eb = edge_where(apart, lambda p: abs(p[0] - 2) < 1e-9
                        and abs(p[1] - (r + T)) < 1e-9)
        seamed = sm.corner_seam(apart, ea, eb, T, r, gap)
        together = sm.flanges(plate, [top_edge(plate, y=0.0),
                                      top_edge(plate, x=0.0)],
                              T, r, 90, 30, gap=gap)
        check("r %g gap %s: seamed is as one Flange on both makes it"
              % (r, gap), near(kernel.volume(seamed),
                               kernel.volume(together), 0.01),
              (kernel.volume(seamed), kernel.volume(together)))
apart = sm.flange(PLATE, EDGE, T, R, 90, 30)
apart = sm.flange(apart, top_edge(apart, x=0.0), T, R, 90, 30)
seamed = sm.corner_seam(
    apart,
    edge_where(apart, lambda p: abs(p[0]) < 1e-9 and abs(p[1] - 2) < 1e-9),
    edge_where(apart, lambda p: abs(p[0] - 2) < 1e-9 and abs(p[1] - 4) < 1e-9),
    T, R, 3.048)
check("and that is Inventor's corner seam, 20069.492",
      near(kernel.volume(seamed), 20069.492, 0.01), kernel.volume(seamed))

# ==========================================================================
print("a STEP body, converted from a picked base face, laid flat")

STEP_FLATS = {"bracket": 86.524, "channel": 113.048, "z45": 83.819}
bodies = {
    "bracket": sm.flange(PLATE, EDGE, T, R, 90, 30),
    "channel": sm.flanges(PLATE, [EDGE, top_edge(PLATE, y=60.0)], T, R, 90,
                          30),
    "z45": sm.flange(PLATE, EDGE, T, 5.0, 45, 25),
    "sharp": kernel.boolean(PLATE, BRepPrimAPI_MakeBox(100, 2, 30).Shape(),
                            "join"),
}
for name, body in bodies.items():
    path = os.path.join(WORK, name + ".stp")
    fileio.write_step(body, path)
    doc = Document()
    feature = ImportFeature()
    feature.path = path
    doc.add_feature(feature)
    doc.rebuild()
    top = max((f for f in kernel.faces(doc.shape)
               if sm._kind(f) == sm.GeomAbs_Plane
               and near(kernel.bounding_box(f)[2], T, 1e-6)
               and near(kernel.bounding_box(f)[5], T, 1e-6)),
              key=kernel.face_area)
    sm.convert(doc, base_face=top)
    check("%s: its thickness measured from the face, 2" % name,
          near(doc.parameter_scope()["Thickness"], 2.0, 1e-6))
    if name == "sharp":
        try:
            sm.flat_pattern(doc)
            check("a sharp corner is refused, as Inventor's is", False)
        except kernel.KernelError as exc:
            check("a sharp corner is refused, as Inventor's is",
                  "cannot be laid flat" in str(exc), str(exc))
        continue
    flat = sm.flat_pattern(doc)
    check("%s: flat %.3f, as Inventor lays the same STEP out"
          % (name, STEP_FLATS[name]),
          any(near(e, STEP_FLATS[name]) for e in flat.extents()),
          flat.extents())
    again = Document()
    again.load_dict(doc.to_dict())
    again.rebuild()
    check("%s: the base face is kept with the part" % name,
          again.sheet_metal.base and any(
              near(e, STEP_FLATS[name])
              for e in sm.flat_pattern(again).extents()))

# ==========================================================================
print("a bent part drawn as an ordinary part, with real arcs")

import math                                                        # noqa: E402
from datum.core.features import ExtrudeFeature                    # noqa: E402


def drawn_l(inner_centre=(4.0, 4.0), inner_radius=2.0):
    """An L drawn on YZ: outer bend radius 4, the inner one given, run
    100 along X, the same shape as the bracket above when concentric."""
    doc = Document()
    sk = SketchFeature(name="L")
    sk.sketch = s = Sketch(STANDARD_PLANES["YZ"], "L")
    cx, cy = inner_centre
    r = inner_radius
    s.add_line((60, 0), (4, 0))
    s.add_arc((4, 4), 4, math.radians(180), math.radians(270))
    s.add_line((0, 4), (0, 30))
    s.add_line((0, 30), (2, 30))
    s.add_line((2, 30), (cx - r, cy))
    s.add_arc((cx, cy), r, math.radians(180), math.radians(270))
    s.add_line((cx, cy - r), (60, 2))
    s.add_line((60, 2), (60, 0))
    doc.add_feature(sk)
    ex = ExtrudeFeature()
    ex.sketch_id = sk.id
    ex.distance = "100"
    doc.add_feature(ex)
    doc.rebuild()
    top = max((f for f in kernel.faces(doc.shape)
               if sm._kind(f) == sm.GeomAbs_Plane
               and abs(sm.face_normal(f, kernel.shape_centre(f))[2]) > 0.99),
              key=kernel.face_area)
    sm.convert(doc, base_face=top)
    return doc


doc = drawn_l()
check("its thickness found, 2", near(doc.parameter_scope()["Thickness"], 2))
check("laid flat at Inventor's 86.524 x 100",
      [round(c, 3) for c in sorted(sm.flat_pattern(doc).extents())]
      == [86.524, 100.0], sm.flat_pattern(doc).extents())
doc = drawn_l(inner_centre=(3.5, 3.5), inner_radius=1.5)
try:
    sm.flat_pattern(doc)
    check("a bend whose arcs do not share a centre is refused", False)
except kernel.KernelError as exc:
    check("a bend whose arcs do not share a centre is refused",
          "same centre" in str(exc), str(exc))

# ==========================================================================
print("the features in a part")


def plate_doc():
    doc = Document()
    sm.convert(doc)
    doc.params.set_expression("Thickness", "2")
    sk = SketchFeature(name="Sketch1")
    sk.sketch = Sketch(SketchPlane(), "Sketch1")
    sk.sketch.add_rectangle((0.0, 0.0), (100.0, 60.0))
    doc.add_feature(sk)
    face = SheetFaceFeature()
    face.sketch_id = sk.id
    doc.add_feature(face)
    doc.rebuild()
    return doc


doc = plate_doc()
hem = HemFeature()
hem.edges.capture_from(doc.shape, "edge", [top_edge(doc.shape, y=0.0)])
hem.first, hem.second = "1", "10"
doc.add_feature(hem)
report = doc.rebuild()
check("Hem builds in a part, as Inventor's",
      report.ok and near(kernel.volume(doc.shape), 13942.478, 0.01),
      report.message)

doc = plate_doc()
sk = SketchFeature(name="Fold line")
sk.sketch = Sketch(SketchPlane((0.0, 0.0, 2.0), (0.0, 0.0, 1.0)), "Fold line")
line = sk.sketch.add_line((0.0, 30.0), (100.0, 30.0))
doc.add_feature(sk)
fold = FoldFeature()
fold.sketch_id = sk.id
fold.line = line
doc.add_feature(fold)
report = doc.rebuild()
check("Fold builds in a part, as Inventor's",
      report.ok and near(kernel.volume(doc.shape), 12037.699, 0.01),
      report.message)
doc.sheet_metal.k_factor = "0.3"
doc.rebuild()
check("and follows the part's K-factor",
      not near(kernel.volume(doc.shape), 12037.699, 0.01)
      and near(min(sm.flat_pattern(doc).extents()), 60.0))

doc = Document()
sm.convert(doc)
doc.params.set_expression("Thickness", "2")
sk = SketchFeature(name="Path")
sk.sketch = Sketch(STANDARD_PLANES["XZ"], "Path")
sk.sketch.add_line((0.0, 30.0), (0.0, 0.0))
sk.sketch.add_line((0.0, 0.0), (40.0, 0.0))
sk.sketch.add_line((40.0, 0.0), (40.0, 30.0))
doc.add_feature(sk)
contour = ContourFlangeFeature()
contour.sketch_id = sk.id
contour.width = "100"
doc.add_feature(contour)
report = doc.rebuild()
check("Contour Flange builds in a part, as Inventor's",
      report.ok and near(kernel.volume(doc.shape), 20284.956, 0.01),
      report.message)

doc = plate_doc()
first = FlangeFeature()
first.edges.capture_from(doc.shape, "edge", [top_edge(doc.shape, y=0.0)])
first.height = "30"
doc.add_feature(first)
doc.rebuild()
second = FlangeFeature()
second.edges.capture_from(doc.shape, "edge", [top_edge(doc.shape, x=0.0)])
second.height = "30"
doc.add_feature(second)
doc.rebuild()
seam = CornerSeamFeature()
seam.edges.capture_from(doc.shape, "edge", [
    edge_where(doc.shape, lambda p: abs(p[0]) < 1e-9 and abs(p[1] - 2) < 1e-9),
    edge_where(doc.shape, lambda p: abs(p[0] - 2) < 1e-9
               and abs(p[1] - 4) < 1e-9)])
doc.add_feature(seam)
report = doc.rebuild()
together = sm.flanges(PLATE, [EDGE, top_edge(PLATE, x=0.0)], T, R, 90, 30)
check("Corner Seam builds in a part",
      report.ok and near(kernel.volume(doc.shape), kernel.volume(together),
                         0.01), report.message)

# ==========================================================================
print("the Flat Pattern's own feature: Bend Perforation")

doc = plate_doc()
flange = FlangeFeature()
flange.edges.capture_from(doc.shape, "edge", [top_edge(doc.shape, y=0.0)])
flange.height = "30"
doc.add_feature(flange)
doc.rebuild()
plain = sm.flat_pattern(doc)
for style in ("zigzag", "straight"):
    doc.sheet_metal.flat_features = [sm.FlatFeature(style=style)]
    flat = sm.flat_pattern(doc)
    loops = kernel.explore(flat.outline(), kernel.TopAbs_WIRE)
    check("%s: slots down the bend, the sheet still one piece" % style,
          len(flat.faces) == 1 and len(loops) > 1, (len(flat.faces),
                                                    len(loops)))
    check("%s: the flat is the same size" % style,
          [round(c, 3) for c in flat.extents()]
          == [round(c, 3) for c in plain.extents()])
    path = sm.flat_to_dxf(flat, os.path.join(WORK, style + ".dxf"))
    check("%s: the slots go into the DXF" % style,
          open(path).read().count("OUTER_PROFILE") > 8)
doc.sheet_metal.flat_features = [sm.FlatFeature(bridge="200")]
flat = sm.flat_pattern(doc)
check("bridges longer than the bend leave a single slot",
      len(kernel.explore(flat.outline(), kernel.TopAbs_WIRE)) == 2)
doc.sheet_metal.flat_features = [sm.FlatFeature(bends="5")]
sm.flat_pattern(doc)
check("a bend that is not there is said, not a crash",
      "no bend 5" in doc.sheet_metal.flat_features[0].error,
      doc.sheet_metal.flat_features[0].error)
again = Document()
doc.sheet_metal.flat_features = [sm.FlatFeature(style="straight",
                                                slot="15")]
again.load_dict(doc.to_dict())
check("saved with the part", again.sheet_metal.flat_features[0].slot == "15"
      and again.sheet_metal.flat_features[0].style == "straight")

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
