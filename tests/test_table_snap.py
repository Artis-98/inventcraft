"""Parts lists and revision tables drag freely and stick to the frame.

Dragged to within a few pixels of the border's frame or the title
block, a table's edge lands exactly on it, so it sits in a corner or on
the block; anywhere else it goes where it is put, and Alt drags freely.
A revision table can be dragged as a parts list can.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets                           # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.ui import sheet_canvas                               # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
doc = dwg.DrawingDocument()
sheet = doc.add_sheet("A3")
table = dwg.PartsList(x=200.0, y=150.0, corner="bottom-right",
                      rows=[], heading=True)
doc.add_parts_list(sheet, table)
revisions = doc.add_revision_table(sheet) if hasattr(
    doc, "add_revision_table") else None

canvas = sheet_canvas.SheetCanvas()
canvas.resize(1200, 860)
canvas.set_document(doc)
canvas.show()
layout = canvas.layout()
width, height = sheet.extent()
frame = doc.borders[sheet.border].frame(width, height)
block = doc.title_blocks[sheet.title_block]


def drag(thing, by_mm, alt=False):
    box = canvas._table_box(thing)
    start = layout.to_device((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    end = (start[0] + by_mm[0] * layout.scale,
           start[1] - by_mm[1] * layout.scale)
    QtWidgets.QApplication.keyboardModifiers = staticmethod(
        lambda: QtCore.Qt.AltModifier if alt else QtCore.Qt.NoModifier)
    QTest.mousePress(canvas, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                     QtCore.QPoint(int(start[0]), int(start[1])))
    QTest.mouseMove(canvas, QtCore.QPoint(int(end[0]), int(end[1])))
    QTest.mouseRelease(canvas, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                       QtCore.QPoint(int(end[0]), int(end[1])))
    return canvas._table_box(thing)


print("a parts list near the title block's corner")
box = canvas._table_box(table)
target = (frame[2] - box[2] + 1.2, frame[1] + block.height - box[1] - 1.0)
box = drag(table, target)
check("its right edge on the frame",
      abs(box[2] - frame[2]) < 1e-6, (box[2], frame[2]))
check("its bottom on the title block",
      abs(box[1] - (frame[1] + block.height)) < 1e-6,
      (box[1], frame[1] + block.height))

print("away from everything")
box = drag(table, (-120.0, 60.0))
check("goes where it is put", abs(box[2] - (frame[2] - 120.0)) < 1.0, box)

print("Alt drags freely")
box = canvas._table_box(table)
box = drag(table, (frame[2] - box[2] + 1.2, 0.0), alt=True)
check("not pulled onto the frame", abs(box[2] - frame[2]) > 0.5, box)

if revisions is not None:
    print("a revision table")
    box = canvas._table_box(revisions)
    box = drag(revisions, (-50.0, -40.0))
    check("can be dragged", abs(revisions.x - (frame[2] - 50.0)) < 15.0,
          revisions.x)
    box = canvas._table_box(revisions)
    box = drag(revisions, (frame[2] - box[2] + 1.0,
                           frame[3] - box[3] - 1.0))
    check("and sticks in the top right corner",
          abs(box[2] - frame[2]) < 1e-6 and abs(box[3] - frame[3]) < 1e-6,
          box)

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
