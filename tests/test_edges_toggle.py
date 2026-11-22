"""Shaded and Shaded with Edges switch every time.

The edge setting is part of each body's picture, so switching used to
take only when something else redrew the body. Switched back and forth
on a box, the edges must come and go each time.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_edges_")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1100, 750)
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


def dark(tag):
    path = os.path.join(WORK, tag + ".png")
    win.viewport.grab_image(path)
    image = QtGui.QImage(path)
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if QtGui.QColor(image.pixel(x, y)).lightness() < 40:
                count += 1
    return count


settle(600)
win.new_document(prompt=False)
settle(300)
win.document.add_feature(PrimitiveFeature(kind="box", a="40", b="30",
                                          c="20"))
win.rebuild()
win.viewport.fit_all()
settle(300)

win.viewport.set_display_mode("shaded_edges")
settle(200)
with_edges = dark("a")
win.viewport.set_display_mode("shaded")
settle(200)
without = dark("b")
win.viewport.set_display_mode("shaded_edges")
settle(200)
again = dark("c")
win.viewport.set_display_mode("shaded")
settle(200)
again_without = dark("d")
check("edges show", with_edges > without + 50, (with_edges, without))
check("and come back after being turned off",
      abs(again - with_edges) < 0.1 * with_edges + 20, (again, with_edges))
check("and go again", abs(again_without - without) < 0.1 * max(without, 1)
      + 20, (again_without, without))

win.document.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
