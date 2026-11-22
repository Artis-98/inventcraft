"""Arrange Balloons: two tidy columns, no leader crossing another.

Balloons scattered at random round an assembly view are put into a
column each side of it, every one on the side its part is on, and no
two leaders cross. One undo puts them back.
"""
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import drawing as dwg                              # noqa: E402
from datum.core import hlr                                         # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_arrange_")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "examples", "excavator", "Excavator.adat")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=250):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)


def crosses(a, b, c, d):
    def turn(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2 = turn(c, d, a), turn(c, d, b)
    d3, d4 = turn(a, b, c), turn(a, b, d)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Arrange.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
d, u = hlr.ORIENTATIONS["front"]
view = ui.create_views({"path": MODEL, "scale": 0.05, "name": "Front"},
                       d, u, 200.0, 150.0, [])
ui.refine_now(300)
settle(200)
sheet = win.drawing.active()
ui.canvas.select([view.id])
ui.auto_balloon()
settle(200)
balloons = [a for a in sheet.annotations_for(view.id)
            if a.kind == dwg.BALLOON]
check("there are balloons to arrange", len(balloons) >= 4, len(balloons))

random.seed(7)
for note in balloons:
    note.offset = [random.uniform(-60, 60), random.uniform(-60, 60)]
before = [list(n.offset) for n in balloons]

moved = ui.arrange_balloons(view.id)
check("every balloon moved", moved == len(balloons), moved)
box = view.projection.box
seats = [(n.points[0][0] + n.offset[0], n.points[0][1] + n.offset[1])
         for n in balloons]
check("all clear of the view, left or right",
      all(s[0] < box[0] or s[0] > box[2] for s in seats))
columns = {round(s[0], 6) for s in seats}
check("in two columns", len(columns) <= 2, columns)
legs = [((n.points[0][0], n.points[0][1]), s)
        for n, s in zip(balloons, seats)]
crossing = [(i, j) for i in range(len(legs)) for j in range(i + 1, len(legs))
            if crosses(legs[i][0], legs[i][1], legs[j][0], legs[j][1])]
check("no leader crosses another", not crossing, crossing)
same_side = all((s[0] < box[0]) == (n.points[0][0] < (box[0] + box[2]) / 2)
                for n, s in zip(balloons, seats))
check("each on the side of its part", same_side)

settle(300)
ui.canvas.grab().save(os.path.join(WORK, "arranged.png"))
print("  picture:", os.path.join(WORK, "arranged.png"))
win.drawing.undo()
settle(100)
again = [a for a in win.drawing.active().annotations_for(view.id)
         if a.kind == dwg.BALLOON]
check("one undo puts them back", [list(n.offset) for n in again] == before)

win.drawing.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
