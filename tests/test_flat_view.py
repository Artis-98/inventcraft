"""A drawing view of a sheet metal part as its flat pattern, with its bend
centre lines, as Inventor's flat pattern view is."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datum.core import drawing as dwg, hlr, sheetmetal         # noqa: E402
from datum.core.document import Document                       # noqa: E402
from datum.core.views import Generator                     # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tray = os.path.join(HERE, "examples", "weld-cart", "Top Tray.icpart")
part = Document.load(tray)
part.rebuild()
flat = sheetmetal.flat_pattern(part)

doc = dwg.DrawingDocument()
sheet = doc.add_sheet("A3")
view = doc.add_view(sheet, dwg.View(kind=dwg.BASE, x=200.0, y=150.0,
                                    scale=1.0))
view.ref.path = tray
view.flat = True
Generator().rebuild(doc, base_dir=HERE, force=True)
p = view.projection
check("the view is drawn", p is not None and p.ok, view.error)
if p is not None and p.ok:
    w, h = p.box[2] - p.box[0], p.box[3] - p.box[1]
    fw, fh = flat.extents()
    check("as big as the flat pattern",
          abs(w - fw) < 0.5 and abs(h - fh) < 0.5, (w, h, fw, fh))
    check("with a bend line for every bend",
          len(p.of_kind(hlr.BEND)) == len(flat.bends) > 0,
          (len(p.of_kind(hlr.BEND)), len(flat.bends)))
again = dwg.View.from_dict(view.to_dict())
check("and it is saved as a flat view", again.flat)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
