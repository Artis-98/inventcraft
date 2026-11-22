"""Symbols can be turned, mirrored and sized (#368).

Surface texture, feature control frames, datums and welds each keep a
turn, a mirror and a size; they survive the file, the dialog shows and
changes them, and the symbol is drawn that way. A sheet of every symbol
in every stance is saved for looking at.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtWidgets                            # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402
from datum.core import hlr                                      # noqa: E402
from datum.core.drawing import BASE, DrawingDocument, View      # noqa: E402
from datum.ui import sheetpaint                                 # noqa: E402
from datum.ui.drawing_tools import SymbolDialog                 # noqa: E402

FAILS = []
OUT = tempfile.mkdtemp(prefix="datum_stance_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

print("kept in the file")
note = dwg.Annotation(kind=dwg.SURFACE, view=1, points=[[0.0, 0.0]],
                      offset=[0.0, 0.0], text="Ra 1.6",
                      shape=dwg.SURFACE_REMOVAL, turn=90.0, flip=True,
                      scale=1.5)
back = dwg.Annotation.from_dict(note.to_dict())
check("turn, mirror and size come back",
      (back.turn, back.flip, back.scale) == (90.0, True, 1.5))
plain = dwg.Annotation(kind=dwg.SURFACE).to_dict()
check("an ordinary symbol writes none of them",
      not any(k in plain for k in ("turn", "flip", "scale")))
check("an old file reads as upright, full size",
      (dwg.Annotation.from_dict({"kind": "surface"}).turn,
       dwg.Annotation.from_dict({"kind": "surface"}).scale) == (0.0, 1.0))

print("the dialog shows them and changes them")
for kind, text in ((dwg.SURFACE, "Ra 1.6"),
                   (dwg.FCF, "position|Ø0.2|A|B"),
                   (dwg.WELD, "fillet|a5|50|all_around"),
                   (dwg.DATUM_ID, "C")):
    held = dwg.Annotation(kind=kind, text=text, turn=45.0, flip=True,
                          scale=2.0,
                          shape=dwg.SURFACE_REMOVAL if kind == dwg.SURFACE
                          else "")
    dialog = SymbolDialog(None, kind, "A", held)
    got = dialog.values()
    check("%s: what it says comes back" % kind, got["text"] == text,
          (got["text"], text))
    check("%s: and its size" % kind, abs(got["scale"] - 2.0) < 1e-9,
          got["scale"])
    if kind in (dwg.SURFACE, dwg.FCF):
        check("%s: and its turn and mirror" % kind,
              got["turn"] == 45.0 and got["flip"])

print("drawn as it stands")
doc = DrawingDocument()
sheet = doc.add_sheet("A3")
view = View(kind=BASE, orientation="front", scale=1.0, x=0, y=0)
doc.add_view(sheet, view)
view.projection = hlr.Projection(
    lines=[hlr.Polyline([(-1, 0), (1, 0)])], box=(-1, -1, 1, 1))

STANCES = [(0.0, False, 1.0), (90.0, False, 1.0), (0.0, True, 1.0),
           (180.0, False, 1.0), (0.0, False, 2.0)]
KINDS = [(dwg.SURFACE, "Ra 3.2", dwg.SURFACE_REMOVAL),
         (dwg.FCF, "position|Ø0.1|A|B", ""),
         (dwg.DATUM_ID, "A", ""),
         (dwg.WELD, "fillet|a4||", "")]
for row, (kind, text, shape) in enumerate(KINDS):
    for col, (turn, flip, scale) in enumerate(STANCES):
        doc.add_annotation(sheet, dwg.Annotation(
            kind=kind, view=view.id, text=text, shape=shape,
            points=[[60.0 + col * 70.0, 240.0 - row * 60.0]],
            offset=[0.0, 0.0] if kind != dwg.WELD else [8.0, 8.0],
            turn=turn, flip=flip, scale=scale))

image = QtGui.QImage(1600, 1130, QtGui.QImage.Format_ARGB32)
w, h = sheet.extent()
layout = sheetpaint.fit(w, h, image.width(), image.height())


def picture():
    image.fill(0xffffffff)
    painter = QtGui.QPainter(image)
    sheetpaint.paint(painter, doc, sheet, layout, on_screen=True)
    painter.end()
    return image.copy()


def ink(img, x0, y0, x1, y1):
    """The dark pixels in a box of sheet millimetres, as a set."""
    a = layout.to_device(x0, y1)
    b = layout.to_device(x1, y0)
    out = set()
    for y in range(int(a[1]), int(b[1])):
        for x in range(int(a[0]), int(b[0])):
            if QtGui.QColor(img.pixel(x, y)).lightness() < 128:
                out.add((x - int(a[0]), y - int(a[1])))
    return out


whole = picture()
whole.save(os.path.join(OUT, "stances.png"))
for row, (kind, _t, _s) in enumerate(KINDS):
    y = 240.0 - row * 60.0
    cells = [ink(whole, 60.0 + c * 70.0 - 30, y - 28, 60.0 + c * 70.0 + 30,
                 y + 28) for c in range(len(STANCES))]
    check("%s: drawn at all" % kind, len(cells[0]) > 20, len(cells[0]))
    def reach(cell):
        xs = [p[0] for p in cell] or [0]
        ys = [p[1] for p in cell] or [0]
        return max(ys) - min(ys)
    big = ink(whole, 60.0 + 4 * 70.0 - 34, y - 29, 60.0 + 4 * 70.0 + 34,
              y + 29)
    check("%s: twice the size reaches further" % kind,
          reach(big) > reach(cells[0]) * 1.4, (reach(big),
                                               reach(cells[0])))
    if kind in (dwg.SURFACE, dwg.FCF):
        check("%s: turned is drawn differently" % kind,
              cells[1] != cells[0])
    if kind != dwg.DATUM_ID:
        check("%s: mirrored is drawn differently" % kind,
              cells[2] != cells[0])
print("  picture:", os.path.join(OUT, "stances.png"))
print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
