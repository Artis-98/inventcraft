"""Model annotations (#269), as the user asked after trying them.

A straight edge clicked on its own shows its length at once and is put
where the next click off the part is.  A dimension's legs always stand
square to what it measures, never tipped by the camera.  Any annotation's
text can be picked up and dragged, and the drag is one undo.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402
from OCP.BRepAdaptor import BRepAdaptor_Curve                   # noqa: E402
from OCP.GeomAbs import GeomAbs_Line                            # noqa: E402

from datum.core import annotations as notes                     # noqa: E402
from datum.core import kernel                                   # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.features import PrimitiveFeature                # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_annodrag_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("" if cond else "  " + str(extra)))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def pump(n=20):
    for _ in range(n):
        app.processEvents()


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


win = MainWindow()
win.resize(1400, 900)
win.show()
pump()

doc = Document()
block = PrimitiveFeature()
block.kind = "box"
block.a, block.b, block.c = "100", "60", "10"
doc.add_feature(block)
doc.rebuild()
path = doc.save(os.path.join(WORK, "plate.icpart"))
win.open_path(path)
pump()
part = win.document
vp = win.viewport


def click(*shapes):
    for shape in shapes:
        held = [shape]
        vp.selected_shapes = lambda: [held.pop()] if held else []
        win._on_viewport_selection()
        del vp.selected_shapes
        pump(2)


def click_off(x, y):
    """A click on empty space at a pixel."""
    vp._press_pos = QtCore.QPoint(int(x), int(y))
    vp.selected_shapes = lambda: []
    win._on_viewport_selection()
    del vp.selected_shapes
    pump(2)


long_edge = next(e for e in kernel.edges(part.shape)
                 if BRepAdaptor_Curve(e).GetType() == GeomAbs_Line
                 and abs(kernel.edge_length(e) - 100.0) < 1e-6)

print("one straight edge")
win.model_annotate.start("dim")
click(long_edge)
tool = win.model_annotate
check("its length shows at once", tool.pending is not None
      and tool.pending.display == "100",
      tool.pending and tool.pending.display)
check("nothing is added yet", not part.annotations)
mid = tool.pending.anchor
direction = vp.view_direction()
sx, sy = vp.project(mid)
click_off(sx, sy - 120)
check("a click off the part puts it there", len(part.annotations) == 1
      and part.annotations[0].display == "100", len(part.annotations))
note = part.annotations[0]
a, b = note.points
span = [b[i] - a[i] for i in range(3)]
length = math.sqrt(dot(span, span))
u = [c / length for c in span]
leg = [note.offset[i] - dot(note.offset, u) * u[i] for i in range(3)]
wanted = vp.plane_hit(sx, sy - 120, mid, direction)
at = tuple(mid[i] + note.offset[i] for i in range(3))
check("its text is where the click was", wanted is not None
      and math.dist(at, wanted) < 1e-6, (at, wanted))
check("and it stands off the edge", math.sqrt(dot(leg, leg)) > 1.0, leg)

print("legs square to the line, whatever the camera")
corners = sorted({tuple(round(c, 6) for c in kernel.shape_centre(v))
                  for v in kernel.vertices(part.shape)})
p = (0.0, 0.0, 0.0)
q = (100.0, 60.0, 10.0)
diagonal = notes.ModelAnnotation(kind=notes.LINEAR)
diagonal.points = [p, q]
diagonal.anchor = tuple((p[i] + q[i]) / 2 for i in range(3))
for sight in ((0.0, 0.0, -1.0), (-0.577, 0.577, -0.577), (1.0, 0.0, 0.0)):
    off = notes.default_offset(diagonal, part.shape, sight)
    line = [q[i] - p[i] for i in range(3)]
    check("seen along %s the offset is square to it" % (sight,),
          abs(dot(off, line)) < 1e-6 and math.sqrt(dot(off, off)) > 1.0,
          (off, dot(off, line)))
drawn = []
real = vp.draw_edge
vp.draw_edge = lambda p1, p2, colour, width=1.0: drawn.append((p1, p2))
diagonal.offset = [30.0, -10.0, 25.0]           # dragged anywhere
diagonal.display = "x"
tool._draw_note(diagonal, "#000000")
vp.draw_edge = real
line = [q[i] - p[i] for i in range(3)]
legs = [(e1, e2) for e1, e2 in drawn[:2]]
check("both legs are drawn square to the line, even dragged off square",
      all(abs(dot([e2[i] - e1[i] for i in range(3)], line)) < 1e-6
          for e1, e2 in legs), legs)

print("dragging the text")
tool.cancel()
win._draw_visible_sketches()
vp.redraw()
pump()
spot = next(at for n, at in tool._spots if n is note)
x, y = vp.project(spot)
grabbed = vp.grabber(x, y)
check("a press on the text picks it up", grabbed is not None)
check("a press well away from it does not", vp.grabber(x + 300, y + 300)
      is None)
before = list(note.offset)
grabbed.move(x + 60, y)
grabbed.move(x + 80, y + 10)
grabbed.finish()
moved = tuple(spot[i] + note.offset[i] - before[i] for i in range(3))
target = vp.plane_hit(x + 80, y + 10, spot, vp.view_direction())
check("it goes where the mouse went", math.dist(moved, target) < 1e-6,
      (moved, target))
check("the part is marked changed", part.modified)
win.undo()
pump()
again = next(n for n in win.document.annotations if n.id == note.id)
check("one undo puts it back", all(abs(again.offset[i] - before[i]) < 1e-9
                                   for i in range(3)), again.offset)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
