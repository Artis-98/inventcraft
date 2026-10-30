"""Measure takes sketches as well as the model: a sketch's points, lines and
circles, in a part, while a sketch is edited, and in an assembly where its
part is placed.

A frame is built on a skeleton of sketch lines, a buggy's or a table's,
and that skeleton is what needs measuring before there is a solid to
measure at all.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                    # noqa: E402

from datum.core.assembly import AssemblyDocument                 # noqa: E402
from datum.core.constraints3d import Placement                   # noqa: E402
from datum.core.document import Document                         # noqa: E402
from datum.core.features import SketchFeature                    # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                # noqa: E402
from datum.ui.main_window import MainWindow                      # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_measure_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


app = QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1400, 900)
win.show()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


# a skeleton: a 100 x 60 rectangle on the floor and a 40 mm circle 50 up
skeleton = Document()
floor = SketchFeature(name="Floor")
floor.sketch = Sketch(SketchPlane(), "Floor")
floor.sketch.add_rectangle((0.0, 0.0), (100.0, 60.0))
skeleton.add_feature(floor)
upper = SketchFeature(name="Upper")
upper.sketch = Sketch(SketchPlane((0.0, 0.0, 50.0), (0, 0, 1), (1, 0, 0),
                                  "Upper"), "Upper")
upper.sketch.add_circle((50.0, 30.0), 20.0)
skeleton.add_feature(upper)
skeleton.rebuild()
path = skeleton.save(os.path.join(WORK, "skeleton"))


def press(x, y):
    """A left click in the view, as Measure sees it."""
    pos = QtCore.QPointF(x, y)
    for kind in (QtCore.QEvent.MouseButtonPress,
                 QtCore.QEvent.MouseButtonRelease):
        event = QtGui.QMouseEvent(
            kind, pos, win.viewport.mapToGlobal(pos), QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton if kind == QtCore.QEvent.MouseButtonPress
            else QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        eaten = win.measure_dialog.eventFilter(win.viewport, event)
    return eaten


def at(p3, shift=(0.0, 0.0)):
    x, y = win.viewport.project(p3)
    return x + shift[0], y + shift[1]


def measure_two(first, second, shift=(0.0, 0.0)):
    win.open_measure()
    settle(200)
    win.measure_dialog.restart()
    press(*at(first, shift))
    press(*at(second, shift))
    return "\n".join(win.measure_dialog.lines())


def distance(text):
    for line in text.splitlines():
        if line.startswith("Distance"):
            return float(line.split()[1])
    return None


print("in a part")
win.open_path(path)
settle(900)
win.viewport.set_view("iso")
win.viewport.fit_all()
settle(500)
win.viewport.finish_animation()
text = measure_two((0.0, 0.0, 0.0), (100.0, 60.0, 0.0))
check("two corners of a sketch: the diagonal between them",
      near(distance(text), math.hypot(100.0, 60.0), 1e-3)
      and text.count("Sketch point") == 2, text)
win.measure_dialog.close()
settle(200)
# a corner of the floor to the circle, 50 up: the shortest way to it
text = measure_two((0.0, 0.0, 0.0), (70.0, 30.0, 50.0))
check("a sketch point to a circle of another sketch on another plane",
      near(distance(text), math.hypot(math.hypot(50, 30) - 20.0, 50.0),
           1e-4) and "Sketch circle" in text, text)
win.measure_dialog.close()
settle(200)
text = measure_two((50.0, 0.0, 0.0), (50.0, 60.0, 0.0))
check("two lines: the distance between them", near(distance(text), 60.0)
      and text.count("Sketch line") == 2, text)
win.measure_dialog.close()
settle(200)

print("while a sketch is edited")
win.edit_sketch(floor.id)
settle(900)
win.viewport.finish_animation()
text = measure_two((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
check("its own points measure too", near(distance(text), 100.0), text)
win.measure_dialog.close()
win.finish_sketch()
settle(300)

print("in an assembly")
asm = AssemblyDocument()
asm.path = os.path.join(WORK, "frame.icasm")
occurrence = asm.place(path)
occurrence.placement = Placement([200.0, 0.0, 0.0], [0.0, 0.0, 0.0])
asm.save(asm.path)
win.open_path(asm.path)
settle(1200)
win.viewport.set_view("iso")
win.viewport.fit_all()
settle(500)
win.viewport.finish_animation()
text = measure_two((200.0, 0.0, 0.0), (300.0, 60.0, 0.0))
check("a placed part's sketch, measured where the part is placed",
      near(distance(text), math.hypot(100.0, 60.0), 1e-3), text)
win.measure_dialog.close()

print("and the model is still there to pick")
win.open_measure()
settle(200)
eaten = press(5, 5)
check("a click on nothing of a sketch goes on to the view", not eaten)
win.measure_dialog.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
