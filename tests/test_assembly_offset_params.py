"""A constraint offset written in a part's parameter works from the start.

An assembly may set a mate's offset to plate_d3, the plate's thickness.
That used to read as 0 until somebody opened the Parameters table, which
is when the parts' values were first read.  Now the assembly reads them
itself whenever it is built and an offset or parameter needs them, and an
offset naming something that does not exist says so instead of quietly
being 0.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel                                     # noqa: E402
from datum.core.assembly import (                                 # noqa: E402
    AssemblyConstraint, AssemblyDocument,
)
from datum.core.constraints3d import MATE                         # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import PrimitiveFeature                  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


WORK = tempfile.mkdtemp(prefix="datum_offset_params_")


def make_part(kind, a, b, c, name, number=""):
    doc = Document()
    if number:
        doc.properties["PartNumber"] = number
    feature = PrimitiveFeature()
    feature.kind = kind
    feature.a, feature.b, feature.c = str(a), str(b), str(c)
    doc.add_feature(feature)
    doc.rebuild()
    return doc.save(os.path.join(WORK, name))


plate = make_part("box", 60, 40, 8, "plate.icpart", "plate")
peg = make_part("cylinder", 5, 25, 0, "peg.icpart", "peg")

asm = AssemblyDocument()
asm.path = os.path.join(WORK, "rig.icasm")
first = asm.place(plate)
second = asm.place(peg)
asm.rebuild()

top = max(kernel.faces(first.shape), key=lambda f: kernel.shape_centre(f)[2])
bottom = min(kernel.faces(second.shape),
             key=lambda f: kernel.shape_centre(f)[2])
a = asm.attach(first, "face", top)
b = asm.attach(second, "face", bottom)
asm.add_constraint(AssemblyConstraint(kind=MATE, a=a, b=b,
                                      offset="plate_d3 * 2"))
asm.save(asm.path)

print("opened fresh, nothing else looked at")
back = AssemblyDocument.load(asm.path)
report = back.rebuild()
check("it builds", report.ok, report.message)
check("the plate's d3 was read", back.component_values.get("plate_d3") == 8.0,
      back.component_values)
seat = back.occurrences[1].placement.apply_point(
    back.constraints[0].b.frame.origin)
# the plate's top is at 8, and the offset 8 * 2 lifts the peg off it; the
# sign depends on the mate's direction, so the gap is what is checked
check("the offset is used, not 0", abs(abs(seat[2] - 8.0) - 16.0) < 1e-4,
      seat)
check("no warning about the offset",
      not any("offset" in w for w in report.warnings), report.warnings)

print("the part changes on disk")
edited = Document.load(plate)
edited.features[0].c = "10"
edited.rebuild()
edited.save(plate)
back.library.forget()
report = back.rebuild()
seat = back.occurrences[1].placement.apply_point(
    back.constraints[0].b.frame.origin)
check("the new thickness is read", back.component_values.get("plate_d3") == 10.0,
      back.component_values)
check("and the gap follows it", abs(abs(seat[2] - 10.0) - 20.0) < 1e-4, seat)

print("an offset naming nothing")
back.constraints[0].offset = "nosuch_d9"
report = back.rebuild()
check("is reported", any("nosuch_d9" in w for w in report.warnings),
      report.warnings)
check("on the constraint too", "nosuch_d9" in back.constraints[0].error,
      back.constraints[0].error)

print("an assembly that uses no part parameters reads no parts")
plain = AssemblyDocument()
plain.path = os.path.join(WORK, "plain.icasm")
plain.place(plate)
reads = []
plain.component_reader = lambda p: reads.append(p)
plain.rebuild()
check("nothing read", not reads, reads)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
