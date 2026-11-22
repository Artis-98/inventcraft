"""Time the steps of a drawing on a heavy model.

    .venv/Scripts/python.exe tools/bench_drawing.py [model] [--serial]

Sheet: front base with hidden lines, top, side, iso and a detail.
Prints the time of each step, so a change can be compared to before.
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WORK = tempfile.mkdtemp(prefix="datum_bench_")
os.environ.setdefault("DATUM_CONFIG_DIR", os.path.join(WORK, "cfg"))
os.environ.pop("DATUM_NO_WORKERS", None)

from datum.core import fileformat, views, workers               # noqa: E402
from datum.core.drawing import (BASE, DETAIL, PROJECTED,        # noqa: E402
                                WITH_HIDDEN, DrawingDocument, View)

args = [a for a in sys.argv[1:] if not a.startswith("--")]
MODEL = os.path.abspath(args[0] if args else os.path.join(
    ROOT, "examples", "walking-excavator", "Walking Excavator.icasm"))
SERIAL = "--serial" in sys.argv


def ref(path):
    return fileformat.ComponentRef(
        path=fileformat.relative_path(path, WORK),
        name=os.path.basename(path),
        label=os.path.splitext(os.path.basename(path))[0])


def sheet():
    doc = DrawingDocument()
    doc.path = os.path.join(WORK, "bench.icdraw")
    s = doc.add_sheet("A2")
    base = View(kind=BASE, orientation="front", scale=0.05, x=150, y=250,
                display=WITH_HIDDEN, name="Front")
    base.ref = ref(MODEL)
    doc.add_view(s, base)
    doc.add_view(s, View(kind=PROJECTED, parent=base.id, name="Top",
                         x=150, y=100))
    doc.add_view(s, View(kind=PROJECTED, parent=base.id, name="Side",
                         x=350, y=250))
    doc.add_view(s, View(kind=PROJECTED, parent=base.id, name="Iso",
                         x=350, y=100, display="visible"))
    doc.add_view(s, View(kind=DETAIL, parent=base.id, letter="A", scale=0.2,
                         centre=[0.0, 0.0], radius=12.0, x=500, y=250,
                         name="Detail"))
    return doc, s, base


def timed(name, fn):
    t = time.perf_counter()
    out = fn()
    print("  %-38s %7.2f s" % (name, time.perf_counter() - t))
    return out


print(os.path.basename(MODEL), "serial" if SERIAL else "workers")
workers.ENABLED = not SERIAL
gen = views.Generator()
doc, s, base = sheet()
if not SERIAL:
    timed("start workers", lambda: workers.pool().start())
timed("first rebuild (cold model)", lambda: gen.rebuild(doc, force=True))
timed("rebuild again, forced", lambda: gen.rebuild(doc, force=True))
timed("rebuild, nothing changed", lambda: gen.rebuild(doc))


def rescale():
    base.scale = 0.04
    for v in s.views:
        v.projection = None
    return gen.rebuild(doc)


timed("scale changed (all views dropped)", rescale)
for v in s.views:
    n = sum(len(line.points) for line in v.projection.lines) \
        if v.projection else 0
    print("    %-8s %6d points  %s" % (v.name, n, v.error))

# -- painting the sheet, as the canvas does on every repaint
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets                            # noqa: E402
from datum.ui import sheetpaint                                 # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
image = QtGui.QImage(1800, 1100, QtGui.QImage.Format_ARGB32_Premultiplied)
w, h = s.extent()
layout = sheetpaint.fit(w, h, image.width(), image.height())


def paint_once():
    painter = QtGui.QPainter(image)
    sheetpaint.paint(painter, doc, s, layout, on_screen=True)
    painter.end()


timed("paint sheet (first)", paint_once)
timed("paint sheet (again)", paint_once)
image.save(os.path.join(WORK, "bench.png"))
print("  picture:", os.path.join(WORK, "bench.png"))

from datum.ui import drawingexport                              # noqa: E402
pdf = os.path.join(WORK, "bench.pdf")
timed("export PDF", lambda: drawingexport.to_pdf(doc, pdf))
print("  PDF size %.1f MB" % (os.path.getsize(pdf) / 1e6))
