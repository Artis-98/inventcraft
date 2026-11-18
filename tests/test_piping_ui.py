"""Insert Pipe and the Cut List, in the window.

Insert Pipe is Insert Frame set to copper tube: no orientation to set, a
bend radius and insulation instead.  The picked lines become pipes, the
green preview shows them bent, and the Cut List lists them with their
totals and saves them as CSV.  Set DATUM_SHOTS to a folder for pictures.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtCore, QtWidgets                             # noqa: E402

from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import SketchFeature                     # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402
from datum.ui.main_window import MainWindow                       # noqa: E402
from datum.ui.theme import stylesheet                             # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_piping_ui_")
SHOTS = os.environ.get("DATUM_SHOTS", "")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


skeleton = Document()
route = SketchFeature(name="Route")
route.sketch = Sketch(SketchPlane((0.0, 0.0, 300.0), (0.0, 0.0, 1.0)),
                      "Route")
s = route.sketch
s.add_line((0.0, 0.0), (1000.0, 0.0))
s.add_line((1000.0, 0.0), (1000.0, 500.0))
s.add_line((1000.0, 500.0), (1500.0, 500.0))
s.add_line((0.0, 300.0), (600.0, 300.0))
skeleton.add_feature(route)
# a riser in a sketch of its own, standing up from the route's far end
riser = SketchFeature(name="Riser")
riser.sketch = Sketch(SketchPlane((1500.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                  (0.0, 1.0, 0.0)), "Riser")
riser.sketch.add_line((500.0, 300.0), (500.0, 700.0))
skeleton.add_feature(riser)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Route"))
plant = AssemblyDocument()
plant.path = os.path.join(WORK, "Plant.icasm")
plant.place(skeleton_path)
plant.save(plant.path)
win.open_path(plant.path)
settle(800)

print("Insert Pipe")
dialog = win.insert_pipe()
settle(200)
check("it opens on copper tube",
      dialog.windowTitle() == "Insert Pipe" and dialog.is_pipe()
      and dialog.category.currentText().startswith("Piping"))
check("with a bend radius and insulation, and no orientation",
      not dialog.pipe_group.isHidden()
      and dialog.orientation_group.isHidden())
check("Merge into one pipe is ticked",
      not dialog.merge.isHidden() and dialog.merge.isChecked()
      and dialog.merge.text() == "Merge into one pipe")
lone = next(k for k, (a, b) in dialog.candidates().items()
            if abs(a[1] - 300.0) < 1e-6 and abs(b[1] - 300.0) < 1e-6)
dialog.add_lines([lone])
check("one line alone: nothing to merge, so it is not offered",
      not dialog.merge.isEnabled())
dialog.clear()
check("the radius says what the size's own is",
      "mm" in dialog.bend_radius.specialValueText(),
      dialog.bend_radius.specialValueText())
dialog.choose("en-12735-1-copper", "22x1")
dialog.add_lines(list(dialog.candidates()))
check("five lines in two sketches, joined: Merge is offered",
      len(dialog.picked()) == 5 and dialog.merge.isEnabled())
dialog.merge.setChecked(False)
check("unticked, each line is a pipe of its own",
      len(dialog.preview_solids()) == 5)
dialog.merge.setChecked(True)
dialog.insulation.setValue(13.0)
check("insulation picks its material", dialog.insulation_material.isEnabled()
      and dialog.insulation_material.currentText() == "Elastomeric Foam")
solids = dialog.preview_solids()
check("the preview is the two pipes", len(solids) == 2, len(solids))
if SHOTS:
    dialog.draw_preview()
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(400)
    win.viewport.grab_image(os.path.join(SHOTS, "pipe_preview.png"))
    dialog.grab().save(os.path.join(SHOTS, "pipe_dialog.png"))
check("it applies", dialog.apply(), dialog.message.text())
dialog.close()
settle(400)

print("a frame member back to a frame family")
dialog = win.insert_frame()
settle(100)
dialog.choose("en-10219-chs", dialog.current_family().sizes()[0]
              if dialog.current_family().id == "en-10219-chs" else
              "CHS21.3x2.6")
check("a steel family shows the orientation again, no pipe box",
      dialog.pipe_group.isHidden() and not dialog.orientation_group.isHidden())
dialog.close()

print("Pipe Corners")
win.viewport.set_view("iso")
win.viewport.fit_all()
settle(400)
mode = win.pipe_corners()
settle(300)
kinds = [c.kind for _f, c, _a in mode._corners]
check("piping mode on: the merged run's three corners, all bends",
      mode.active and kinds == ["bend"] * 3, kinds)
check("a small button on each, beside its corner, nothing else open",
      len(mode.chips) == 3 and all(c.isVisible() for c in mode.chips)
      and all(c.width() < 80 and c.height() < 40 for c in mode.chips),
      [(c.isVisible(), c.width(), c.height()) for c in mode.chips])
chip = mode.chips[0]
x, y = win.viewport.project(mode._corners[0][2])
spot = win.viewport.mapFromGlobal(chip.pos())
check("just above and right of its corner",
      0 < spot.x() - x < 30 and 0 < y - spot.y() < 60,
      (x, y, spot.x(), spot.y()))
items = [a.text() for a in chip.button.menu().actions()]
check("its menu: a bend (as it is, ticked) or an elbow fitting",
      len(items) == 2 and items[0].startswith("Bend")
      and items[1].startswith("Elbow fitting")
      and chip.button.menu().actions()[0].isChecked(), items)
win.viewport.set_view("top")
settle(300)
moved = win.viewport.mapFromGlobal(mode.chips[0].pos())
x2, y2 = win.viewport.project(mode._corners[0][2])
check("the view turned, the buttons follow their corners",
      0 < moved.x() - x2 < 30 and 0 < y2 - moved.y() < 60,
      (x2, y2, moved.x(), moved.y()))
win.viewport.set_view("iso")
win.viewport.fit_all()
settle(300)
chip.button.menu().actions()[1].trigger()
settle(300)
kinds = sorted(c.kind for _f, c, _a in mode._corners)
check("Elbow fitting chosen: two bends and an elbow now",
      kinds == ["bend", "bend", "elbow90"], kinds)
elbow_chip = next(c for c in mode.chips if c.corner.kind == "elbow90")
check("and its button shows the elbow, Elbow ticked in its menu",
      elbow_chip.button.menu().actions()[1].isChecked())
if SHOTS:
    settle(300)
    top = win.window()
    shot = app.primaryScreen().grabWindow(
        0, top.x(), top.y(), top.frameGeometry().width(),
        top.frameGeometry().height())
    shot.save(os.path.join(SHOTS, "pipe_corners_chips.png"))
    menu = mode.chips[0].button.menu()
    menu.popup(mode.chips[0].mapToGlobal(
        QtCore.QPoint(0, mode.chips[0].height())))
    settle(300)
    shot = app.primaryScreen().grabWindow(
        0, top.x(), top.y(), top.frameGeometry().width(),
        top.frameGeometry().height())
    shot.save(os.path.join(SHOTS, "pipe_corners_menu.png"))
    menu.hide()
row = mode.chips.index(elbow_chip)
check("and back to a bend", mode.choose(row, "bend")
      and sorted(c.kind for _f, c, _a in mode._corners) == ["bend"] * 3)
mode.choose(0, "elbow")
win.viewport.escape_pressed.emit()
settle(200)
check("Esc ends piping mode, the buttons go",
      not mode.active and not mode.chips)
settle(200)

print("the Cut List")
cut = win.pipe_cut_list()
settle(200)
check("the three pipes in it, the run split at its elbow",
      cut.table.rowCount() == 3, cut.table.rowCount())
totals = [cut.totals.item(i, 0).text() for i in range(cut.totals.rowCount())]
check("the 22 x 1 totalled, its insulation, and the elbow",
      "22x1" in totals and any(t.startswith("Insulation 13") for t in totals)
      and "Elbow 90 22" in totals, totals)
out = cut.export(os.path.join(WORK, "cut.csv"))
check("and saved as CSV", out and "Total tube m" in open(out).read())
if SHOTS:
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(600)
    win.viewport.grab_image(os.path.join(SHOTS, "pipe_built.png"))
    cut.grab().save(os.path.join(SHOTS, "pipe_cutlist.png"))
cut.close()

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
