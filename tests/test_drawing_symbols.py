"""Surface texture, feature control frame and datum identifier (#280).

Each is placed as Inventor's: the tool is picked, the edge clicked, what
it says set in its box, and it stands on that edge.  They are saved with
the drawing and drawn on the sheet.
"""
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
WORK = tempfile.mkdtemp(prefix="datum_symbols_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("frame cells")
check("position, a diameter zone, two datums",
      dwg.fcf_cells("position|Ø0.1|A|B")
      == [dwg.gdt_symbol("position"), "Ø0.1", "A", "B"],
      dwg.fcf_cells("position|Ø0.1|A|B"))
check("empty says nothing", dwg.fcf_cells("") == [])

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


print("on the sheet")
lines = [i for i in drawpick.items(view) if i.kind == drawpick.LINE]
edge = max(lines, key=lambda i: abs(i.b[0] - i.a[0]))
middle = ((edge.a[0] + edge.b[0]) / 2, (edge.a[1] + edge.b[1]) / 2)
values = {}


def fake_exec(dialog, *a, **k):
    values[dialog.kind] = dialog.values()
    return QtWidgets.QDialog.Accepted


drawing_tools.SymbolDialog.exec = fake_exec
spots = {}
for n, kind in enumerate((dwg.SURFACE, dwg.FCF, dwg.DATUM_ID)):
    before = len(sheet.annotations)
    ui.add_symbol_tool(kind)
    tool = ui._placer
    # along the edge, a little apart, as somebody would put them
    t = 0.2 + 0.3 * n
    spot = (edge.a[0] + (edge.b[0] - edge.a[0]) * t,
            edge.a[1] + (edge.b[1] - edge.a[1]) * t)
    spots[kind] = spot
    tool.press(at(spot), None)
    ui.end_placement()
    check("%s placed" % kind, len(sheet.annotations) == before + 1
          and sheet.annotations[-1].kind == kind)
surface, frame, datum = sheet.annotations[-3:]
check("the surface: machined, Ra 3.2",
      surface.shape == dwg.SURFACE_REMOVAL and surface.text == "Ra 3.2",
      (surface.shape, surface.text))
check("it stands on the edge",
      abs(surface.points[0][1] - spots[dwg.SURFACE][1]) < 1e-6,
      surface.points)
box = view.projection.box
inward = (box[1] + box[3]) / 2.0 - surface.points[0][1]
check("and faces out of the part, not into it",
      all(n.offset[1] * inward <= 0 for n in (surface, frame, datum)),
      [n.offset for n in (surface, frame, datum)])
check("the frame: position, Ø0.1, A, B",
      dwg.fcf_cells(frame.text)[1:] == ["Ø0.1", "A", "B"], frame.text)
check("the datum takes the first free letter", datum.text == "A",
      datum.text)
ui.add_symbol_tool(dwg.DATUM_ID)
ui._placer.press(at(middle), None)
ui.end_placement()
check("and the next one B", sheet.annotations[-1].text == "B",
      sheet.annotations[-1].text)

print("a weld")
values.clear()


def weld_exec(dialog, *a, **k):
    dialog.weld.setCurrentIndex([k for k, _l in dwg.WELDS].index("fillet"))
    dialog.size.setText("a5")
    dialog.length.setText("100")
    dialog.around.setChecked(True)
    dialog.field.setChecked(True)
    values[dialog.kind] = dialog.values()
    return QtWidgets.QDialog.Accepted


drawing_tools.SymbolDialog.exec = weld_exec
ui.add_symbol_tool(dwg.WELD)
ui._placer.press(at((edge.a[0] + (edge.b[0] - edge.a[0]) * 0.9,
                     edge.a[1])), None)
ui.end_placement()
weld = sheet.annotations[-1]
check("a weld symbol placed", weld.kind == dwg.WELD)
kind, size, length, flags = dwg.weld_parts(weld.text)
check("fillet a5, 100 long, all round, on site",
      (kind, size, length) == ("fillet", "a5", "100")
      and flags == {"all_around", "field"}, weld.text)

print("painted")
errors = []
hook = sys.excepthook
sys.excepthook = lambda *a: errors.append(a[1])
shot = ui.canvas.grab()
pump()
sys.excepthook = hook
check("the sheet paints", not shot.isNull() and not errors, errors)
shot.save(os.path.join(WORK, "symbols.png"))
print("    picture:", os.path.join(WORK, "symbols.png"))

print("saved")
win.save_document()
back = dwg.DrawingDocument.load(win.drawing.path)
kinds = [n.kind for n in back.active().annotations]
check("all five come back", kinds.count(dwg.DATUM_ID) == 2
      and dwg.SURFACE in kinds and dwg.FCF in kinds and dwg.WELD in kinds,
      kinds)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
