"""Baseline, Ordinate and Chain dimension sets on a real drawing (#280).

As Inventor's: the corners and holes are clicked in turn, the first the
datum, right-click Continue, then the set is dropped.  Above the picks,
the set measures across the page; beside them, up it."""
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


print("worked by hand")
pts = [(0.0, 0.0), (20.0, 5.0), (60.0, 5.0), (80.0, 0.0)]
made = drawing_tools.dimension_set("baseline", pts, (40.0, 30.0))
check("a baseline set above: three, all across the page",
      len(made) == 3 and all(n.axis == "x" for n in made))
check("each from the datum, reading 20, 60 and 80",
      [round(n.measure(), 6) for n in made] == [20.0, 60.0, 80.0],
      [n.measure() for n in made])
check("stacked a line apart", [n.offset[1] for n in made]
      == [30.0, 30.0 + drawing_tools.SET_SPACING,
          30.0 + 2 * drawing_tools.SET_SPACING], [n.offset for n in made])
made = drawing_tools.dimension_set("chain", pts, (40.0, -20.0))
check("a chain below: 20, 40, 20 on one line",
      [round(n.measure(), 6) for n in made] == [20.0, 40.0, 20.0]
      and len({round(dwg.dimension_line(n)[0][1], 6) for n in made}) == 1,
      [(n.measure(), dwg.dimension_line(n)[0]) for n in made])
made = drawing_tools.dimension_set("ordinate", pts, (100.0, 2.0))
check("an ordinate set beside them reads up the page: 0, 0, 5, 5",
      sorted(round(n.measure(), 6) for n in made) == [0.0, 0.0, 5.0, 5.0]
      and all(n.axis == "y" for n in made),
      [(n.axis, n.measure()) for n in made])

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

print("on the sheet")
corners = sorted((i for i in drawpick.items(view) if i.kind == drawpick.POINT),
                 key=lambda i: (round(i.a[1], 3), i.a[0]))
low = [c for c in corners if abs(c.a[1] - corners[0].a[1]) < 1e-6]
check("the plate's corners can be picked", len(low) >= 2, len(corners))
holes = sorted(top_like, key=lambda i: i.a[0])
picks = [low[0]] + holes + [low[-1]]


def run(kind, drop):
    before = len(sheet.annotations)
    ui.start_dimension_set(kind)
    tool = ui._placer
    for item in picks:
        point = item.a if item.kind != drawpick.CIRCLE else (
            item.a[0] + item.radius, item.a[1])
        tool.press(at(point), None)
    took = len(tool.picks)
    tool.right_click(at(drop), None)
    tool.press(at(drop), None)
    ui.end_placement()
    return took, sheet.annotations[before:]


took, made = run("baseline", (low[0].a[0], low[0].a[1] - 20))
check("baseline took every pick", took == len(picks), took)
scale = win.drawing.view_scale(sheet, view)
values = sorted(round(n.measure() / scale, 3) for n in made)
check("baseline: 20, 60 and 80 from the left edge", values == [20.0, 60.0,
                                                               80.0], values)
check("each tied to the model", all(n.anchored for n in made))
took, made = run("chain", (low[0].a[0], low[0].a[1] - 40))
values = [round(n.measure() / scale, 3) for n in made]
check("chain: 20, 40, 20", sorted(values) == [20.0, 20.0, 40.0], values)
took, made = run("ordinate", (low[0].a[0], low[0].a[1] - 60))
values = sorted(round(n.measure() / scale, 3) for n in made)
check("ordinate: 0, 20, 60, 80", values == [0.0, 20.0, 60.0, 80.0], values)
check("ordinates measure across", all(n.axis == "x" for n in made))

print("painted without trouble")
from PySide6 import QtGui  # noqa: E402
errors = []
old_hook = sys.excepthook
sys.excepthook = lambda *a: errors.append(a[1])
shot = ui.canvas.grab()
pump()
sys.excepthook = old_hook
check("the sheet paints", not shot.isNull() and not errors, errors)
shot.save(os.path.join(WORK, "sets.png"))
print("    picture:", os.path.join(WORK, "sets.png"))

print("undo takes a whole set back")
count = len(sheet.annotations)
win.undo()
pump()
sheet = win.drawing.active()
check("four ordinates gone at once", len(sheet.annotations) == count - 4,
      (count, len(sheet.annotations)))

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
