"""Adaptive parts: a sketch in one part follows an edge of another (#319).

A plate and a cover sit in an assembly.  The cover's sketch projects the
plate's round hole and cuts its own hole through it.  The link lives in
the assembly: move the plate, or make its hole bigger, and the cover's
hole follows.  Turn adaptive off and it stays put.  Delete the plate and
the cover keeps its hole where it last was.  The cover opened on its own
still has the hole.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel                                     # noqa: E402
from datum.core.adaptive import in_target_frame                   # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (                                 # noqa: E402
    ExtrudeFeature, PrimitiveFeature, SketchFeature, cast_onto,
)
from datum.core.naming import RefSet                              # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


WORK = tempfile.mkdtemp(prefix="datum_adaptive_")


def plate_with_hole(radius):
    doc = Document()
    block = PrimitiveFeature()
    block.kind = "box"
    block.a, block.b, block.c = "80", "60", "6"
    doc.add_feature(block)
    hole = SketchFeature()
    hole.sketch = Sketch(SketchPlane((0, 0, 6), (0, 0, 1), (1, 0, 0), "Top"),
                         "Hole")
    hole.sketch.add_circle((40, 30), radius)
    doc.add_feature(hole)
    cut = ExtrudeFeature()
    cut.sketch_id = hole.id
    cut.operation = "cut"
    cut.extent = "through_all"
    doc.add_feature(cut)
    doc.rebuild()
    return doc


plate_doc = plate_with_hole(8)
plate = plate_doc.save(os.path.join(WORK, "plate.icpart"))
check("the plate has its hole", plate_doc.shape is not None
      and len(kernel.faces(plate_doc.shape)) >= 7,
      len(kernel.faces(plate_doc.shape)) if plate_doc.shape else None)

cover_doc = Document()
slab = PrimitiveFeature()
slab.kind = "box"
slab.a, slab.b, slab.c = "80", "60", "4"
cover_doc.add_feature(slab)
cover_sketch = SketchFeature()
cover_sketch.sketch = Sketch(SketchPlane((0, 0, 4), (0, 0, 1), (1, 0, 0),
                                         "Top"), "Follow")
cover_doc.add_feature(cover_sketch)
cover_doc.rebuild()
cover = cover_doc.save(os.path.join(WORK, "cover.icpart"))

asm = AssemblyDocument()
asm.path = os.path.join(WORK, "stack.icasm")
first = asm.place(plate)
second = asm.place(cover)
second.grounded = True
second.placement.position = [0.0, 0.0, 6.0]
asm.rebuild()

print("the cover's sketch projects the plate's hole")
circle = next(e for e in kernel.edges(first.shape)
              if kernel.edge_kind(e) == "circle"
              and abs(kernel.shape_centre(e)[2] - 6.0) < 1e-6) \
    if hasattr(kernel, "edge_kind") else None
if circle is None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle
    circle = next(e for e in kernel.edges(first.shape)
                  if BRepAdaptor_Curve(e).GetType() == GeomAbs_Circle
                  and abs(kernel.shape_centre(e)[2] - 6.0) < 1e-6)
refs = RefSet()
refs.capture_from(first.shape, "edge", [circle])
live_cover = Document.load(cover)
live_cover.rebuild()
held = {os.path.normcase(os.path.abspath(cover)): live_cover}
asm.part_opener = lambda p: held[os.path.normcase(os.path.abspath(p))]
sketch_feature = live_cover.feature(cover_sketch.id)
record = cast_onto(sketch_feature.sketch,
                   in_target_frame(circle, first.placement, second.placement),
                   source={"adaptive": 0})
check("it cast one circle", record is not None and len(record.entities) == 1)
link = asm.add_adaptive(second.id, cover_sketch.id, record.id, first.id,
                        refs.refs[0].to_dict())
record.source = {"adaptive": link.id}
cut = ExtrudeFeature()
cut.sketch_id = cover_sketch.id
cut.operation = "cut"
cut.extent = "through_all"
live_cover.add_feature(cut)
live_cover.rebuild()


def hole():
    """The cover's projected circle: centre and radius."""
    sk = live_cover.feature(cover_sketch.id).sketch
    rec = next(r for r in sk.projections if r.id == record.id)
    entity = sk.entities[rec.entities[0]]
    c = sk.points[entity.points[0]]
    return round(c.x, 4), round(c.y, 4), round(entity.radius, 4)


check("at the middle, radius 8", hole() == (40.0, 30.0, 8.0), hole())

print("the plate moves")
first.placement.position = [10.0, -5.0, 0.0]
report = asm.rebuild()
check("the cover's hole follows it", hole() == (50.0, 25.0, 8.0), hole())
check("and is cut there", live_cover.shape is not None and any(
    abs(kernel.shape_centre(f)[0] - 50.0) < 1e-3
    and abs(kernel.shape_centre(f)[1] - 25.0) < 1e-3
    for f in kernel.faces(live_cover.shape)
    if abs(kernel.shape_centre(f)[2] - 2.0) < 1e-3))
check("no warnings", not report.warnings, report.warnings)

print("the plate's hole gets bigger")
bigger = Document.load(plate)
bigger.features[1].sketch.entities[
    next(iter(bigger.features[1].sketch.entities))].radius = 12.0
bigger.rebuild()
bigger.save(plate)
asm.library.forget(plate)
asm.rebuild()
check("the cover's hole grows with it", hole() == (50.0, 25.0, 12.0), hole())

print("saved and opened again")
asm.save(asm.path)
back = AssemblyDocument.load(asm.path)
check("the link comes back", len(back.adaptive) == 1
      and back.adaptive[0].source == first.id, back.adaptive)

print("adaptive off freezes it")
link.adaptive = False
first.placement.position = [-10.0, 0.0, 0.0]
asm.rebuild()
check("it stays where it was", hole() == (50.0, 25.0, 12.0), hole())
link.adaptive = True
asm.rebuild()
check("and on again it follows", hole() == (30.0, 30.0, 12.0), hole())

print("the cover on its own")
live_cover.save(cover)
alone = Document.load(cover)
alone.rebuild()
sk = alone.feature(cover_sketch.id).sketch
rec = next(r for r in sk.projections if r.id == record.id)
check("keeps the lines, not stale", not rec.stale)
entity = sk.entities[rec.entities[0]]
c = sk.points[entity.points[0]]
check("where they last were", (round(c.x, 4), round(c.y, 4)) == (30.0, 30.0),
      (c.x, c.y))

print("the plate deleted")
asm.remove_occurrence(first.id)
report = asm.rebuild()
check("the link goes", not asm.adaptive)
check("the hole stays", hole() == (30.0, 30.0, 12.0), hole())
check("nothing complains", not report.errors, report.errors)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
