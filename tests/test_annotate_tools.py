"""The Annotate tab's tools, picked on a real drawing as Inventor's are:
Center Mark on a circle, Centerline between two points, Centerline
Bisector between two lines, and Hole and Thread on one hole, counted."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core.features import CUT, PrimitiveFeature           # noqa: E402
from datum.ui import drawing_tools, drawpick                    # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_annotate_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("bisector, worked by hand")
L = drawpick.Item
mid = drawing_tools.bisector(L(drawpick.LINE, 1, (0, 0), (40, 0)),
                             L(drawpick.LINE, 1, (40, 10), (0, 10)))
check("between two parallel lines, down the middle and a little past",
      mid is not None and abs(mid[0][1] - 5) < 1e-9
      and abs(mid[1][1] - 5) < 1e-9
      and abs(abs(mid[1][0] - mid[0][0]) - 44) < 1e-9, mid)

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


# the top view, where the holes are circles
win.drawing_ui.canvas.select([view.id])
top_like = [i for i in drawpick.items(view) if i.kind == drawpick.CIRCLE]
if not top_like:
    # the default front view shows the holes from the side: look from above
    from datum.core import hlr
    view.direction = list(hlr.ORIENTATIONS["top"][0])
    view.up = list(hlr.ORIENTATIONS["top"][1])
    view.projection = None
    ui.rebuild(force=True)
    pump(20)
    top_like = [i for i in drawpick.items(view) if i.kind == drawpick.CIRCLE]
check("seen from above, the holes are circles to pick", len(top_like) >= 2,
      len(top_like))

hole_item = top_like[0]
before = len(sheet.annotations)
ui.add_centre_mark()
tool = ui._placer
tool.press(at((hole_item.a[0] + hole_item.radius, hole_item.a[1])), None)
check("Center Mark: a click on a circle marks it",
      len(sheet.annotations) == before + 1
      and sheet.annotations[-1].kind == dwg.CENTRE_MARK)

ui.add_hole_note()
tool = ui._placer
tool.press(at((hole_item.a[0] + hole_item.radius, hole_item.a[1])), None)
tool.press(at((hole_item.a[0] + 20, hole_item.a[1] + 15)), None)
note = sheet.annotations[-1]
check("Hole and Thread: the hole clicked, counted with its twin",
      note.kind == dwg.LEADER and note.text == "2x Ø8 THRU", note.text)

ui.add_centreline()
tool = ui._placer
a, b = top_like[0].a, top_like[1].a
tool.press(at((a[0] + top_like[0].radius, a[1])), None)
tool.press(at((b[0] + top_like[1].radius, b[1])), None)
line = sheet.annotations[-1]
check("Centerline: between the two hole centres, and a little past",
      line.kind == dwg.CENTRELINE and len(line.points) == 2
      and abs(abs(line.points[1][0] - line.points[0][0]) - 44) < 1e-6,
      line.points)
ui.end_placement()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
