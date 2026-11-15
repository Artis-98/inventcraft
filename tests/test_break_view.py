"""Break views (#280), as Inventor's.

A bar 600 long with a hole near each end is drawn and broken in the
middle: the view closes up round the band taken out, with the break's
zigzags either side of the gap.  Everything is still kept unbroken, so a
dimension from end to end reads 600 though it is drawn shorter, the
corners past the break can still be picked, and the DXF is broken too.
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
from datum.core.features import CUT, PrimitiveFeature           # noqa: E402
from datum.ui import drawing_tools, drawingexport, drawpick     # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_break_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("" if cond else "  " + str(extra)))
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
win.new_primitive("box")
d = win._active_dialog
d.a.set_text("600")
d.b.set_text("30")
d.c.set_text("20")
d.commit()
for x in ("50", "550"):
    hole = PrimitiveFeature()
    hole.kind, hole.a, hole.b = "cylinder", "4", "20"
    hole.origin = [x, "15", "-5"]
    hole.operation = CUT
    win.document.add_feature(hole)
win.document.rebuild()
part = os.path.join(WORK, "Bar.icpart")
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
session.dialog.scale.setEditText("1:2")
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
box = view.projection.box
width_before = box[2] - box[0]
check("the bar is drawn 300 long at 1:2", abs(width_before - 300) < 0.5,
      width_before)

print("broken")
ui.add_break()
tool = ui._placer
check("the tool is armed", isinstance(tool, drawing_tools.BreakTool))
y = (box[1] + box[3]) / 2
tool.press((view.x - 100, view.y + y), None)
tool.press((view.x + 100, view.y + y), None)
ui.end_placement()
check("a band across the page", view.breaks == [[0.0, -100.0, 100.0]],
      view.breaks)
left = dwg.shown(view, (box[0], 0))[0]
right = dwg.shown(view, (box[2], 0))[0]
check("the view is drawn %.0f shorter" % (200 - dwg.BREAK_GAP),
      abs((right - left) - (width_before - 200 + dwg.BREAK_GAP)) < 1e-6,
      right - left)
check("and keeps its middle", abs(left + right) < 1e-6, (left, right))
check("the zigzags either side", len(dwg.break_lines(view)) == 2)

print("dimensioned across it")
corners = [i for i in drawpick.items(view) if i.kind == drawpick.POINT]
lo = min(corners, key=lambda i: (i.a[0], i.a[1]))
hi = min((c for c in corners if abs(c.a[1] - lo.a[1]) < 1e-6),
         key=lambda i: -i.a[0])
tol = 1.0
at_lo = dwg.shown(view, lo.a)
at_hi = dwg.shown(view, hi.a)
found = drawpick.nearest(sheet, (view.x + at_hi[0], view.y + at_hi[1]), tol)
check("the far corner is picked where it is drawn", found is not None
      and found.same(hi), found)
ui.start_dimension_set("chain")
tool = ui._placer
tool.press((view.x + at_lo[0], view.y + at_lo[1]), None)
tool.press((view.x + at_hi[0], view.y + at_hi[1]), None)
tool.right_click(None, None)
tool.press((view.x, view.y + box[1] - 15), None)
ui.end_placement()
note = sheet.annotations[-1]
check("the overall length reads 600, not what is drawn",
      abs(note.measure() / scale - 600) < 1e-6
      and dwg.broken_note(note, view, scale).caption(scale) == "600",
      (note.measure() / scale,
       dwg.broken_note(note, view, scale).caption(scale)))

print("painted and exported")
errors = []
hook = sys.excepthook
sys.excepthook = lambda *a: errors.append(a[1])
shot = ui.canvas.grab()
pump()
sys.excepthook = hook
check("the sheet paints", not shot.isNull() and not errors, errors)
shot.save(os.path.join(WORK, "break.png"))
print("    picture:", os.path.join(WORK, "break.png"))
dxf = os.path.join(WORK, "bar.dxf")
drawingexport.to_dxf(win.drawing, sheet, dxf)
text = open(dxf, encoding="utf-8", errors="replace").read()
check("the DXF is written", "LINE" in text)

print("saved, and made whole")
win.save_document()
back = dwg.DrawingDocument.load(win.drawing.path)
check("the break comes back", back.active().views[0].breaks
      == [[0.0, -100.0, 100.0]])
ui.canvas.select([view.id])
ui.remove_breaks()
check("Remove Breaks makes it whole", view.breaks == [])

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
