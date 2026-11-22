"""A parts list fits its columns to their words and wraps when long.

New lists size each column to what is in it; lists saved before keep
the widths they had. Past a number of rows the list carries on in a
section beside the first, each with its own heading, as Inventor's
Table Wrapping does.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtWidgets                            # noqa: E402

from datum.core import bom                                      # noqa: E402
from datum.core.drawing import DrawingDocument, PartsList       # noqa: E402
from datum.ui import sheetpaint                                 # noqa: E402

FAILS = []
OUT = tempfile.mkdtemp(prefix="datum_plist_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

rows = [bom.Row(item=i + 1, quantity=1 + i % 3,
                part_number="WE-%03d Track Frame Bracket" % i
                if i % 5 == 0 else "P-%d" % i, material="S355")
        for i in range(23)]

print("columns fit their words")
table = PartsList(columns=["item", "qty", "part_number", "material"],
                  rows=rows)
narrow = PartsList(columns=["item", "qty", "part_number", "material"],
                   rows=rows[1:2])
check("a long name makes a wide column",
      table.column_width("part_number") > 60.0,
      table.column_width("part_number"))
check("short names a narrow one",
      narrow.column_width("part_number") < 40.0,
      narrow.column_width("part_number"))
check("a width given by hand wins",
      PartsList(rows=rows, widths={"part_number": 50.0})
      .column_width("part_number") == 50.0)
old = PartsList.from_dict({"columns": ["item", "part_number"], "rows": []})
check("a list from an older file keeps its old widths",
      not old.auto_width and old.column_width("part_number")
      == bom.DEFAULT_WIDTHS["part_number"])
again = PartsList.from_dict(table.to_dict())
check("a new list stays fitted after saving", again.auto_width)

print("a long list wraps")
table.wrap_rows = 10
check("into three sections", [len(s) for s in table.sections()]
      == [10, 10, 3], [len(s) for s in table.sections()])
check("three sections wide", abs(table.width()
                                 - 3 * table.section_width()) < 1e-9)
check("as tall as the tallest", abs(table.height()
                                    - 11 * table.row_height) < 1e-9)
check("kept in the file", PartsList.from_dict(table.to_dict()).wrap_rows
      == 10)
table.wrap_rows = 0
check("unwrapped, one section", len(table.sections()) == 1)

print("drawn")
doc = DrawingDocument()
sheet = doc.add_sheet("A3")
table.wrap_rows = 10
table.x, table.y = 410.0, 20.0
doc.add_parts_list(sheet, table)
image = QtGui.QImage(1600, 1130, QtGui.QImage.Format_ARGB32)
image.fill(0xffffffff)
w, h = sheet.extent()
layout = sheetpaint.fit(w, h, image.width(), image.height())
painter = QtGui.QPainter(image)
sheetpaint.paint(painter, doc, sheet, layout, on_screen=True,
                 title_block=False)
painter.end()
image.save(os.path.join(OUT, "parts_list.png"))
x0, y0, x1, y1 = table.box()
row = int(round(layout.to_device(0, y1)[1]))
xs = range(int(layout.to_device(x0, 0)[0]) + 2,
           int(layout.to_device(x1, 0)[0]) - 2)
dark = sum(1 for x in xs if min(
    QtGui.QColor(image.pixel(x, row + k)).lightness() for k in (-1, 0, 1))
    < 128)
check("the headings sit level, one top line across all three",
      dark > 0.95 * len(xs), (dark, len(xs)))
print("  picture:", os.path.join(OUT, "parts_list.png"))
print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
