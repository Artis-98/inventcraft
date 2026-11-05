"""Fillet and Chamfer keep the edges picked lit while the dialog is open,
so which edges were taken is seen, not guessed from the rounded preview."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import kernel                                   # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.features import FilletFeature, PrimitiveFeature  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def settle(ms=200):
    end = QtCore.QTime.currentTime().addMSecs(ms)
    while QtCore.QTime.currentTime() < end:
        app.processEvents()


doc = Document()
box = PrimitiveFeature()
box.kind, box.a, box.b, box.c = "box", "40", "30", "20"
doc.add_feature(box)
doc.rebuild()
path = os.path.join(tempfile.mkdtemp(), "box.icpart")
doc.save(path)

from datum.ui.main_window import MainWindow                     # noqa: E402

win = MainWindow()
win.resize(1300, 850)
win.show()
win.open_path(path)
settle(800)
win.new_feature(FilletFeature)
settle(400)
dialog = win._active_dialog
edges = kernel.edges(win.pick_shape())[:2]
win.viewport.selected_shapes = lambda: list(edges)
win.viewport.selected_edges = lambda: list(edges)
dialog.on_selection()
del win.viewport.selected_shapes
del win.viewport.selected_edges
settle(300)
check("two edges picked, two lit", len(dialog._edge_marks) == 2,
      len(dialog._edge_marks))
dialog.cancel()
settle(300)
check("and nothing lit once it closes", not dialog._edge_marks)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
