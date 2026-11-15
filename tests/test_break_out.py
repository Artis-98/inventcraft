"""Break Out views (#280), as Inventor's.

The plate's front view shows its holes only as hidden lines.  An outline
clicked round one of them, closed with a right-click and given a depth,
opens the view there: the material in front is taken away, what it laid
bare is hatched, the hole's walls are drawn as seen, and the rest of the
view stays exactly where it was.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core import hlr                                      # noqa: E402
from datum.core.features import CUT, PrimitiveFeature           # noqa: E402
from datum.ui import drawing_tools, drawpick                    # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_breakout_")


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
d.a.set_text("80")
d.b.set_text("40")
d.c.set_text("10")
d.commit()
for x in ("20", "60"):
    hole = PrimitiveFeature()
    hole.kind, hole.a, hole.b = "cylinder", "4", "20"
    hole.origin = [x, "20", "-5"]
    hole.operation = CUT
    win.document.add_feature(hole)
win.document.rebuild()
part = os.path.join(WORK, "Plate.icpart")
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
session.dialog._set_style(dwg.WITH_HIDDEN)
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



projection = view.projection
box_before = projection.box
check("the front view: no cut faces yet",
      not projection.of_kind(hlr.CUT))
hidden_before = len(projection.of_kind(hlr.HIDDEN))

print("opened round the left hole")
ui.add_break_out()
tool = ui._placer
check("the tool is armed", isinstance(tool, drawing_tools.BreakOutTool))
# a square round x 20 of the 80 long plate, the view centred on it
left = box_before[0]
cx = left + 20.0 * win.drawing.view_scale(sheet, view)
y0, y1 = box_before[1] - 2, box_before[3] + 2
for x, y in ((cx - 8, y0), (cx + 8, y0), (cx + 8, y1), (cx - 8, y1)):
    tool.press((view.x + x, view.y + y), None)
check("four corners", len(tool.points) == 4)
ui.break_out(sheet, view, [list(p) for p in tool.points], depth=20.0)
tool.points = []
ui.end_placement()
pump(40)
projection = view.projection
check("drawn", projection is not None and not view.error, view.error)
check("what was laid bare is hatched", bool(projection.of_kind(hlr.CUT)),
      [l.kind for l in projection.lines][:20])
check("the view has not moved", all(abs(a - b) < 1e-6 for a, b in
                                     zip(projection.box, box_before)),
      (projection.box, box_before))
check("one hole's walls are no longer hidden",
      len(projection.of_kind(hlr.HIDDEN)) < hidden_before,
      (len(projection.of_kind(hlr.HIDDEN)), hidden_before))
shot = ui.canvas.grab()
shot.save(os.path.join(WORK, "breakout.png"))
print("    picture:", os.path.join(WORK, "breakout.png"))

print("saved, and whole again")
win.save_document()
back = dwg.DrawingDocument.load(win.drawing.path)
check("the break out comes back", len(back.active().views[0].breakout) == 4
      and back.active().views[0].breakout_depth == 20.0)
ui.canvas.select([view.id])
ui.remove_breaks()
pump(40)
check("Remove Breaks closes it", not view.breakout
      and view.projection is not None
      and not view.projection.of_kind(hlr.CUT))

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
