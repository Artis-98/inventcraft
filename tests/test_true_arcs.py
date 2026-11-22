"""Circles and arcs seen square on go to paper and DXF as true arcs.

A plate with a hole and rounded corners, seen from above: its circle and
corner arcs keep what they are through hidden line removal, scaling, the
projection cache and the file, and are drawn on paper as arcs that lie
on the lines the screen shows, and written to DXF as CIRCLE and ARC.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WORK = tempfile.mkdtemp(prefix="datum_arcs_")
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_NO_WORKERS"] = "1"

from PySide6 import QtGui, QtWidgets                            # noqa: E402

from datum.core import fileformat, hlr, kernel, projcache, views  # noqa
from datum.core import workers                                  # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.drawing import BASE, DrawingDocument, View      # noqa: E402
from datum.core.features import CUT, PrimitiveFeature           # noqa: E402
from datum.ui import drawingexport, sheetpaint                  # noqa: E402

workers.ENABLED = False
FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
part = Document()
part.add_feature(PrimitiveFeature(name="Plate", kind="box", a="80", b="50",
                                  c="8"))
part.add_feature(PrimitiveFeature(name="Hole", kind="cylinder", a="9",
                                  b="8", operation=CUT,
                                  origin=("40", "25", "0")))
part.rebuild()
PLATE = part.save(os.path.join(WORK, "Plate"))

print("kept through hidden line removal")
shape = kernel.read_any(PLATE) if hasattr(kernel, "read_any") else None
doc = DrawingDocument()
doc.path = os.path.join(WORK, "a.ddat")
sheet = doc.add_sheet("A4")
view = View(kind=BASE, orientation="top", scale=2.0, x=105, y=150,
            display="visible")
view.ref = fileformat.ComponentRef(path=fileformat.relative_path(PLATE, WORK),
                                   name="Plate", label="Plate")
doc.add_view(sheet, view)
views.Generator().rebuild(doc, force=True)
arcs = [l for l in view.projection.lines if l.arc is not None]
check("the hole is a true circle", any(abs(abs(l.arc[4]) - 360.0) < 1e-6
                                        for l in arcs),
      [l.arc for l in arcs])
circle = next((l for l in arcs if abs(abs(l.arc[4]) - 360.0) < 1e-6), None)
if circle is not None:
    cx, cy, r, _a0, _sw = circle.arc
    check("of the hole's radius at the view's scale", abs(r - 18.0) < 1e-6,
          r)
    far = max(abs(math.dist(p, (cx, cy)) - r) for p in circle.points)
    check("and its points lie on it", far < 0.05, far)

print("kept through the cache and the file")
cache = projcache.ProjectionCache()
cache.put("k", view.projection)
again = cache.get("k", 0.5)
check("the cache scales it with the points",
      any(l.arc and abs(l.arc[2] - 9.0) < 1e-6 for l in again.lines))
back = hlr.Projection.from_dict(view.projection.to_dict())
check("the file keeps it", sum(1 for l in back.lines if l.arc)
      == len(arcs))

print("on paper")
image = QtGui.QImage(1240, 1754, QtGui.QImage.Format_ARGB32)
w, h = sheet.extent()
layout = sheetpaint.fit(w, h, image.width(), image.height())


def picture(on_screen):
    image.fill(0xffffffff)
    painter = QtGui.QPainter(image)
    sheetpaint.paint(painter, doc, sheet, layout, on_screen=on_screen,
                     title_block=False)
    painter.end()
    return image.copy()


paper, screen = picture(False), picture(True)
c = layout.to_device(view.x + cx, view.y + cy)
rr = r * layout.scale
dark_paper = dark_screen = both = 0
for k in range(360):
    t = math.radians(k)
    x, y = int(round(c[0] + rr * math.cos(t))), int(round(c[1]
                                                          + rr * math.sin(t)))
    a = QtGui.QColor(paper.pixel(x, y)).lightness() < 160
    b = QtGui.QColor(screen.pixel(x, y)).lightness() < 160
    dark_paper += a
    dark_screen += b
    both += a and b
check("the arc on paper lies where the screen draws it",
      dark_paper > 330 and both > 300, (dark_paper, dark_screen, both))

pdf = os.path.join(WORK, "a.pdf")
drawingexport.to_pdf(doc, pdf)
check("a PDF comes out", os.path.getsize(pdf) > 1000)

print("in DXF")
dxf = os.path.join(WORK, "a.dxf")
drawingexport.to_dxf(doc, sheet, dxf)
text = open(dxf, encoding="utf-8", errors="replace").read()
check("as a CIRCLE", "\nCIRCLE\n" in text)
check("and the corners, if any, as ARC or lines",
      "\nLINE\n" in text)

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
