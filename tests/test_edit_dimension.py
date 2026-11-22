"""Edit Dimension: text, precision and tolerance (Suggest button #366).

A 25 mm linear dimension written with decimals, each tolerance method,
text before and after, and a text height of its own; all kept in the
file. The dialog shows the result as it is set and writes it back.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets                                   # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core.drawing import BASE, DrawingDocument, View      # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def note(**kw):
    return dwg.Annotation(kind=dwg.LINEAR, points=[[0, 0], [25, 0]],
                          axis="x", **kw)


print("captions")
check("plain", note().caption() == "25")
check("three decimals", note(precision=3).caption() == "25.000")
check("symmetric", note(tolerance="symmetric", upper=0.1).caption()
      == "25 ±0.10", note(tolerance="symmetric", upper=0.1).caption())
check("deviation", note(tolerance="deviation", upper=0.1, lower=0.05,
                        precision=2).caption() == "25.00 +0.10/-0.05")
check("limits", note(tolerance="limits", upper=0.1, lower=0.05,
                     precision=2).caption() == "25.10/24.95")
check("a fit", note(tolerance="fit", fit="H7").caption() == "25 H7")
check("basic", note(tolerance="basic").caption() == "[25]")
check("reference", note(tolerance="reference").caption() == "(25)")
check("text round it", note(prefix="2x ", suffix=" TYP").caption()
      == "2x 25 TYP")
diameter = dwg.Annotation(kind=dwg.DIAMETER, points=[[0, 0], [10, 0]],
                          tolerance="fit", fit="h6")
check("a diameter's fit", diameter.caption() == "⌀20 h6",
      diameter.caption())

print("kept in the file")
held = note(precision=1, tolerance="deviation", upper=0.2, lower=0.1,
            size=5.0)
back = dwg.Annotation.from_dict(held.to_dict())
check("all of it comes back", (back.precision, back.tolerance, back.upper,
                               back.lower, back.size)
      == (1, "deviation", 0.2, 0.1, 5.0))
check("a plain one writes none of it", "tolerance" not in note().to_dict()
      and "precision" not in note().to_dict())

print("the dialog")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from datum.ui.drawing_ui import DimensionDialog                 # noqa: E402
doc = DrawingDocument()
sheet = doc.add_sheet("A3")
view = View(kind=BASE, orientation="front", scale=1.0, x=100, y=100)
doc.add_view(sheet, view)
dim = note(view=view.id)
doc.add_annotation(sheet, dim)
dialog = DimensionDialog(None, doc, sheet, dim)
dialog.method.setCurrentIndex(dialog.method.findData("symmetric"))
dialog.upper.setValue(0.05)
dialog.precision.setValue(2)
check("shows the result as it is set",
      dialog.preview.text() == "25.00 ±0.05", dialog.preview.text())
check("and leaves the dimension alone until OK", dim.tolerance == "")
dialog.apply()
check("then writes it", dim.caption() == "25.00 ±0.05", dim.caption())

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
