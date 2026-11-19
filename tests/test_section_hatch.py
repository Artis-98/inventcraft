"""A section view's cut face is hatched, sized to the model.

A part cut open used to show a flat cap, and on a thin walled part that
read as an empty shell.  Now the cut carries stripes, as a drawing's
section does, and the spacing follows the model: a small pin and a big
frame both get about the same number of lines across.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=300):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def cut(size):
    win.new_document(prompt=False)
    settle()
    win.document.add_feature(PrimitiveFeature(
        kind="cylinder", a=str(size), b=str(2 * size), c=str(size)))
    win.rebuild()
    settle(500)
    vp = win.viewport
    vp.set_clip("section", ((0, 0, 0), (0, 1, 0)))
    clip = vp.clip_plane("section")
    tex = clip.CappingTexture()
    scale = tex.GetParams().Scale().x() if tex is not None else None
    vp.set_clip("section", None)
    return clip, tex, scale


clip, tex, small = cut(10)
check("the cut is capped", clip.IsCapping())
check("and the cap is hatched", tex is not None)
_clip, _tex, big = cut(400)
check("the stripes follow the model's size: 40 times bigger, 40 times "
      "the spacing", small and big and abs(small / big - 40.0) < 2.0,
      (small, big))
check("the stripe tile is kept in the cache",
      os.path.isfile(win.viewport._hatch_tile()))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
