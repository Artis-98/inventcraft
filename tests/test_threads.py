"""Cosmetic threads, as Inventor draws them.

The size follows the face (16 mm is M16; a size far from any is Custom at
its own diameter); a shaft takes an external thread and a hole an internal
one; the solid is left exactly as it was; the thread's marks are saved
with the part, so an assembly can draw them without building it; and the
library's bolts and nuts come with their threads on.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel, threads                            # noqa: E402
from datum.core import standard_parts as sp                       # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (PrimitiveFeature, ThreadFeature,  # noqa: E402
                                 CUT)
from datum.core.naming import RefSet                              # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


print("sizes")
m16 = threads.match(16.0)
check("a 16 mm face is M16, 2 mm coarse pitch",
      m16.designation == "M16" and near(m16.pitch, 2.0))
check("with its fine pitch on offer", 1.5 in m16.pitches)
check("15.9 mm tube is still M16", threads.match(15.9).designation == "M16")
odd = threads.match(17.2)
check("17.2 mm is no standard size: Custom at 17.2",
      odd.standard == threads.CUSTOM and near(odd.diameter, 17.2))
check("pipe threads too: G1/2 is 20.955 mm, 14 to the inch",
      next(s for s in threads.sizes(threads.PIPE)
           if s.designation == "G1/2").pitch == round(25.4 / 14, 4))
check("a fine pitch is written M16x1.5",
      threads.designation(m16, 1.5) == "M16x1.5"
      and threads.designation(m16, 2.0) == "M16")


def round_face(shape, radius):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    for f in kernel.faces(shape):
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder \
                and near(s.Cylinder().Radius(), radius, 1e-6):
            return f
    return None


print("on a shaft")
doc = Document()
doc.add_feature(PrimitiveFeature(name="Shaft", kind="cylinder", a="8",
                                 b="30"))
doc.rebuild()
volume = kernel.volume(doc.shape)
feature = ThreadFeature(designation="M16", diameter=16.0, pitch=2.0)
feature.refs = RefSet()
feature.refs.capture_from(doc.shape, "face", [round_face(doc.shape, 8.0)])
doc.add_feature(feature)
report = doc.rebuild()
check("it builds", report.ok, report.message)
check("one mark, on the 8 mm radius, 30 long, outside",
      len(feature.marks) == 1
      and near(threads.Mark.from_list(feature.marks[0]).radius, 8.0)
      and near(threads.Mark.from_list(feature.marks[0]).length, 30.0, 1e-4)
      and not threads.Mark.from_list(feature.marks[0]).internal,
      feature.marks)
check("the solid is left exactly as it was",
      near(kernel.volume(doc.shape), volume, 1e-6))
wires = threads.helix(threads.Mark.from_list(feature.marks[0]))
check("drawn as a helix and a ring at each end", len(wires) == 3)
feature.full_length, feature.length, feature.offset = False, "12", "5"
doc.rebuild()
m = threads.Mark.from_list(feature.marks[0])
check("or 12 long, 5 in from the start", near(m.length, 12.0, 1e-4))
feature.left_hand = True
doc.rebuild()
check("and left hand when asked",
      threads.Mark.from_list(feature.marks[0]).left_hand)

with tempfile.TemporaryDirectory() as there:
    path = doc.save(os.path.join(there, "Shaft"))
    check("saved with the part, read back without building it",
          len(threads.marks_in_file(path)) == 1)

print("in a hole")
block = Document()
block.add_feature(PrimitiveFeature(name="Block", kind="box", a="40",
                                   b="40", c="20"))
block.add_feature(PrimitiveFeature(name="Bore", kind="cylinder", a="7",
                                   b="20", operation=CUT,
                                   origin=("20", "20", "0")))
block.rebuild()
tap = ThreadFeature(designation="M14", diameter=14.0, pitch=2.0)
tap.refs = RefSet()
tap.refs.capture_from(block.shape, "face", [round_face(block.shape, 7.0)])
block.add_feature(tap)
block.rebuild()
check("a hole takes an internal thread",
      tap.marks and threads.Mark.from_list(tap.marks[0]).internal,
      tap.marks)

print("the library's fasteners")
bolt = sp._fastener(sp.family("iso-4762"), sp.spec("iso-4762", "M8", 30))
bt = [f for f in bolt.features if isinstance(f, ThreadFeature)]
mk = threads.Mark.from_list(bt[0].marks[0]) if bt else None
check("an M8 x 30 cap screw is threaded M8, 1.25 pitch, down its shank",
      bt and bt[0].designation == "M8" and near(bt[0].pitch, 1.25)
      and mk and near(mk.length, 30.0) and not mk.internal,
      bt and (bt[0].designation, bt[0].pitch))
nut = sp._fastener(sp.family("din-985"), sp.spec("din-985", "M10"))
nt = [f for f in nut.features if isinstance(f, ThreadFeature)]
check("an M10 lock nut is threaded inside, 1.5 pitch",
      nt and threads.Mark.from_list(nt[0].marks[0]).internal
      and near(nt[0].pitch, 1.5))
washer = sp._fastener(sp.family("iso-7089"), sp.spec("iso-7089", "M8"))
check("a washer has none", not any(isinstance(f, ThreadFeature)
                                   for f in washer.features))
check("and the threaded parts still build their solids",
      bolt.last_report.ok and nut.last_report.ok)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
