"""The welding cart sample opens, rebuilds and is still put together.

The cart is the sample that touches everything at once: a Frame Generator
frame on a skeleton, sheet metal with corners and reliefs, plates nested
for the plasma table, and an assembly held by constraints rather than
grounded.  A change to any of those can leave it opening as a pile of
parts, and nobody would notice until it was in front of somebody, so this
checks what a person would look for.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import frames, kernel, sheetmetal              # noqa: E402
from datum.core.assembly import open_any                       # noqa: E402
from datum.core.cam import CamDocument                         # noqa: E402
from datum.core.document import Document                       # noqa: E402

FAILS = []
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "examples", "weld-cart")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("the assembly")
asm = open_any(os.path.join(SRC, "Welding Cart.icasm"))
report = asm.rebuild()
check("it rebuilds without error", report.ok and not report.errors,
      report.message)
check("all 18 components are there", len(asm.occurrences) == 18,
      len(asm.occurrences))
check("held by 46 constraints, none of them failing",
      len(asm.constraints) == 46
      and not [c.name for c in asm.constraints if c.error],
      [(c.name, c.error) for c in asm.constraints if c.error])
check("one degree of freedom left: the bottle turning where it stands",
      report.dof == 1, report.dof)
check("nothing is grounded but the skeleton and the frame that follows it",
      sorted(o.label.split(":")[0] for o in asm.occurrences
             if o.grounded) == ["Cart Skeleton", "Frame0001"],
      [o.label for o in asm.occurrences if o.grounded])
frame = next(o for o in asm.occurrences if o.follows)
box = kernel.bounding_box(asm.shape)
top = kernel.bounding_box(frame.placed())[5]
check("it stands on its casters on the floor, the handle bar 1065 up",
      abs(box[2]) < 0.5 and abs(top - 1065.0) < 0.5,
      ([round(c, 1) for c in box], top))

print("the frame")
fd = frames.read_frame(asm.component_path(frame))
check("16 members of 30 x 30 x 2 tube",
      len(fd.members) == 16 and {m.size for m in fd.members}
      == {"30 x 30 x 2"}, len(fd.members))
check("its ten corners mitred",
      [t.kind for t in fd.treatments] == ["miter"] * 10,
      [t.kind for t in fd.treatments])
member = Document.load(os.path.join(os.path.dirname(
    asm.component_path(frame)), fd.members[0].part))
check("a member is a sketch, extruded, and its end treatments",
      [f.type_name for f in member.features]
      == ["sketch", "extrude", "frame_ends"])

print("the sheet metal")
for name in ("Top Tray", "Lower Shelf", "Bottle Tray", "Bottle Collar"):
    part = Document.load(os.path.join(SRC, name + ".icpart"))
    try:
        flat = sheetmetal.flat_pattern(part)
        laid = flat is not None and min(flat.extents()) > 100
    except kernel.KernelError as exc:
        laid = False
        print("   ", exc)
    check("%s lays flat" % name, laid)

print("the plates")
cam = CamDocument.load(os.path.join(SRC, "Cart Plates.iccam"))
cam_report = cam.rebuild()
check("six plates on the sheet, every cut ready",
      len(cam.parts) == 6 and "ready" in getattr(cam_report, "message", ""),
      getattr(cam_report, "message", ""))

print("the caster")
caster = Document.load(os.path.join(SRC, "Caster.icpart"))
check("the sample's own caster, not a maker's file it may not carry",
      not any(f.type_name == "import" for f in caster.features))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
