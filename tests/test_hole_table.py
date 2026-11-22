"""Inventor's Hole Table: every hole seen end on, tagged, measured.

A plate with two 8 mm holes and one 12 mm blind hole, seen from above:
picking its corner makes a table of three rows, A1 and A2 for the 8 mm
pair and B1 for the other, each with where it is from that corner and
its note. It survives the file, follows the model, and the balloons'
numbers are not taken from it.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import drawing as dwg                              # noqa: E402
from datum.core import hlr                                         # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import CUT, PrimitiveFeature              # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_holetable_")
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


def plate(path, third_x="70"):
    part = Document()
    part.add_feature(PrimitiveFeature(name="Plate", kind="box", a="100",
                                      b="60", c="10"))
    for name, x, y, r, depth in (("H1", "20", "15", "4", "10"),
                                 ("H2", "20", "45", "4", "10"),
                                 ("H3", third_x, "30", "6", "6")):
        part.add_feature(PrimitiveFeature(
            name=name, kind="cylinder", a=r, b=depth, operation=CUT,
            origin=(x, y, str(10 - float(depth)))))
    part.rebuild()
    return part.save(path)


PLATE = plate(os.path.join(WORK, "Plate"))
win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Holes.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
sheet = win.drawing.active()
d, u = hlr.ORIENTATIONS["top"]
view = ui.create_views({"path": PLATE, "scale": 1.0, "name": "Top",
                        "centrelines": False}, d, u, 120.0, 160.0, [])
settle(200)
box = view.projection.box
corner = (box[0], box[1])           # the plate's bottom left, on paper

print("made from a picked corner")
table = ui.add_hole_table(sheet, view, corner)
settle(100)
rows = table.rows
tags = [r.extra.get("HOLE") for r in rows]
check("three holes", len(rows) == 3, tags)
check("two of one size, one of another",
      sorted(tags) == ["A1", "A2", "B1"], tags)
by_tag = {r.extra["HOLE"]: r for r in rows}
dims = {t: (float(r.extra["XDIM"]), float(r.extra["YDIM"]))
        for t, r in by_tag.items()}
check("measured from the corner, in model millimetres",
      sorted(dims.values()) == [(20.0, 15.0), (20.0, 45.0), (70.0, 30.0)],
      dims)
check("A1 is above A2: tagged top to bottom",
      dims["A1"][1] > dims["A2"][1], dims)
check("the 8 mm ones say THRU", "Ø8 THRU"
      in by_tag["A1"].extra["DESCRIPTION"], by_tag["A1"].extra)
check("the 12 mm one gives its depth", "DEPTH 6"
      in by_tag["B1"].extra["DESCRIPTION"], by_tag["B1"].extra)
check("its columns are Inventor's",
      [dwg.PartsList.from_dict(table.to_dict()).kind] == ["holes"]
      and table.columns == dwg.HOLE_COLUMNS)

settle(200)
ui.canvas.fit()
settle(200)
ui.canvas.grab().save(os.path.join(WORK, "hole_table.png"))
print("  picture:", os.path.join(WORK, "hole_table.png"))

print("kept in the file")
win.save_document()
again = dwg.DrawingDocument.load(win.drawing.path)
kept = again.active().parts_lists[0]
check("a hole table again, with its datum and rows",
      kept.kind == "holes" and kept.datum == [corner[0], corner[1]]
      and len(kept.rows) == 3)

print("balloons do not number from it")
note = dwg.Annotation(kind=dwg.BALLOON, view=view.id, points=[[0, 0]],
                      component=PLATE, item=7)
check("a balloon keeps its own number", win.drawing.balloon_number(
    sheet, note) == 7)

print("follows the model")
time.sleep(0.05)
plate(PLATE, third_x="80")
ui.update_views()
ui.refine_now(60)
settle(100)
table = win.drawing.active().parts_lists[0]
moved = [r for r in table.rows if r.extra.get("HOLE") == "B1"]
check("B1 moved with the hole", moved and float(moved[0].extra["XDIM"])
      == 80.0, [r.extra for r in table.rows])

win.drawing.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
