"""Project Geometry takes the lines of another sketch on show, as it takes
a model's edges: click one while projecting and it lands in the sketch
being edited."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-4):
    return abs(a - b) < tol


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
ed = win.editor


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


print("a sketch with a line, finished and on show")
win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
settle(900)
ed.sketch.add_line((0.0, 0.0), (100.0, 0.0))
ed.render()
win.finish_sketch()
settle(300)
first = win.document.sketch_features()[0]
check("an unused sketch stays visible",
      win.document.sketch_visible(first.id))

print("a second sketch: Project Geometry on the first one's line")
win.start_sketch_on_plane("XY")
settle(900)
check("the first sketch is there to see", len(ed.references) == 1,
      ed.references)
win.project_geometry()
win.viewport.set_view("top")
win.viewport.fit_all()
settle(400)
x, y = win.viewport.project((50.0, 0.0, 0.0))
win.viewport.clear_selection()
win.viewport._press_pos = QtCore.QPoint(x, y)
win._project_picked_edge()
lines = [e for e in ed.sketch.entities.values() if e.kind == "line"]
check("the line lands in the sketch being edited", len(lines) == 1,
      len(lines))
if lines:
    a, b = (ed.sketch.points[q] for q in lines[0].points)
    check("where it is, 100 long", sorted((round(a.x, 4), round(b.x, 4)))
          == [0.0, 100.0] and near(a.y, 0) and near(b.y, 0),
          (a.x, a.y, b.x, b.y))
win.viewport._press_pos = QtCore.QPoint(x, y + 200)
before = len(ed.sketch.entities)
win._project_picked_edge()
check("a click on nothing projects nothing", len(ed.sketch.entities) == before)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
