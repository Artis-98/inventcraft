"""A section line drawn through the middle of a view cuts the middle of
the part, wherever its centre of mass is.

A point on the paper is its place in the parent view's frame less the
middle the projection was centred on (hlr.project centres on the shape's
box). The cut plane used to be lifted back by the centre of mass instead,
so on a part whose mass sits off-centre, an L, the cut landed somewhere
else than the line.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtWidgets                                      # noqa: E402

from datum.core import fileformat, hlr                             # noqa: E402
from datum.core import views as viewgen                            # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.drawing import (                                   # noqa: E402
    BASE, SECTION, DrawingDocument, View, WITH_HIDDEN,
)
from datum.core.features import PrimitiveFeature                   # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
WORK = tempfile.mkdtemp(prefix="datum_section_line_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# an L seen from the front: a bar 100 long and 20 high along X, and a
# column 40 wide standing 80 above it at the left end. Its box's middle is
# at X 50, over the bar alone; its centre of mass is at X 31.5, inside the
# column.
part = Document()
for a, b, c, origin in ((100, 20, 20, (0, 0, 0)),
                        (40, 20, 80, (0, 0, 20))):
    step = PrimitiveFeature()
    step.kind = "box"
    step.a, step.b, step.c = str(a), str(b), str(c)
    step.origin = tuple(str(v) for v in origin)
    step.operation = "join" if part.features else "new"
    part.add_feature(step)
part.rebuild()
PART = part.save(os.path.join(WORK, "ell.icpart"))

doc = DrawingDocument()
doc.path = os.path.join(WORK, "d.icdraw")
sheet = doc.add_sheet("A3")
front = View(kind=BASE, orientation="front", scale=1.0, x=140.0, y=190.0,
             display=WITH_HIDDEN)
front.ref = fileformat.ComponentRef(
    path=fileformat.relative_path(PART, WORK), name="ell.icpart")
doc.add_view(sheet, front)
viewgen.Generator().rebuild(doc)
box = front.projection.box
check("the front view shows the L 100 wide and 100 high",
      abs(box[2] - box[0] - 100) < 1e-3 and abs(box[3] - box[1] - 100) < 1e-3,
      box)

middle = (box[0] + box[2]) / 2.0
section = doc.add_view(sheet, View(
    kind=SECTION, parent=front.id, letter="A",
    cut=[middle, box[3] + 5.0, middle, box[1] - 5.0],
    x=front.x + 150.0, y=front.y))
viewgen.Generator().rebuild(doc, force=True)
check("the section was cut", section.projection is not None, section.error)

loops = section.projection.of_kind(hlr.CUT) if section.projection else []
ys = [p[1] for loop in loops for p in loop.points] if loops else []
height = (max(ys) - min(ys)) if ys else None
check("a line through the middle of the view cuts the bar alone, 20 high "
      "(through the centre of mass it would cut the column, 100 high)",
      height is not None and abs(height - 20.0) < 1e-3, height)

print()
if FAILS:
    print("%d FAILURE(S): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
