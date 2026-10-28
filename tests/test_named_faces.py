"""Named faces (board #82, asked on Reddit): Inventor's Assign Name.

A face given a name in the part is found again after every rebuild; a
rule reads it by name; and an assembly constraint holds it by name
through the component, so the part can be remodelled underneath it.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel, rules                              # noqa: E402
from datum.core.assembly import AssemblyDocument, Attachment      # noqa: E402
from datum.core.constraints3d import MATE                         # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import PrimitiveFeature                  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_named_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


def box(a, b, c):
    doc = Document()
    f = PrimitiveFeature()
    f.kind = "box"
    f.a, f.b, f.c = str(a), str(b), str(c)
    doc.add_feature(f)
    doc.rebuild()
    return doc, f


def top_of(doc):
    return max(kernel.faces(doc.shape),
               key=lambda f: kernel.shape_centre(f)[2])


# ==========================================================================
print("a name in the part")

doc, feature = box(60, 40, 8)
doc.assign_name("Top", top_of(doc))
check("the face has its name", doc.name_of(top_of(doc)) == "Top")
feature.c = "12"
doc.rebuild()
found = doc.named("Top")
check("after the part grows, the name is still on the top",
      found is not None and near(kernel.shape_centre(found)[2], 12.0),
      found and kernel.shape_centre(found))
try:
    doc.assign_name("1st face", top_of(doc))
    check("a name must start with a letter", False)
except ValueError:
    check("a name must start with a letter", True)
side = min(kernel.faces(doc.shape), key=lambda f: kernel.shape_centre(f)[0])
doc.assign_name("Top", side)
check("giving a name to another face moves it there",
      doc.name_of(side) == "Top" and doc.name_of(top_of(doc)) == "")
doc.assign_name("Top", top_of(doc))
again = Document()
again.load_dict(doc.to_dict())
again.rebuild()
check("saved and loaded, the name is kept",
      again.named("Top") is not None
      and near(kernel.shape_centre(again.named("Top"))[2], 12.0))
doc.remove_name("Top")
check("and a name can be taken off", doc.named("Top") is None)
doc.assign_name("Top", top_of(doc))

print("a rule reads it")
result = rules.run(rules.Rule(name="Area", source=(
    'face = named("Top")\n'
    'log(round(face.area), face.normal, face.centre[2])')), doc)
check("its area, which way it faces and where",
      result.ok and "2400 (0.0, 0.0, 1.0) 12.0" in result.output,
      (result.error, result.output))
result = rules.run(rules.Rule(name="Missing",
                              source='named("Bottom")'), doc)
check("a name that is not there says which there are",
      not result.ok and "Top" in (result.error or ""), result.error)

# ==========================================================================
print("an assembly constraint holds it by name")

plate_doc, plate_feature = box(60, 40, 8)
plate_doc.assign_name("Top", top_of(plate_doc))
plate_path = plate_doc.save(os.path.join(WORK, "plate"))
block_doc, _f = box(10, 10, 10)
bottom = min(kernel.faces(block_doc.shape),
             key=lambda f: kernel.shape_centre(f)[2])
block_doc.assign_name("Base", bottom)
block_path = block_doc.save(os.path.join(WORK, "block"))

asm = AssemblyDocument()
asm.path = os.path.join(WORK, "rig.icasm")
plate = asm.place(plate_path)
block = asm.place(block_path)
asm.rebuild()
result = rules.run(rules.Rule(name="Seat", source=(
    'constrain("mate", "plate:1", "Top", "block:1", "Base")')), asm)
check("a rule constrains two components by their faces' names",
      result.ok and len(asm.constraints) == 1, (result.error, result.output))
report = asm.rebuild()
seat = block.placement.apply_point(asm.constraints[0].b.frame.origin)
check("the block sits on the plate", report.ok and near(seat[2], 8.0, 1e-4),
      (report.message, seat))

print("the plate is made thicker, and the block follows its top")
plate_feature.c = "20"
plate_doc.rebuild()
plate_doc.save(plate_path)
report = asm.rebuild()
seat = block.placement.apply_point(asm.constraints[0].b.frame.origin)
check("on the new top, not where the old one was",
      report.ok and near(seat[2], 20.0, 1e-4), (report.message, seat))

print("a face picked in the assembly picks up its name")
top_now = max(kernel.faces(plate.shape),
              key=lambda f: kernel.shape_centre(f)[2])
attachment = asm.attach(plate, "face", top_now)
check("the attachment knows it as Top",
      attachment is not None and attachment.named == "Top",
      attachment and attachment.named)
check("and keeps it in the file", Attachment.from_dict(
    attachment.to_dict()).named == "Top")

print("a name the part has lost says so")
plate_doc.remove_name("Top")
plate_doc.save(plate_path)
report = asm.rebuild()
check("the constraint reports it", "nothing called Top"
      in (asm.constraints[0].error or ""), asm.constraints[0].error)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
