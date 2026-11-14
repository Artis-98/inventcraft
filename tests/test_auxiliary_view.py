"""Auxiliary views (#280), as Inventor's.

A block with a sloping face: its side view shows the slope as an edge.
Auxiliary picks that edge and places a view out square from it, which
looks straight at the sloping face, so the face shows its true size,
42.43 by 30, where the side and top views show it foreshortened.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core import kernel                                   # noqa: E402
from datum.core.features import ExtrudeFeature, SketchFeature   # noqa: E402
from datum.core.sketch import Sketch, SketchPlane               # noqa: E402
from datum.ui import drawing_tools, drawpick                    # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_auxiliary_")
SLOPE = math.hypot(30, 30)


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def pump(n=20):
    for _ in range(n):
        app.processEvents()


win = MainWindow()
win.resize(1400, 900)
win.show()
win.new_document(prompt=False)
sketch = SketchFeature()
sketch.sketch = Sketch(SketchPlane((0, 0, 0), (0, -1, 0), (1, 0, 0), "XZ"),
                       "Side")
corners = [(0, 0), (60, 0), (60, 10), (30, 40), (0, 40)]
for p, q in zip(corners, corners[1:] + corners[:1]):
    sketch.sketch.add_line(p, q)
win.document.add_feature(sketch)
block = ExtrudeFeature()
block.sketch_id = sketch.id
block.distance = "30"
win.document.add_feature(block)
win.document.rebuild()
check("the sloped block builds", win.document.shape is not None
      and len(kernel.faces(win.document.shape)) == 7,
      len(kernel.faces(win.document.shape)) if win.document.shape else None)
part = os.path.join(WORK, "Wedge.icpart")
win.document.path = part
win.save_document()
pump()

win.new_drawing(prompt=False)
pump()
win.drawing.path = os.path.join(WORK, "Sheet.icdraw")
win.save_document()
pump()
ui = win.drawing_ui
ui.place_base_view()
pump()
session = ui._placer
session.dialog.scale.setEditText("1:1")
session.dialog._set_style(dwg.VISIBLE_ONLY)
session.projections.wait()
check("the Drawing View box has Inventor's Sheet Metal View, greyed for "
      "a plain part", not session.dialog.sheet_metal.isEnabled())
check("and the view's name is not shown on the sheet",
      not session.dialog.show_label.isChecked())
session.dialog.place_requested.emit()
pump(40)
sheet = win.drawing.active()
view = sheet.views[0]
check("the base view's label is hidden", not view.label_visible)
def at(item_point):
    return (view.x + item_point[0], view.y + item_point[1])



scale = win.drawing.view_scale(sheet, view)


def lengths(v):
    out = []
    for line in v.projection.lines:
        for p, q in zip(line.points, line.points[1:]):
            out.append(round(math.dist(p, q) / scale, 2))
    return out


slope = [i for i in drawpick.items(view) if i.kind == drawpick.LINE
         and abs(math.dist(i.a, i.b) / scale - SLOPE) < 0.05]
if not slope:
    from datum.core import hlr
    for name in ("front", "back", "right", "left"):
        view.direction = list(hlr.ORIENTATIONS[name][0])
        view.up = list(hlr.ORIENTATIONS[name][1])
        view.projection = None
        ui.rebuild(force=True)
        pump(20)
        slope = [i for i in drawpick.items(view) if i.kind == drawpick.LINE
                 and abs(math.dist(i.a, i.b) / scale - SLOPE) < 0.05]
        if slope:
            break
check("the side view shows the slope as an edge", bool(slope))
edge = slope[0]

print("Auxiliary off that edge")
ui.add_auxiliary()
tool = ui._placer
check("the tool is armed", isinstance(tool, drawing_tools.AuxiliaryTool))
mid = ((edge.a[0] + edge.b[0]) / 2, (edge.a[1] + edge.b[1]) / 2)
tool.press((view.x + mid[0], view.y + mid[1]), None)
check("the edge is taken", len(tool.picks) == 1)
dx, dy = edge.b[0] - edge.a[0], edge.b[1] - edge.a[1]
n = math.hypot(dx, dy)
normal = (-dy / n, dx / n)
# out on the side the slope faces, away from the middle of the view
box = view.projection.box
centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
side = 1.0 if ((mid[0] - centre[0]) * normal[0]
               + (mid[1] - centre[1]) * normal[1]) > 0 else -1.0
drop = (view.x + normal[0] * side * 90, view.y + normal[1] * side * 90)
before = len(sheet.views)
tool.press(drop, None)
pump(40)
ui.end_placement()
check("a view is placed", len(sheet.views) == before + 1)
aux = sheet.views[-1]
check("it is an auxiliary view of the side view",
      aux.kind == dwg.AUXILIARY and aux.parent == view.id)
check("out square from the edge", abs((aux.x - view.x) * dx
                                     + (aux.y - view.y) * dy) / n < 1e-6)
check("drawn", aux.projection is not None and aux.projection.lines,
      aux.error)
seen = lengths(aux)
check("the sloping face at its true size: %.2f long" % SLOPE,
      any(abs(x - SLOPE) < 0.05 for x in seen), sorted(set(seen)))
check("and 30 deep", any(abs(x - 30.0) < 0.05 for x in seen),
      sorted(set(seen)))

shot = ui.canvas.grab()
shot.save(os.path.join(WORK, "auxiliary.png"))
print("    picture:", os.path.join(WORK, "auxiliary.png"))

print("saved")
win.save_document()
back = dwg.DrawingDocument.load(win.drawing.path)
check("the auxiliary view comes back", any(v.kind == dwg.AUXILIARY
                                           for v in back.active().views))

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
