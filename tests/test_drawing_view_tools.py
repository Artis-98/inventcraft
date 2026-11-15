"""Section, crop, Delete and dragging on a drawing (#280), as Inventor's.

A bar 600 x 30 x 20 is drawn front on.  Section is a view clicked, then
a line drawn across it at any angle, then the new view dragged out to one
side: a short line gives a section only as wide as the line.  Crop keeps
what is inside a rectangle.  Delete takes the selected view off.  A
dimension picked right to left follows the mouse when dragged, and the
browser no longer lists every dimension under its view.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtTest, QtWidgets                   # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.ui import drawing_tools                              # noqa: E402
from datum.ui.main_window import MainWindow                     # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_viewtools_")


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
win.document.rebuild()
win.document.path = os.path.join(WORK, "Bar.icpart")
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
session.dialog.place_requested.emit()
pump(40)
sheet = win.drawing.active()
view = sheet.views[0]
box = view.projection.box
width = box[2] - box[0]
check("the bar is drawn 300 across at 1:2", abs(width - 300) < 0.5, width)
ui.canvas.select([], [])

print("section: the view, a short line along it, then out to one side")
ui.add_section()
tool = ui._placer
check("the tool is armed", isinstance(tool, drawing_tools.SectionTool))
check("it waits for a view", tool.view is None)
tool.press((view.x + 10, view.y), None)
check("the view is taken by its box", tool.view is view)
mid_y = (box[1] + box[3]) / 2
tool.press((view.x - 50, view.y + mid_y + 0.3), None)
tool.press((view.x + 50, view.y + mid_y - 0.4), None)
check("two ends drawn, the second pulled level",
      len(tool.points) == 2
      and abs(tool.points[1][1] - tool.points[0][1]) < 1e-9, tool.points)
before = len(sheet.views)
tool.press((view.x, view.y - 80), None)
pump(40)
check("a section is placed", len(sheet.views) == before + 1)
section = sheet.views[-1]
check("it is a section of the bar", section.kind == dwg.SECTION
      and section.parent == view.id and section.bounded, section.kind)
check("drawn", section.projection is not None, section.error)
sbox = section.projection.box
check("only as wide as the line: 100 across, not 300",
      abs((sbox[2] - sbox[0]) - 100) < 0.5, sbox)
check("and the 30 depth of the bar shows at 1:2",
      abs((sbox[3] - sbox[1]) - 15) < 0.5, sbox)
check("placed straight out from the line", abs(section.x - view.x) < 0.01
      and section.y < view.y, (section.x, section.y))
check("the tool is ready for the next one", tool.view is None
      and not tool.points)

print("the other side looks the other way")
tool.press((view.x + 10, view.y), None)
tool.press((view.x - 30, view.y + mid_y), None)
tool.press((view.x + 30, view.y + mid_y), None)
tool.press((view.x, view.y + 80), None)
pump(40)
above = sheet.views[-1]
first_angle = win.drawing.angle == dwg.FIRST_ANGLE
c1, c2 = section.cut, above.cut
check("the cut runs the other way round, so it looks from the other side",
      (c1[2] - c1[0]) * (c2[2] - c2[0]) < 0, (c1, c2))
check("first angle puts the view away from where it is looked from",
      not first_angle or c1[2] > c1[0], c1)
ui.end_placement()

print("Esc steps back a stage at a time")
ui.add_section()
tool = ui._placer
tool.press((view.x + 10, view.y), None)
tool.press((view.x - 30, view.y), None)
check("Esc drops the point", tool.escape() and not tool.points)
check("then the view", tool.escape() and tool.view is None)
check("then lets go", not tool.escape())
ui.end_placement()

print("crop")
ui.add_crop()
tool = ui._placer
check("the tool is armed", isinstance(tool, drawing_tools.CropTool))
tool.press((view.x, view.y), None)
tool.press((view.x - 60, view.y - 20), None)
tool.press((view.x + 40, view.y + 20), None)
pump(40)
ui.end_placement()
cbox = view.projection.box
check("the view keeps only what is in the rectangle: 100 across",
      abs((cbox[2] - cbox[0]) - 100) < 0.5 and abs(cbox[0] + 60) < 0.5,
      cbox)
check("and says so in the file", view.to_dict().get("crop")
      == [-60.0, -20.0, 40.0, 20.0], view.to_dict().get("crop"))
ui.canvas.select([view.id])
ui.remove_breaks()
pump(40)
rbox = view.projection.box
check("Remove Breaks gives it back whole", not view.crop
      and abs((rbox[2] - rbox[0]) - 300) < 0.5, rbox)

print("Delete")
ui.canvas.select([above.id])
count = len(sheet.views)
ui.canvas.setFocus()
QtTest.QTest.keyClick(ui.canvas, QtCore.Qt.Key_Delete)
pump(20)
check("the Delete key takes the selected view off",
      len(sheet.views) == count - 1
      and all(v.id != above.id for v in sheet.views), len(sheet.views))

print("dragging a dimension")
note = dwg.Annotation(kind=dwg.LINEAR, view=view.id,
                      points=[[100.0, 0.0], [-100.0, 0.0]],
                      offset=[0.0, 20.0], axis="x")
win.drawing.add_annotation(sheet, note)
before = dwg.label_at(note)
note.offset = dwg.dragged_offset(note, note.offset, 15.0, 5.0)
after = dwg.label_at(note)
check("picked right to left, its value still follows the mouse",
      abs((after[0] - before[0]) - 15.0) < 1e-6
      and abs((after[1] - before[1]) - 5.0) < 1e-6, (before, after))
slant = dwg.Annotation(kind=dwg.ALIGNED, view=view.id,
                       points=[[0.0, 0.0], [-30.0, 40.0]],
                       offset=[0.0, 10.0], axis="aligned")
before = dwg.label_at(slant)
slant.offset = dwg.dragged_offset(slant, slant.offset, 7.0, -3.0)
after = dwg.label_at(slant)
check("an aligned one goes where it is dragged too",
      abs((after[0] - before[0]) - 7.0) < 1e-6
      and abs((after[1] - before[1]) + 3.0) < 1e-6, (before, after))

print("the browser")
ui.browser.refresh()
from datum.ui.drawing_browser import ROLE_KIND                   # noqa: E402
kinds = []
stack = [ui.browser.topLevelItem(i)
         for i in range(ui.browser.topLevelItemCount())]
while stack:
    item = stack.pop()
    kinds.append(item.data(0, ROLE_KIND))
    stack += [item.child(i) for i in range(item.childCount())]
check("views are listed", "view" in kinds, kinds)
check("dimensions are not", "note" not in kinds, kinds)

shot = ui.canvas.grab()
shot.save(os.path.join(WORK, "view_tools.png"))
print("    picture:", os.path.join(WORK, "view_tools.png"))

print("saved")
win.save_document()
back = dwg.DrawingDocument.load(win.drawing.path)
kept = next(v for v in back.active().views if v.id == section.id)
check("a bounded section comes back bounded", kept.bounded)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
