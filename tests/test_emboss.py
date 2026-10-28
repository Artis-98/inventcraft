"""Text in sketches, and Emboss (GitHub #12).

Text is a closed profile like any other: one region for the whole of it,
saved and loaded, extruded.  Emboss raises a profile out of a face or
engraves it in, on a flat face, cast onto a cylinder, or wrapped round it.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel                                     # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (                                 # noqa: E402
    JOIN, EmbossFeature, ExtrudeFeature, Feature, PrimitiveFeature,
    SketchFeature,
)
from datum.core.naming import RefSet                              # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


def solid(doc, kind, a, b, c, origin=(0, 0, 0)):
    f = PrimitiveFeature()
    f.kind = kind
    f.a, f.b, f.c = str(a), str(b), str(c)
    f.origin = tuple(str(v) for v in origin)
    f.operation = JOIN
    doc.add_feature(f)
    return f


def text_sketch(doc, plane, x, y, text, size=10.0, **style):
    sk = SketchFeature(name="Sketch%d" % (len(doc.features) + 1))
    sk.sketch = Sketch(plane, sk.name)
    tid = sk.sketch.add_text(x, y, text, size=size, **style)
    doc.add_feature(sk)
    return sk, tid


def emboss(doc, sk, **fields):
    e = EmbossFeature()
    e.sketch_id = sk.id
    for key, value in fields.items():
        setattr(e, key, value)
    doc.add_feature(e)
    return e


def built(doc):
    report = doc.rebuild()
    return report.ok, report.message


def letters_area(sketch):
    return sum(kernel.face_area(f) for f in kernel.sketch_faces(sketch))


ABOVE = SketchPlane((0.0, 0.0, 20.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0),
                    "z=20")

# ==========================================================================
print("text in a sketch")

s = Sketch()
tid = s.add_text(5.0, 5.0, "Hi 8", size=10.0)
check("the letters are faces, the hole of the 8 a hole",
      len(kernel.text_faces(s, tid)) == 4, len(kernel.text_faces(s, tid)))
regions = kernel.sketch_regions(s)
check("the whole text is one region", len(regions) == 1, len(regions))
check("its identity point lies on a letter",
      any(kernel.face_area(f) > 0 for f in kernel.text_faces(s, tid)))
back = Sketch.from_dict(s.to_dict())
check("saved and loaded", back.texts[tid].text == "Hi 8"
      and back.texts[tid].size == 10.0)
check("on a point of its own", back.texts[tid].point in back.points)
turned = Sketch()
t2 = turned.add_text(0.0, 0.0, "Hi 8", size=10.0, angle=90.0)
box = kernel.text_box(turned, t2)
check("turned 90 degrees, the box stands up",
      max(p[1] for p in box) > 15 and max(p[0] for p in box) < 1.0, box)
bold = Sketch()
bold.add_text(0.0, 0.0, "Hi 8", size=10.0, bold=True)
check("bold letters are heavier", letters_area(bold) > letters_area(s),
      (letters_area(bold), letters_area(s)))
two = Sketch()
t3 = two.add_text(0.0, 0.0, "AB\nCD", size=10.0)
tb = kernel.text_box(two, t3)
check("a second line goes below the first", min(p[1] for p in tb) < -5,
      tb)
s.remove_text(tid)
check("removed, its point goes with it", not s.texts and len(s.points) == 0,
      (s.texts, list(s.points)))

# ==========================================================================
print("text extrudes like any profile")

doc = Document()
sk, tid = text_sketch(doc, SketchPlane(), 0.0, 0.0, "IC")
area = letters_area(sk.sketch)
ex = ExtrudeFeature()
ex.sketch_id = sk.id
ex.distance = "3"
doc.add_feature(ex)
ok, msg = built(doc)
check("built", ok, msg)
check("volume is the letters times the height",
      near(kernel.volume(doc.shape), area * 3.0, 1e-2),
      (kernel.volume(doc.shape), area * 3.0))

# ==========================================================================
print("Emboss and Engrave on a flat face")

for mode, sign in (("emboss", 1.0), ("engrave", -1.0)):
    doc = Document()
    solid(doc, "box", 60, 30, 10)
    sk, tid = text_sketch(doc, ABOVE, 5.0, 10.0, "IITEG")
    area = letters_area(sk.sketch)
    before = 60 * 30 * 10
    e = emboss(doc, sk, mode=mode, depth="1.5")
    ok, msg = built(doc)
    check("%s builds" % mode, ok, msg)
    change = kernel.volume(doc.shape) - before
    check("%s changes the volume by the letters times the depth" % mode,
          near(change, sign * area * 1.5, 1e-2), (change, area * 1.5))
    top = kernel.bounding_box(doc.shape)[5]
    check("%s: %s" % (mode, "standing 1.5 proud" if sign > 0
                      else "the top stays where it was"),
          near(top, 11.5 if sign > 0 else 10.0), top)

print("the sketch below the part works too")
doc = Document()
solid(doc, "box", 60, 30, 10)
below = SketchPlane((0.0, 0.0, -5.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
sk, tid = text_sketch(doc, below, 5.0, 10.0, "IITEG")
emboss(doc, sk, mode="emboss", depth="1")
ok, msg = built(doc)
check("it finds the bottom face", ok and near(
    kernel.bounding_box(doc.shape)[2], -1.0), (msg,
                                              kernel.bounding_box(doc.shape)))

print("a picked face wins")
doc = Document()
solid(doc, "box", 60, 30, 10)
inside = SketchPlane((0.0, 0.0, 5.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
sk, tid = text_sketch(doc, inside, 5.0, 10.0, "IITEG")
doc.rebuild()
bottom = min(kernel.faces(doc.shape),
             key=lambda f: kernel.shape_centre(f)[2])
ref = RefSet()
ref.capture_from(doc.shape, "face", [bottom])
emboss(doc, sk, mode="emboss", depth="1", face=ref)
ok, msg = built(doc)
check("embossed on the bottom although the top is as near", ok and near(
    kernel.bounding_box(doc.shape)[2], -1.0), (msg,
                                              kernel.bounding_box(doc.shape)))

print("nothing there to emboss on says so")
doc = Document()
solid(doc, "box", 10, 10, 10)
sk, tid = text_sketch(doc, ABOVE, 50.0, 50.0, "X")
emboss(doc, sk)
ok, msg = built(doc)
check("an error, not a crash", not ok and "does not meet" in msg, msg)

# ==========================================================================
print("on a cylinder, cast and wrapped")

side = SketchPlane((25.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0))
results = {}
for wrap in (False, True):
    for mode in ("emboss", "engrave"):
        doc = Document()
        solid(doc, "cylinder", 20, 40, 0)
        sk, tid = text_sketch(doc, side, -18.0, 15.0, "WRAP")
        before = math.pi * 20 * 20 * 40
        e = emboss(doc, sk, mode=mode, depth="1", wrap=wrap)
        ok, msg = built(doc)
        name = "%s%s" % (mode, " wrapped" if wrap else "")
        check("%s builds" % name, ok, msg)
        if not ok:
            continue
        change = kernel.volume(doc.shape) - before
        results[name] = change
        check("%s %s material" % (name, "adds" if mode == "emboss"
                                  else "takes away"),
              change > 20 if mode == "emboss" else change < -20, change)
        b = kernel.bounding_box(doc.shape)
        check("%s stays on the near side" % name,
              b[0] > -20.001, b)
        if mode == "emboss":
            # how far out it reaches depends on where the letters fall on
            # the curve, which the font decides: Linux has no Arial
            check("%s stands proud, by no more than 1" % name,
                  b[3] < 21.05 and b[3] > 20.01, b[3])
        check("%s is one valid solid" % name,
              kernel.BRepCheck_Analyzer(doc.shape).IsValid())
if "emboss wrapped" in results and "emboss" in results:
    check("wrapped, the letters keep their width round the cylinder: "
          "more area than cast at a slant",
          abs(results["emboss wrapped"]) > 0.5 * abs(results["emboss"]),
          results)

# ==========================================================================
print("saved and loaded")
data = e.to_dict()
again = Feature.from_dict(data)
check("an Emboss comes back an Emboss",
      isinstance(again, EmbossFeature) and again.wrap
      and again.mode == "engrave" and again.depth == "1", data)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
