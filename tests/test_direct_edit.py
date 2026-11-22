"""Direct Edit and Delete Body.

A block with a hole: the hole moved, turned, made bigger and deleted; a
boss moved; the top face moved up along its normal. A part of two
solids loses one to Delete Body.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATUM_NO_WORKERS"] = "1"

from OCP.BRepAdaptor import BRepAdaptor_Surface                    # noqa: E402

from datum.core import kernel                                      # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import (CUT, JOIN, NEW_BODY,              # noqa: E402
                                 DeleteBodyFeature, DirectEditFeature,
                                 PrimitiveFeature)
from datum.core.naming import RefSet                               # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def part(op=CUT):
    d = Document()
    d.add_feature(PrimitiveFeature(kind="box", a="40", b="30", c="20"))
    d.add_feature(PrimitiveFeature(
        kind="cylinder", a="5", b="10" if op == JOIN else "20",
        operation=op, origin=("20", "15", "20" if op == JOIN else "0")))
    d.rebuild()
    return d


def round_faces(shape):
    return [f for f in kernel.faces(shape)
            if BRepAdaptor_Surface(f).GetType().name == "GeomAbs_Cylinder"]


def edit(doc, faces, **kw):
    feature = DirectEditFeature(**kw)
    feature.refs = RefSet()
    feature.refs.capture_from(doc.shape, "face", faces)
    doc.add_feature(feature)
    return doc.rebuild()


def hole_at(doc):
    return [tuple(round(c, 2) for c in kernel.shape_centre(f))
            for f in round_faces(doc.shape)]


doc = part()
report = edit(doc, round_faces(doc.shape), mode="move", dx="8")
check("a hole moved 8 along X", report.ok and hole_at(doc)
      == [(28.0, 15.0, 10.0)], (report.message, hole_at(doc)))
doc = part()
report = edit(doc, round_faces(doc.shape), mode="size", distance="-2")
check("a hole made 4 mm bigger", report.ok and abs(
    kernel.volume(doc.shape) - (24000 - 3.14159265 * 49 * 20)) < 1.0,
    kernel.volume(doc.shape))
doc = part()
report = edit(doc, round_faces(doc.shape), mode="delete")
check("a hole deleted, the block whole again", report.ok and abs(
    kernel.volume(doc.shape) - 24000.0) < 1e-3)
doc = part()
report = edit(doc, round_faces(doc.shape), mode="rotate", axis="Y",
              angle="20")
check("a hole turned", report.ok and kernel.volume(doc.shape) > 22430)
doc = part()
top = max(kernel.faces(doc.shape), key=lambda f: kernel.shape_centre(f)[2])
report = edit(doc, [top], mode="move", dz="5")
check("the top face moved up along its normal", report.ok and abs(
    kernel.bounding_box(doc.shape)[5] - 25.0) < 1e-6)
doc = part(JOIN)
faces = round_faces(doc.shape) + [max(
    kernel.faces(doc.shape), key=lambda f: kernel.shape_centre(f)[2])]
report = edit(doc, faces, mode="move", dy="-6")
check("a boss moved", report.ok and hole_at(doc)[0][1] == 9.0,
      hole_at(doc))
saved = DirectEditFeature(mode="size", distance="3")
again = DirectEditFeature()
again.load_fields(saved.field_dict())
check("kept in the file", (again.mode, again.distance) == ("size", "3"))

print("Delete Body")
doc = Document()
doc.add_feature(PrimitiveFeature(kind="box", a="10", b="10", c="10"))
doc.add_feature(PrimitiveFeature(kind="box", a="10", b="10", c="10",
                                 operation=NEW_BODY,
                                 origin=("30", "0", "0")))
doc.rebuild()
names = doc.bodies_before(10 ** 9) if hasattr(doc, "bodies_before") else []
gone = DeleteBodyFeature()
gone.solids = [names[-1]] if names else ["Solid2"]
doc.add_feature(gone)
report = doc.rebuild()
check("one solid left", report.ok and abs(kernel.volume(doc.shape)
                                          - 1000.0) < 1e-6,
      (report.message, kernel.volume(doc.shape)))

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
