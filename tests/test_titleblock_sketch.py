"""The title block edited as a sketch, Inventor's way: drawn anywhere,
lines and text brought in from a DXF, and on Finish measured so its
bottom right corner is the one put on the border's."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtWidgets                                   # noqa: E402

from datum.core import drawing as dwg, dxf, dxfread            # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("a DXF from AutoCAD, read")
out = dxf.DxfDocument()
for a, b in (((500, 100), (680, 100)), ((680, 100), (680, 140)),
             ((680, 140), (500, 140)), ((500, 140), (500, 100)),
             ((500, 120), (680, 120))):
    out.line(a, b)
out.text((505, 125), 5.0, "IITEG")
path = os.path.join(tempfile.mkdtemp(), "block.dxf")
out.save(path)
found = dxfread.read(path)
check("its five lines and its text", len(found["lines"]) == 5
      and [t[3] for t in found["texts"]] == ["IITEG"], found)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from datum.ui.titleblock_editor import TitleBlockEditor          # noqa: E402

doc = dwg.DrawingDocument()
one = doc.add_sheet("A3")
two = doc.add_sheet("A3")
editor = TitleBlockEditor(None, None, doc, one.title_block)
for item in editor.lines() + editor.texts():
    editor.canvas.scene().removeItem(item)
editor.take(found)
editor.apply()
block = doc.title_blocks[one.title_block]
check("drawn far off at 500, 100, it is measured from its own corner",
      abs(block.width - 180) < 1e-6 and abs(block.height - 40) < 1e-6
      and min(min(l[0], l[2]) for l in block.lines) == 0.0,
      (block.width, block.height))
check("the text comes with it, where it was in the block",
      [(f.text, round(f.x, 6), round(f.y, 6)) for f in block.fields]
      == [("IITEG", 5.0, 25.0)],
      [(f.text, f.x, f.y) for f in block.fields])
from datum.ui.titleblock_ui import block_rect                    # noqa: E402
w, h = two.extent()
frame = doc.borders[two.border].frame(w, h)
rect = block_rect(doc, two)
check("and on every sheet its bottom right is on the border's",
      abs(rect[2] - frame[2]) < 1e-9 and abs(rect[1] - frame[1]) < 1e-9)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
