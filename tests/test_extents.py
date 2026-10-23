"""Extrude's extents, the rest of Inventor's (#210).

Asymmetric, To Next, To a face, a plane or a point with Extend Face,
From a face, From To between two, and Match Shape for an open profile.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel                                     # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (                                 # noqa: E402
    CUT, JOIN, NEW_BODY, ExtrudeFeature, PrimitiveFeature, SketchFeature,
    WorkPlaneFeature,
)
from datum.core.naming import RefSet                              # noqa: E402
from datum.core.sketch import STANDARD_PLANES, Sketch, SketchPlane  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


def box(doc, x, y, z, dx, dy, dz, op=JOIN, kind="box"):
    f = PrimitiveFeature()
    f.kind = kind
    f.a, f.b, f.c = str(dx), str(dy), str(dz)
    f.origin = (str(x), str(y), str(z))
    f.operation = op
    doc.add_feature(f)
    return f


def sketch(doc, plane, *rects, lines=()):
    sk = SketchFeature(name="Sketch%d" % (len(doc.features) + 1))
    sk.sketch = Sketch(plane, sk.name)
    for a, b in rects:
        sk.sketch.add_rectangle(a, b)
    for a, b in lines:
        sk.sketch.add_line(a, b)
    doc.add_feature(sk)
    return sk


def extrude(doc, sk, **fields):
    e = ExtrudeFeature()
    e.sketch_id = sk.id
    for key, value in fields.items():
        setattr(e, key, value)
    doc.add_feature(e)
    return e


def raised(z):
    return SketchPlane((0.0, 0.0, z), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0),
                       "z=%g" % z)


def built(doc):
    report = doc.rebuild()
    return report.ok, report.message


def vol(doc):
    return kernel.volume(doc.shape)


def face_at(doc, axis, value):
    """The face whose middle is furthest along an axis, or at a value."""
    return min(kernel.faces(doc.shape),
               key=lambda f: abs(kernel.shape_centre(f)[axis] - value))


def ref_to(doc, kind, shape):
    ref = RefSet()
    ref.capture_from(doc.shape, kind, [shape])
    return ref


# ==========================================================================
print("Asymmetric: each way its own distance")
doc = Document()
sk = sketch(doc, STANDARD_PLANES["XY"], ((0, 0), (10, 10)))
e = extrude(doc, sk, extent="asymmetric", distance="8", distance2="3")
ok, msg = built(doc)
b = kernel.bounding_box(doc.shape)
check("it builds", ok, msg)
check("8 one way and 3 the other", near(b[2], -3) and near(b[5], 8), b)
e.reversed = True
built(doc)
b = kernel.bounding_box(doc.shape)
check("and Flip swaps them over", near(b[2], -8) and near(b[5], 3), b)
e.taper2 = "5"
ok, msg = built(doc)
check("with a taper of its own on the second", ok
      and abs(vol(doc) - 1100) > 1.0, (msg, vol(doc)))
b = kernel.bounding_box(doc.shape)
check("which leaves the first way's end as it was",
      near(b[2], -8) and near(b[5], 3), b)

# ==========================================================================
print("To Next")
doc = Document()
box(doc, 0, 0, 0, 40, 40, 20)
sk = sketch(doc, raised(35), ((5, 5), (15, 15)))
e = extrude(doc, sk, extent="to_next", reversed=True)
ok, msg = built(doc)
check("a join from above runs down until it meets the part",
      ok and near(vol(doc), 40 * 40 * 20 + 100 * 15), (msg, vol(doc)))
e.reversed = False
ok, msg = built(doc)
check("and up, with nothing there, says so",
      not ok and "nothing that way" in msg, msg)

doc = Document()
box(doc, 0, 0, 0, 40, 40, 20)
box(doc, 5, 5, 5, 30, 30, 10, op=CUT)
sk = sketch(doc, raised(20), ((10, 10), (20, 20)))
built(doc)
before = vol(doc)
e = extrude(doc, sk, extent="to_next", reversed=True, operation=CUT)
ok, msg = built(doc)
check("a cut goes through the wall it starts in and stops at the hollow",
      ok and near(vol(doc), before - 100 * 5), (msg, before - vol(doc)))

# ==========================================================================
print("To a face, a plane or a point")
doc = Document()
box(doc, 0, 0, 0, 40, 40, 20)
built(doc)
top = face_at(doc, 2, 20)
corner = min(kernel.vertices(doc.shape), key=lambda v: kernel.distance_to_point(
    v, (40, 40, 20)))
sk = sketch(doc, raised(35), ((10, 10), (20, 20)))
e = extrude(doc, sk, extent="to_plane", to_ref=ref_to(doc, "face", top))
ok, msg = built(doc)
check("down to a picked face", ok
      and near(vol(doc), 40 * 40 * 20 + 100 * 15), (msg, vol(doc)))
sk.sketch = Sketch(raised(35), sk.name)
sk.sketch.add_rectangle((30, 10), (50, 20))
ok, msg = built(doc)
check("a face that does not cover the profile says so",
      not ok and "Extend Face" in msg, msg)
e.extend_face = True
ok, msg = built(doc)
check("and Extend Face runs it out", ok
      and near(vol(doc), 40 * 40 * 20 + 200 * 15), (msg, vol(doc)))
e.extend_face = False
e.to_ref = ref_to(doc, "vertex", corner)
e.operation = NEW_BODY
sk.sketch = Sketch(raised(50), sk.name)
sk.sketch.add_rectangle((0, 0), (10, 10))
ok, msg = built(doc)
b = kernel.bounding_box(doc.bodies[-1].shape) if ok else None
check("to a point: down to its height", ok and near(b[2], 20)
      and near(b[5], 50), (msg, b))
e.to_ref = RefSet()
e.to_plane = "XY"
ok, msg = built(doc)
b = kernel.bounding_box(doc.bodies[-1].shape) if ok else None
check("and a plane by name still works", ok and near(b[2], 0), (msg, b))

print("to a curved face")
doc = Document()
box(doc, 0, 0, 0, 10, 20, 0, kind="cylinder")
built(doc)
side = next(f for f in kernel.faces(doc.shape)
            if kernel.shape_centre(f)[2] > 1 and kernel.shape_centre(f)[2] < 19
            and abs(kernel.shape_centre(f)[0]) + abs(kernel.shape_centre(f)[1])
            < 9.9)
left = SketchPlane((-30.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                   "x=-30")
sk = sketch(doc, left, ((-2, 5), (2, 10)))
e = extrude(doc, sk, extent="to_plane", operation=NEW_BODY,
            to_ref=ref_to(doc, "face", side))


def gap(y):
    return 30.0 - math.sqrt(100.0 - y * y)


steps = 2000
want = 5.0 * sum(gap(-2 + 4 * (i + 0.5) / steps) * 4 / steps
                 for i in range(steps))
ok, msg = built(doc)
check("it runs up to the curve", ok
      and near(kernel.volume(doc.bodies[-1].shape), want, 1e-2),
      (msg, ok and kernel.volume(doc.bodies[-1].shape), want))
sk.sketch = Sketch(left, sk.name)
sk.sketch.add_rectangle((-2, 15), (2, 25))
ok, msg = built(doc)
check("past the end of the cylinder it says so", not ok
      and "Extend Face" in msg, msg)
e.extend_face = True
ok, msg = built(doc)
check("and Extend Face carries the cylinder on", ok
      and near(kernel.volume(doc.bodies[-1].shape), 2 * want, 2e-2),
      (msg, ok and kernel.volume(doc.bodies[-1].shape), 2 * want))

# ==========================================================================
print("From a face or a plane, and From To")
doc = Document()
low = WorkPlaneFeature(name="Low")
low.base, low.offset = "XY", "5"
doc.add_feature(low)
high = WorkPlaneFeature(name="High")
high.base, high.offset = "XY", "12"
doc.add_feature(high)
sk = sketch(doc, STANDARD_PLANES["XY"], ((0, 0), (10, 10)))
e = extrude(doc, sk, distance="4", from_plane="Low")
ok, msg = built(doc)
b = kernel.bounding_box(doc.shape)
check("a distance from a plane starts there", ok and near(b[2], 5)
      and near(b[5], 9), (msg, b))
tilt = WorkPlaneFeature(name="Tilt")
tilt.base, tilt.offset, tilt.angle = "XY", "5", "20"
doc.features.insert(0, tilt)
e.from_plane = "Tilt"
ok, msg = built(doc)
b = kernel.bounding_box(doc.shape)
check("from a tilted one both ends take the slope, the volume the same",
      ok and near(vol(doc), 400, 1e-2) and b[5] - b[2] > 4.5, (msg, vol(doc), b))
e.extent, e.from_plane, e.to_plane = "from_to", "Low", "High"
ok, msg = built(doc)
b = kernel.bounding_box(doc.shape)
check("From To runs between two planes", ok and near(b[2], 5)
      and near(b[5], 12) and near(vol(doc), 700), (msg, b))
e.to_plane = ""
ok, msg = built(doc)
check("and asks for the second when it is missing", not ok
      and "pick the face or plane it runs to" in msg, msg)
e.from_plane, e.to_plane = "", "High"
ok, msg = built(doc)
b = kernel.bounding_box(doc.shape)
check("with no From it starts on the sketch", ok and near(b[2], 0)
      and near(b[5], 12), (msg, b))

doc = Document()
box(doc, 0, 0, 0, 40, 40, 20)
low = WorkPlaneFeature(name="Low")
low.base, low.offset = "XY", "-6"
doc.add_feature(low)
built(doc)
top = face_at(doc, 2, 20)
sk = sketch(doc, raised(30), ((50, 0), (60, 10)))
e = extrude(doc, sk, extent="from_to", from_plane="Low", operation=NEW_BODY,
            to_ref=ref_to(doc, "face", top))
ok, msg = built(doc)
check("a face it misses stops nothing", not ok
      and "does not run between" in msg, msg)
e.extend_face = True
ok, msg = built(doc)
b = kernel.bounding_box(doc.bodies[-1].shape) if ok else None
check("unless Extend Face", ok and near(b[2], -6) and near(b[5], 20),
      (msg, b))

# ==========================================================================
print("Match Shape: an open profile, run out to the part")
doc = Document()
box(doc, 0, 0, 0, 40, 40, 10)
box(doc, 10, 20, 0, 20, 30, 10, op=CUT)      # a slot, open at y = 40
sk = sketch(doc, STANDARD_PLANES["XY"], lines=[((10, 35), (30, 35))])
built(doc)
before = vol(doc)
e = extrude(doc, sk, match_shape=True, distance="10")
ok, msg = built(doc)
check("open to the outside on that side, it says so", not ok
      and "close nothing in" in msg, msg)
e.match_flip = True
ok, msg = built(doc)
check("the other side fills the slot up to the line", ok
      and near(vol(doc), before + 20 * 15 * 10), (msg, vol(doc) - before))
e.operation = CUT
ok, msg = built(doc)
check("a cut takes everything on its side", ok
      and near(vol(doc), 2 * 10 * 5 * 10), (msg, vol(doc)))

print("an open chain drawn out of order is still one")
sk = Sketch(STANDARD_PLANES["XY"], "Chain")
sk.add_line((10, 0), (20, 0))
sk.add_line((0, 0), (10, 0))
sk.add_line((20, 0), (20, 10))
wire = kernel.open_chain_wire(sk)
check("all three curves in one wire", wire is not None
      and len(kernel.edges(wire)) == 3,
      wire is not None and len(kernel.edges(wire)))

print("saved and read back")
again = Document()
again.load_dict(doc.to_dict())
twin = [f for f in again.features if isinstance(f, ExtrudeFeature)][-1]
check("the new fields survive the file", twin.match_shape and twin.match_flip
      and twin.operation == CUT)
ok, msg = built(again)
check("and build the same", ok and near(vol(again), vol(doc)), msg)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
