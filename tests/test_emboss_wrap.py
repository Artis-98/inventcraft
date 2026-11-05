"""Emboss and Engrave wrapped round a cylinder read the right way round,
with every letter there (GitHub #17).

Wrapped text came out mirrored whenever the cylinder's u ran the other way
round from the sketch, letters stacked on the first one because their
placement was dropped, and letters whose loops ran backwards became
invalid faces that the emboss lost, along with the part in the preview.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datum.core import kernel                                    # noqa: E402
from datum.core.document import Document                         # noqa: E402
from datum.core.features import (                                # noqa: E402
    EmbossFeature, ExtrudeFeature, PrimitiveFeature, SketchFeature)
from datum.core.sketch import Sketch, SketchPlane                # noqa: E402

FAILS = []


def build(cyl_from_sketch, front, mode):
    doc = Document()
    if cyl_from_sketch:
        base = SketchFeature(name="Base")
        base.sketch = Sketch(SketchPlane(), "Base")
        base.sketch.add_circle((0.0, 0.0), 20.0)
        doc.add_feature(base)
        ex = ExtrudeFeature()
        ex.sketch_id, ex.distance = base.id, "40"
        doc.add_feature(ex)
    else:
        cyl = PrimitiveFeature()
        cyl.kind, cyl.a, cyl.b = "cylinder", "20", "40"
        doc.add_feature(cyl)
    doc.rebuild()
    base_shape = doc.shape
    if front:
        plane = SketchPlane((0.0, -30.0, 0.0), (0.0, -1.0, 0.0),
                            (1.0, 0.0, 0.0))
    else:
        plane = SketchPlane((0.0, 30.0, 0.0), (0.0, 1.0, 0.0),
                            (-1.0, 0.0, 0.0))
    sk = SketchFeature(name="S")
    sk.sketch = Sketch(plane, "S")
    sk.sketch.add_text(-10.0, 17.0, "TEST", size=6.0)
    doc.add_feature(sk)
    doc.rebuild()
    e = EmbossFeature()
    e.mode, e.depth, e.wrap = mode, "1", True
    for r in kernel.sketch_regions(sk.sketch):
        e.profiles.add(sk.id, r["centre"])
    doc.add_feature(e)
    doc.rebuild()
    if e.error or doc.shape is None:
        return "error %s" % e.error
    if mode == "emboss":
        letters = kernel.boolean(doc.shape, base_shape, "cut")
    else:
        letters = kernel.boolean(base_shape, doc.shape, "cut")
    pieces = kernel.solids(letters)
    xd = plane.xdir
    along = sorted(pieces, key=lambda p: sum(
        kernel.centre_of_mass(p)[i] * xd[i] for i in range(3)))
    # in TEST the E is the biggest letter, and it comes second when the
    # text reads the right way round, third when it is mirrored
    vols = [kernel.volume(p) for p in along]
    return "%d letters, E at %d" % (len(pieces),
                                    vols.index(max(vols)) if vols else -1)


for from_sketch in (False, True):
    for front in (True, False):
        for mode in ("emboss", "engrave"):
            got = build(from_sketch, front, mode)
            name = "%s cylinder, from %s, %s" % (
                "extruded" if from_sketch else "primitive",
                "the front" if front else "behind", mode)
            ok = got == "4 letters, E at 1"
            print(("  PASS  " if ok else "  FAIL  ") + name
                  + ("" if ok else "  " + got))
            if not ok:
                FAILS.append(name)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all emboss wrap checks passed")
