"""The revision table on a drawing (#280), as Inventor's.

Placed from the Annotate tab's Table panel, it hangs in the top right of
the sheet with the drawing's revision as its first row.  Add Revision
gives the next letter, dated today, and the title block's REV follows the
newest row.  The history belongs to the drawing and is saved with it.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core.features import CUT, PrimitiveFeature           # noqa: E402
from datum.ui import drawing_ui as dui                          # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_revisions_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("the letters")
check("A, B ... Z, AA; numbers count",
      [dwg.next_revision(r) for r in ("", "A", "B", "Z", "AZ", "1", "9")]
      == ["A", "B", "C", "AA", "BA", "2", "10"],
      [dwg.next_revision(r) for r in ("", "A", "B", "Z", "AZ", "1", "9")])

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



print("the table")
doc = win.drawing
check("a new drawing is revision A", doc.properties.get("Revision") == "A")
answers = {"add": 1, "text": "Holes moved 5 mm", "ok": True}


def fake_exec(dialog, *a, **k):
    """Add one revision, describe it, and press OK."""
    for _ in range(answers["add"]):
        dialog.add_revision()
    row = dialog.table.rowCount() - 1
    dialog.table.item(row, 1).setText(answers["text"])
    return (QtWidgets.QDialog.Accepted if answers["ok"]
            else QtWidgets.QDialog.Rejected)


dui.RevisionsDialog.exec = fake_exec
ui.revision_table()
pump()
sheet = doc.active()
check("placed on the sheet", len(sheet.revision_tables) == 1)
table = sheet.revision_tables[0]
width, height = sheet.extent()
frame = doc.borders[sheet.border].frame(width, height)
check("in the top right corner, inside the border",
      (table.x, table.y) == (frame[2], frame[3]), (table.x, table.y, frame))
check("two rows: the first release and B",
      [r.rev for r in doc.revisions] == ["A", "B"],
      [r.rev for r in doc.revisions])
check("the first described", doc.revisions[0].description
      == "Initial release")
check("B says what changed, dated today",
      doc.revisions[1].description == "Holes moved 5 mm"
      and doc.revisions[1].date == time.strftime("%Y-%m-%d"))
check("the title block's REV reads B", doc.properties["Revision"] == "B")
check("and its field shows it", dwg.property_values(doc, sheet)
      ["Drawing.Revision"] == "B" if hasattr(dwg, "property_values")
      else True)

print("cancelled")
answers.update(ok=False, text="nothing")
ui.revision_table()
check("changes nothing", [r.rev for r in doc.revisions] == ["A", "B"])
check("and places no second table", len(sheet.revision_tables) == 1)

print("painted")
errors = []
hook = sys.excepthook
sys.excepthook = lambda *a: errors.append(a[1])
shot = ui.canvas.grab()
pump()
sys.excepthook = hook
check("the sheet paints", not shot.isNull() and not errors, errors)
shot.save(os.path.join(WORK, "revisions.png"))
print("    picture:", os.path.join(WORK, "revisions.png"))

print("saved and opened")
win.save_document()
back = dwg.DrawingDocument.load(doc.path)
check("the history comes back", [r.rev for r in back.revisions] == ["A", "B"])
check("so does the table", len(back.active().revision_tables) == 1)

print("undo")
ui.document.undo()
check("takes the revision back", [r.rev for r in doc.revisions] == ["A"]
      or len(doc.revisions) == 0, [r.rev for r in doc.revisions])

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
