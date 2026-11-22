"""A detail view goes where it is asked to, and can be moved after.

Reported from the Suggest button (#367): Detail put its circle in the
middle of the view, and it could not be changed. Now the middle, the
reach and where the detail goes are all clicked, as in Inventor, and a
selected detail's circle has a grip at its middle and one on its edge.
"""
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402

from datum.core import hlr                                         # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.drawing import DETAIL                              # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_detail_")
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


part = Document()
part.add_feature(PrimitiveFeature(kind="box", a="60", b="30", c="40"))
part.rebuild()
BLOCK = part.save(os.path.join(WORK, "Block"))

win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Block.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
d, u = hlr.ORIENTATIONS["front"]
base = ui.create_views({"path": BLOCK, "scale": 1.0, "name": "Front"},
                       d, u, 120.0, 150.0, [])
settle(200)
sheet = win.drawing.active()
canvas = ui.canvas

print("the Detail tool asks for each thing in turn")
canvas.select([base.id])
ui.add_detail()
tool = canvas.placer
check("a tool is placing", tool is not None
      and type(tool).__name__ == "DetailTool")
check("with the selected view already picked", tool.view is base)
corner = (base.x + 25.0, base.y + 15.0)     # near the top right corner
tool.press(corner, None)
check("the middle is where it was clicked",
      tool.centre is not None and abs(tool.centre[0] - 25.0) < 1e-6
      and abs(tool.centre[1] - 15.0) < 1e-6, tool.centre)
tool.move((corner[0] + 8.0, corner[1]), None, False)
tool.press((corner[0] + 8.0, corner[1]), None)
check("the reach is how far the second click was", tool.radius is not None
      and abs(tool.radius - 8.0) < 1e-6, tool.radius)
tool.escape()
check("Esc takes the reach back", tool.radius is None
      and tool.centre is not None)
tool.press((corner[0] + 6.0, corner[1]), None)
tool.press((260.0, 120.0), None)
settle(200)
details = [v for v in sheet.views if v.kind == DETAIL]
check("one detail made", len(details) == 1, len(details))
detail = details[0]
check("where it was put", abs(detail.x - 260.0) < 1e-6
      and abs(detail.y - 120.0) < 1e-6, (detail.x, detail.y))
check("of the corner that was clicked",
      detail.centre == [25.0, 15.0] and abs(detail.radius - 6.0) < 1e-6,
      (detail.centre, detail.radius))
check("drawn twice the size", detail.projection is not None
      and detail.projection.ok)
check("of only what was in the circle",
      detail.projection.width <= 2 * 2 * 6.0 + 1e-6,
      detail.projection.width)
ui.end_placement()
settle(100)

print("its circle moves with a grip")
canvas.select([detail.id])
settle(100)
grips = canvas._fence_grips()
check("a grip in the middle and one on the edge", len(grips) == 2,
      len(grips))
middle = [g for g in grips if g[1] == "centre"][0][2]
layout = canvas.layout()
target = layout.to_device(base.x - 27.0, base.y - 17.0)
QTest.mousePress(canvas, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                 middle.toPoint())
QTest.mouseMove(canvas, QtCore.QPoint(int(target[0]), int(target[1])))
QTest.mouseRelease(canvas, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                   QtCore.QPoint(int(target[0]), int(target[1])))
settle(200)
detail = [v for v in win.drawing.active().views if v.kind == DETAIL][0]
check("the middle followed the mouse",
      math.hypot(detail.centre[0] + 27.0, detail.centre[1] + 17.0)
      < 2.0 / layout.scale + 0.5, detail.centre)
check("and the detail was drawn again", detail.projection is not None
      and detail.projection.ok)
win.drawing.undo()
settle(100)
back = [v for v in win.drawing.active().views if v.kind == DETAIL][0]
check("one undo puts it back", back.centre == [25.0, 15.0], back.centre)

win.drawing.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
