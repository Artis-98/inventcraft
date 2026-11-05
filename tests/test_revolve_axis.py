"""Revolve around a line of the profile's own sketch, as Inventor does: a
centre line drawn for the purpose is taken by itself, and any line of the
sketch can be clicked in the view."""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                    # noqa: E402

from datum.core import kernel                                   # noqa: E402
from datum.core.document import Document                        # noqa: E402
from datum.core.features import RevolveFeature, SketchFeature   # noqa: E402
from datum.core.sketch import Sketch, SketchPlane               # noqa: E402

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
sk = SketchFeature(name="Profile")
sk.sketch = Sketch(SketchPlane(), "Profile")
# a 10 x 20 rectangle standing 30 off a vertical centre line at x = 50
sk.sketch.add_rectangle((80.0, 0.0), (90.0, 20.0))
centre = sk.sketch.add_line((50.0, -10.0), (50.0, 30.0), construction=True)
edge = sk.sketch.add_line((0.0, -10.0), (0.0, 30.0))
doc.add_feature(sk)
doc.rebuild()
path = os.path.join(tempfile.mkdtemp(), "ring.icpart")
doc.save(path)

from datum.ui.main_window import MainWindow                     # noqa: E402

win = MainWindow()
win.resize(1300, 850)
win.show()
win.open_path(path)
settle(800)
win.viewport.set_view("front")
win.viewport.finish_animation()
win.viewport.fit_all()
settle(200)
win.new_feature(RevolveFeature)
settle(600)
dialog = win._active_dialog
dialog.preview()
settle(300)
check("the sketch's one centre line is the axis by itself",
      dialog.axis.currentData() == "entity:%d" % centre,
      dialog.axis.currentData())
ring = 2 * math.pi * 35.0 * 200.0
check("and the ring it makes is right",
      win.document.shape is not None
      and abs(kernel.volume(win.document.shape) - ring) < 1,
      kernel.volume(win.document.shape) if win.document.shape else None)
dialog.axis_pick.set_picking(True)
plane = dialog._profile_sketch()[1].plane
x, y = win.viewport.project(plane.to_3d(0.0, 10.0))
for kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
    QtWidgets.QApplication.sendEvent(win.viewport, QtGui.QMouseEvent(
        kind, QtCore.QPointF(x, y), QtCore.QPointF(x, y),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
settle(300)
check("a line clicked in the view is the axis",
      dialog.axis.currentData() == "entity:%d" % edge
      and not dialog.axis_pick.picking, dialog.axis.currentData())
dialog.commit()
settle(400)
made = next(f for f in win.document.features if isinstance(f, RevolveFeature))
check("saved as that line", made.axis == "entity" and made.axis_entity == edge)
check("around it", abs(kernel.volume(win.document.shape)
                       - 2 * math.pi * 85.0 * 200.0) < 1)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
