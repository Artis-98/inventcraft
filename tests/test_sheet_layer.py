"""The sheet canvas keeps its views as a picture.

Panning and dragging a balloon must not stroke the views again, and the
picture must look like the sheet drawn the old way. Changing a view
must draw it afresh.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WORK = tempfile.mkdtemp(prefix="datum_layer_")
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_NO_WORKERS"] = "1"

from PySide6 import QtCore, QtGui, QtWidgets                    # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core import hlr                                      # noqa: E402
from datum.core.drawing import BASE, DrawingDocument, View      # noqa: E402
from datum.ui import sheet_canvas, sheetpaint                   # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def projection(n=400):
    lines = []
    for i in range(n):
        x = (i % 20) * 4.0 - 40.0
        y = (i // 20) * 4.0 - 40.0
        lines.append(hlr.Polyline([(x, y), (x + 3.0, y), (x + 3.0, y + 3.0)],
                                  hlr.VISIBLE if i % 3 else hlr.HIDDEN))
    return hlr.Projection(lines=lines, box=(-40.0, -40.0, 40.0, 40.0))


doc = DrawingDocument()
sheet = doc.add_sheet("A3")
view = View(kind=BASE, orientation="front", scale=1.0, x=150, y=150,
            name="Front")
doc.add_view(sheet, view)
view.projection = projection()
note = dwg.Annotation(kind=dwg.NOTE, view=view.id, points=[[0.0, 0.0]],
                      text="NOTE")
sheet.annotations.append(note)

canvas = sheet_canvas.SheetCanvas()
canvas.resize(900, 640)
canvas.set_document(doc)

calls = {"views": 0}
real_paint = sheetpaint.paint


def counting(*args, **kw):
    if kw.get("phase") == "views" and kw.get("only") is None:
        calls["views"] += 1
    return real_paint(*args, **kw)


sheetpaint.paint = counting


def grab():
    return canvas.grab().toImage().convertToFormat(
        QtGui.QImage.Format_ARGB32)


def differ(a, b):
    """Share of pixels that differ noticeably."""
    step, bad, total = 3, 0, 0
    for y in range(0, a.height(), step):
        for x in range(0, a.width(), step):
            total += 1
            p, q = a.pixelColor(x, y), b.pixelColor(x, y)
            if abs(p.red() - q.red()) + abs(p.green() - q.green()) \
                    + abs(p.blue() - q.blue()) > 120:
                bad += 1
    return bad / max(1, total)


print("the picture looks like the sheet")
sheet_canvas.LAYER_CACHE = False
plain = grab()
sheet_canvas.LAYER_CACHE = True
cached = grab()
share = differ(plain, cached)
check("cached and live sheets match", share < 0.002, share)

print("a repaint with nothing changed reuses it")
before = calls["views"]
grab()
check("views not stroked again", calls["views"] == before,
      calls["views"] - before)

print("dragging a note reuses it")
note.offset = [12.0, 7.0]
grab()
check("views not stroked for a note", calls["views"] == before,
      calls["views"] - before)

print("panning reuses it, then sharpens")
canvas._touch()
canvas._pan[0] += 40
grab()
check("pan blits the old picture", calls["views"] == before,
      calls["views"] - before)
canvas._layer_settled()
grab()
check("settles to a fresh picture", calls["views"] == before + 1,
      calls["views"] - before)

print("changing a view draws it again")
before = calls["views"]
view.x += 10
grab()
check("moved view redrawn", calls["views"] == before + 1)
before = calls["views"]
view.projection = projection(200)
grab()
check("new lines redrawn", calls["views"] == before + 1)
before = calls["views"]
canvas.selected_views = [view.id]
grab()
check("selection redrawn", calls["views"] == before + 1)

print("zoom stretches, then sharpens")
before = calls["views"]
canvas.zoom(1.15)
grab()
check("zoom blits while the wheel turns", calls["views"] == before)
canvas._touched.invalidate()
canvas._layer_settled()
grab()
check("zoom settles", calls["views"] == before + 1)

print("polygons are kept on the projection")
p = view.projection
first = sheetpaint.view_polygons(p, hlr.VISIBLE)
check("same list next time",
      sheetpaint.view_polygons(p, hlr.VISIBLE) is first)
p.lines = p.lines[:10]
check("rebuilt when the lines change",
      sheetpaint.view_polygons(p, hlr.VISIBLE) is not first)

sheetpaint.paint = real_paint
print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
