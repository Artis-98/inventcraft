"""A label dragged near another's line is pulled level with it.

Dragging a balloon to within a few pixels of another's height puts it
exactly level, with a guide drawn while the mouse is down; held Alt, it
goes exactly where the mouse puts it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets                           # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core import hlr                                      # noqa: E402
from datum.core.drawing import BASE, DrawingDocument, View      # noqa: E402
from datum.ui import sheet_canvas                               # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
doc = DrawingDocument()
sheet = doc.add_sheet("A3")
view = View(kind=BASE, orientation="front", scale=1.0, x=150, y=150)
doc.add_view(sheet, view)
view.projection = hlr.Projection(
    lines=[hlr.Polyline([(-40, -20), (40, -20), (40, 20), (-40, 20),
                         (-40, -20)])], box=(-40, -20, 40, 20))
first = doc.add_annotation(sheet, dwg.Annotation(
    kind=dwg.BALLOON, view=view.id, points=[[40.0, 10.0]],
    offset=[30.0, 20.0], text="1"))
second = doc.add_annotation(sheet, dwg.Annotation(
    kind=dwg.BALLOON, view=view.id, points=[[-40.0, -10.0]],
    offset=[-30.0, -25.0], text="2"))

canvas = sheet_canvas.SheetCanvas()
canvas.resize(1000, 700)
canvas.set_document(doc)
canvas.show()
layout = canvas.layout()


def at(note):
    x, y = dwg.label_at(note)
    return layout.to_device(view.x + x, view.y + y)


def drag(note, to, alt=False):
    start = at(note)
    mods = QtCore.Qt.AltModifier if alt else QtCore.Qt.NoModifier
    QTest.mousePress(canvas, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                     QtCore.QPoint(int(start[0]), int(start[1])))
    QTest.mouseMove(canvas, QtCore.QPoint(int(to[0]), int(to[1])))
    if alt:
        # the modifier is read from the application while dragging
        QtWidgets.QApplication.keyboardModifiers = staticmethod(
            lambda: QtCore.Qt.AltModifier)
    else:
        QtWidgets.QApplication.keyboardModifiers = staticmethod(
            lambda: QtCore.Qt.NoModifier)
    QTest.mouseMove(canvas, QtCore.QPoint(int(to[0]) + 1, int(to[1])))
    guides = list(getattr(canvas, "_guides", []))
    QTest.mouseRelease(canvas, QtCore.Qt.LeftButton, mods,
                       QtCore.QPoint(int(to[0]) + 1, int(to[1])))
    return guides


print("pulled level")
target = at(first)
guides = drag(second, (target[0] - 200, target[1] + 3))
check("now exactly level with the other",
      abs(dwg.label_at(second)[1] - dwg.label_at(first)[1]) < 1e-9,
      (dwg.label_at(second), dwg.label_at(first)))
check("with a guide shown while dragging", len(guides) == 1, guides)
check("and no guide after", not getattr(canvas, "_guides", []))

print("Alt drags freely")
target = at(first)
drag(second, (target[0] - 200, target[1] + 12), alt=True)
drag(second, (target[0] - 200, target[1] + 3), alt=True)
check("left where the mouse put it",
      abs(dwg.label_at(second)[1] - dwg.label_at(first)[1]) > 0.1,
      (dwg.label_at(second), dwg.label_at(first)))

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
