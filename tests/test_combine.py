"""Combine, Inventor's: solids already made, joined, cut or intersected,
the tool solids used up unless Keep Toolbody says otherwise."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import kernel                                   # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.features import (                               # noqa: E402
    CUT, INTERSECT, JOIN, NEW_BODY, CombineFeature, PrimitiveFeature)

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def two_blocks():
    doc = Document()
    for x, name in ((0, "A"), (30, "B")):
        box = PrimitiveFeature()
        box.kind, box.a, box.b, box.c = "box", "40", "20", "10"
        box.origin = [x, 0, 0]
        box.operation, box.body_name = NEW_BODY, name
        doc.add_feature(box)
    return doc


for op, keep, want_vol, want_bodies in (
        (JOIN, False, 7000 * 10 / 10 * 10 / 10 * 1.0, ["A"]),
        (CUT, False, 30 * 20 * 10, ["A"]),
        (INTERSECT, False, 10 * 20 * 10, ["A"]),
        (CUT, True, 30 * 20 * 10 + 40 * 20 * 10, ["A", "B"])):
    doc = two_blocks()
    c = CombineFeature()
    c.base, c.tools, c.operation, c.keep_tools = "A", ["B"], op, keep
    doc.add_feature(c)
    doc.rebuild()
    if op == JOIN:
        want_vol = 70 * 20 * 10
    names = sorted(b.name for b in doc.bodies if b.valid)
    check("%s%s" % (op, ", keeping the toolbody" if keep else ""),
          not c.error and names == want_bodies
          and abs(kernel.volume(doc.shape) - want_vol) < 1e-3,
          (c.error, names, kernel.volume(doc.shape)))

print("in the dialog")
doc = two_blocks()
doc.rebuild()
path = os.path.join(tempfile.mkdtemp(), "two.icpart")
doc.save(path)
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from datum.ui.main_window import MainWindow                     # noqa: E402

win = MainWindow()
win.show()
win.open_path(path)
for _ in range(60):
    app.processEvents()
win.new_feature(CombineFeature)
for _ in range(40):
    app.processEvents()
dialog = win._active_dialog
check("the base pick is ready", dialog.base_pick.picking)
win._tree_item_clicked("body", "A")
check("a solid clicked in the tree is the base, and Toolbodies is next",
      dialog.feature.base == "A" and dialog.tools.picking)
win._tree_item_clicked("body", "B")
dialog.operation.set_value(CUT)
dialog.commit()
for _ in range(40):
    app.processEvents()
check("Cut: B taken out of A, B used up",
      [b.name for b in win.document.bodies if b.valid] == ["A"]
      and abs(kernel.volume(win.document.shape) - 6000) < 1e-3,
      kernel.volume(win.document.shape))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
