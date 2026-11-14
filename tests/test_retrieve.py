"""Retrieve Model Annotations onto a drawing view (#280, with #269).

The plate's own model annotations, a length across it, its thickness and
a diameter on a hole, are brought onto a top view.  The top view sees the
length and the hole at their true size but not the thickness, which is
square to the paper, so that one is left for another view.  Retrieving
again adds nothing twice, and what comes in is tied to the model.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from OCP.BRepAdaptor import BRepAdaptor_Curve  # noqa: E402
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line  # noqa: E402
from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import annotations as model                     # noqa: E402
from datum.core import drawing as dwg                           # noqa: E402
from datum.core import kernel                                   # noqa: E402
from datum.core.features import CUT, PrimitiveFeature           # noqa: E402
from datum.ui import drawing_tools, drawpick                    # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_retrieve_")


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
body = win.document.shape
faces = kernel.faces(body)
top = max(faces, key=lambda f: kernel.shape_centre(f)[2])
bottom = min(faces, key=lambda f: kernel.shape_centre(f)[2])
length = next(e for e in kernel.edges(body)
              if BRepAdaptor_Curve(e).GetType() == GeomAbs_Line
              and abs(kernel.edge_length(e) - 80) < 1e-6)
ring = next(e for e in kernel.edges(body)
            if BRepAdaptor_Curve(e).GetType() == GeomAbs_Circle)
for kind, picks in ((model.LINEAR, [length]), (model.LINEAR, [top, bottom]),
                    (model.DIAMETER, [ring])):
    refs, kinds = model.capture(body, picks)
    note = model.ModelAnnotation(id=win.document.new_id(), kind=kind,
                                 refs=refs, ref_kinds=kinds)
    model.evaluate(note, body)
    win.document.annotations.append(note)
check("the part has three model annotations",
      [n.display for n in win.document.annotations] == ["80", "10", "Ø8"],
      [n.display for n in win.document.annotations])
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


print("retrieved onto the top view")
found = ui.retrieve_candidates(sheet, view)
kinds = sorted(n.kind for _m, n in found)
check("the length and the hole, not the thickness",
      kinds == [dwg.DIAMETER, dwg.LINEAR], kinds)
made = ui.retrieve_into(sheet, view)
check("two brought in", made == 2, made)
scale = win.drawing.view_scale(sheet, view)
new = [n for n in sheet.annotations if n.retrieved]
length_note = next(n for n in new if n.kind == dwg.LINEAR)
check("the length reads 80", abs(length_note.measure() / scale - 80) < 1e-6,
      length_note.measure() / scale)
check("across the page", length_note.axis == "x", length_note.axis)
check("tied to the model", length_note.anchored)
hole = next(n for n in new if n.kind == dwg.DIAMETER)
check("the hole reads Ø8", hole.caption(scale).endswith("8"),
      hole.caption(scale))

print("again")
check("nothing left to bring", ui.retrieve_candidates(sheet, view) == [])
check("and nothing added", ui.retrieve_into(sheet, view) == 0)

print("the tool")
ui.retrieve_model_annotations()
tool = ui._placer
check("is armed", isinstance(tool, drawing_tools.RetrieveTool))
box = view.projection.box
inside = (view.x + (box[0] + box[2]) / 2, view.y + (box[1] + box[3]) / 2)
check("a click finds the view", tool.view_at(inside) is view)
ui.end_placement()

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
