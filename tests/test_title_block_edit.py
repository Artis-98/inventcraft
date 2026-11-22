"""Editing a title block: fast, and fully constrained with its sizes.

The standard block opened for editing is a sketch whose lines are each
horizontal or vertical, held to each other, grounded at the bottom left
and dimensioned for every column and row, so it is fully constrained.
Its texts are drawn as plain text while it is edited, not built as
letter outlines, which made editing crawl.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core.drawing import standard_title_block                # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=250):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)


print("the block as a sketch")
sketch = standard_title_block().as_sketch()
sketch.solve()
check("every line held", all(sketch.entity_constrained(e)
                             for e in sketch.entities))
check("every text placed", all(sketch.point_constrained(r.point)
                               for r in sketch.texts.values()))
widths = sorted(c.value for c in sketch.constraints.values()
                if c.kind == "distance_x")
heights = sorted(c.value for c in sketch.constraints.values()
                 if c.kind == "distance_y")
check("a dimension for every column", widths == [45, 90, 110, 135, 180],
      widths)
check("and every row", heights == [15, 30, 46], heights)

print("edited on the sheet")
win = MainWindow()
win.resize(1300, 850)
win.show()
settle(500)
win.new_drawing(prompt=False)
settle(300)
ui = win.drawing_ui
ui.edit_title_block()
settle(100)
surface = win.editor.viewport
kinds = [item[0] for item in surface._overlay]
check("its texts drawn as text", kinds.count("label")
      == len(win.editor.sketch.texts), (kinds.count("label"),
                                         len(win.editor.sketch.texts)))
started = time.perf_counter()
for _ in range(10):
    win.editor.render()
    ui.canvas.repaint()
took = time.perf_counter() - started
check("ten redraws in well under a second", took < 0.6, took)
ui.finish_drawing_sketch()
settle(100)

win.drawing.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
