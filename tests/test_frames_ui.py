"""The Frame Generator in the window: the Design tab, Insert Frame with
lines clicked in the view, the frame following its skeleton, and the
Profile Library."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
WORK = tempfile.mkdtemp(prefix="datum_frames_ui_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from datum.core import frames, kernel                             # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import SketchFeature                     # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402
from datum.ui.main_window import TAB_DESIGN, MainWindow           # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
SHOTS = os.environ.get("DATUM_SHOTS", "")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()


def pump(n=4):
    for _ in range(n):
        app.processEvents()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


# a table's skeleton: its top, a rectangle at 750
skeleton = Document()
top = SketchFeature(name="Top")
top.sketch = Sketch(SketchPlane((0.0, 0.0, 750.0), (0.0, 0.0, 1.0)), "Top")
top.sketch.add_rectangle((0.0, 0.0), (1000.0, 600.0))
skeleton.add_feature(top)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Table skeleton"))
table = AssemblyDocument()
table.path = os.path.join(WORK, "Table.icasm")
table.place(skeleton_path)
table.save(table.path)

# ==========================================================================
print("the Design tab")
win.open_path(table.path)
settle(800)
check("an assembly has the Design tab", win.ribbon._buttons[TAB_DESIGN]
      .isVisible())

print("Insert Frame")
dialog = win.insert_frame()
pump()
check("it finds the skeleton and its sketch",
      dialog.skeleton.count() == 1 and dialog.sketch.count() == 1)
check("and lists its four lines", dialog.lines.count() == 4)
check("the families are offered by category",
      [dialog.category.itemText(i) for i in range(dialog.category.count())]
      [:2] == ["Angles", "Square Tubes"])
win.viewport.set_view("top")
win.viewport.fit_all()
settle(400)
dialog._redraw()
pump()
# a click on a line in the view picks it
lines = dialog.current_lines()
first = next(iter(lines))
a, b = lines[first]
mid = tuple((a[i] + b[i]) / 2 for i in range(3))
x, y = win.viewport.project(mid)
for kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
    pos = QtCore.QPointF(x, y)
    event = QtGui.QMouseEvent(kind, pos, win.viewport.mapToGlobal(pos),
                              QtCore.Qt.LeftButton,
                              QtCore.Qt.LeftButton if kind ==
                              QtCore.QEvent.MouseButtonPress
                              else QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
    dialog.eventFilter(win.viewport, event)
check("a click on a line in the view picks it", dialog.picked() == [first],
      dialog.picked())
if SHOTS:
    win.viewport.grab_image(os.path.join(SHOTS, "frame_pick.png"))
dialog._tick_all(True)
check("All Lines takes the rest", len(dialog.picked()) == 4)
check("a family and size are chosen",
      dialog.choose("din-en-10219-2-square", "40 x 40 x 3"))
check("it applies", dialog.apply(), dialog.message.text())
pump()
asm = win.assembly
frame_occurrences = [o for o in asm.occurrences if o.follows]
check("the frame is placed, following the skeleton",
      len(frame_occurrences) == 1)
box = kernel.bounding_box(asm.shape)
check("four tubes round the top", near(box[0], -20, 0.05)
      and near(box[3], 1020, 0.05) and near(box[5], 770, 0.05),
      [round(c, 2) for c in box])
dialog.close()
pump()
if SHOTS:
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(500)
    win.viewport.grab_image(os.path.join(SHOTS, "frame_table.png"))

print("the skeleton edited, Refresh")
part = Document.load(skeleton_path)
sid = next(iter(part.all_sketches()))
for point in part.all_sketches()[sid].points.values():
    if near(point.y, 600.0):
        point.y = 800.0
part.rebuild()
part.save(skeleton_path)
win.assembly_ui.rebuild()
pump()
box = kernel.bounding_box(win.assembly.shape)
check("the frame is 800 deep now", near(box[4], 820, 0.05), box)

# ==========================================================================
print("the Profile Library")
library = win.profile_library()
pump()
names = []
for i in range(library.tree.topLevelItemCount()):
    group = library.tree.topLevelItem(i)
    names += [group.child(j).text(0) for j in range(group.childCount())]
check("it shows the families", any("10056-1" in n for n in names)
      and any("10219-2" in n for n in names), names)
check("a built in family's table is read only",
      library.current.builtin and not library.save_button.isEnabled())
check("its sizes are in the table", library.table.rowCount()
      == len(library.current.rows))
library.fill("din-en-10219-2-square")
mine = library.copy("Workshop tubes")
check("Copy makes it your own", mine is not None and not mine.builtin
      and library.save_button.isEnabled())
library.table.setRowCount(1)
for c, value in enumerate(["30x30x2", "30", "2", "3"]):
    library.table.setItem(0, c, QtWidgets.QTableWidgetItem(value))
check("your own sizes save", library.save())
check("and are in the library", frames.family("workshop-tubes").row(
    "30x30x2") == {"b": 30.0, "t": 2.0, "ro": 3.0})
library.table.setItem(0, 1, QtWidgets.QTableWidgetItem("thirty"))
check("a size that is not a number is refused, saying which",
      not library.save() and "30x30x2" in library.message.text())
library.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
