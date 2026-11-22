"""Text in a box, Inventor's way, and properties to so many decimals.

The Text tool takes two corners, then Format Text; the text sits in the
box as its alignment says, across and up and down. A property can be
asked for to so many decimals, <Model.Mass:1>.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtWidgets                            # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core.drawing import BASE, DrawingDocument, View      # noqa: E402
from datum.ui import sheetpaint                                 # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("properties to so many decimals")
values = {"Model.Mass": "412.318 g", "Model.Name": "Plate"}
check("one decimal", dwg.fill_properties("<Model.Mass:1>", values)
      == "412.3 g", dwg.fill_properties("<Model.Mass:1>", values))
check("none", dwg.fill_properties("<Model.Mass:0>", values) == "412 g")
check("as it is", dwg.fill_properties("<Model.Mass>", values)
      == "412.318 g")
check("words are left alone", dwg.fill_properties("<Model.Name:2>", values)
      == "Plate")

print("in its box")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
doc = DrawingDocument()
sheet = doc.add_sheet("A3")
view = View(kind=BASE, orientation="front", scale=1.0, x=100, y=100)
doc.add_view(sheet, view)
image = QtGui.QImage(1600, 1130, QtGui.QImage.Format_ARGB32)
w, h = sheet.extent()
layout = sheetpaint.fit(w, h, image.width(), image.height())


def ink_rows(note):
    sheet.annotations = []
    doc.add_annotation(sheet, note)
    image.fill(0xffffffff)
    painter = QtGui.QPainter(image)
    sheetpaint.paint(painter, doc, sheet, layout, on_screen=False,
                     title_block=False, with_paper=False)
    painter.end()
    top = layout.to_device(0, 200)[1]
    bottom = layout.to_device(0, 140)[1]
    left = layout.to_device(150, 0)[0]
    right = layout.to_device(250, 0)[0]
    rows, cols = [], []
    for y in range(int(top), int(bottom)):
        for x in range(int(left), int(right), 2):
            if QtGui.QColor(image.pixel(x, y)).lightness() < 128:
                rows.append(y)
                cols.append(x)
    return rows, cols


def boxed(align, valign):
    # a 100 x 60 box with its top left at (150, 200) on the sheet
    return dwg.Annotation(kind=dwg.NOTE, view=view.id,
                          points=[[150 - view.x, 200 - view.y]],
                          offset=[0.0, 0.0], text="HELLO", size=5.0,
                          box=[100.0, 60.0], align=align, valign=valign)


top_rows, _ = ink_rows(boxed("left", "top"))
bottom_rows, _ = ink_rows(boxed("left", "bottom"))
middle_rows, _ = ink_rows(boxed("left", "middle"))
check("top sits at the top", top_rows and min(top_rows)
      < layout.to_device(0, 190)[1])
check("bottom sits at the bottom", bottom_rows and max(bottom_rows)
      > layout.to_device(0, 150)[1])
check("middle between", top_rows and bottom_rows and middle_rows
      and min(top_rows) < min(middle_rows) < min(bottom_rows))
_l, left_cols = ink_rows(boxed("left", "top"))
_r, right_cols = ink_rows(boxed("right", "top"))
check("right is right of left", left_cols and right_cols
      and min(right_cols) > min(left_cols) + 100)
back = dwg.Annotation.from_dict(boxed("centre", "middle").to_dict())
check("kept in the file", back.box == [100.0, 60.0]
      and back.valign == "middle")

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
