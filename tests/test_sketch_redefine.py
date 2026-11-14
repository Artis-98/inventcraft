"""Sketch Redefine: move a sketch to another plane or face after the fact.

Asked for through the Suggest button (board #330, #331).  A sketch drawn
on XY and extruded is moved to XZ: the body turns with it.  A second
sketch on the block's top face is moved to its side face, and only faces
that existed before that sketch can be picked.  Esc leaves it alone, and
undo puts it back.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from datum.core import kernel  # noqa: E402
from datum.core.features import ExtrudeFeature, SketchFeature  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

FAILS = []

app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1200, 800)
win.show()
app.processEvents()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def pump(n=4):
    for _ in range(n):
        app.processEvents()


def rect(x0, y0, x1, y1):
    win.set_sketch_tool("rect")
    win.editor._on_move(x0, y0, QtCore.Qt.NoModifier)
    win.editor._on_click(x0, y0, QtCore.Qt.NoModifier)
    win.editor._on_move(x1, y1, QtCore.Qt.NoModifier)
    win.editor._on_click(x1, y1, QtCore.Qt.NoModifier)


def extrude(distance):
    win.new_feature(ExtrudeFeature)
    win.select_all_profiles()
    win._active_dialog.distance.set_text(str(distance))
    win._active_dialog.commit()
    pump()


def box():
    b = kernel.bounding_box(win.document.shape)
    return tuple(round(b[i + 3] - b[i], 3) for i in range(3))


print("a block on XY")
win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
rect(-30, -20, 30, 20)
win.finish_sketch()
pump()
extrude(10)
first = next(f for f in win.document.features if isinstance(f, SketchFeature))
check("60 x 40 x 10", box() == (60.0, 40.0, 10.0), box())

print("redefined onto XZ")
win.plane_action("redefine_sketch", first.id)
pump()
check("the picker is up", win._pending_plane_pick)
check("the model is rolled back to before the sketch",
      win.document.rollback_index == win.document.index_of(first.id),
      win.document.rollback_index)
win._pending_plane_pick = False
win.viewport.hide_plane_picker()
win.start_sketch_on_plane("XZ")
pump()
check("the model is rolled forward again", win.document.rollback_index is None,
      win.document.rollback_index)
check("the sketch keeps XZ", first.plane_ref == "XZ", first.plane_ref)
check("the block turned with it: 60 wide, 10 deep, 40 tall",
      box() == (60.0, 10.0, 40.0), box())
check("nothing editing", not win.editor.active)

print("undo puts it back")
win.undo()
pump()
first = next(f for f in win.document.features if isinstance(f, SketchFeature))
check("on XY again", first.plane_ref == "XY", first.plane_ref)
check("and the block lies flat", box() == (60.0, 40.0, 10.0), box())

print("Esc leaves it alone")
win.plane_action("redefine_sketch", first.id)
pump()
win.cancel_current() if hasattr(win, "cancel_current") else None
if win._pending_plane_pick:
    # what Esc does, through the window's own key handling
    win.viewport.setFocus()
    from PySide6 import QtGui, QtTest  # noqa: E402
    QtTest.QTest.keyClick(win.viewport, QtCore.Qt.Key_Escape)
    pump()
check("the picker is gone", not win._pending_plane_pick)
check("rolled forward", win.document.rollback_index is None,
      win.document.rollback_index)
check("still XY", first.plane_ref == "XY", first.plane_ref)

print("a sketch on the top face, moved to a side face")
top = max(kernel.faces(win.document.shape),
          key=lambda f: kernel.shape_centre(f)[2])
win.sketch_on_face(top)
pump()
rect(-5, -5, 5, 5)
win.finish_sketch()
pump()
extrude(5)
second = [f for f in win.document.features
          if isinstance(f, SketchFeature)][-1]
check("a boss on top: 15 tall", box()[2] == 15.0, box())
win.plane_action("redefine_sketch", second.id)
pump()
shape = win.document.shape
check("the boss is not offered: the body is the plain block",
      box() == (60.0, 40.0, 10.0), box())
side = max(kernel.faces(shape), key=lambda f: kernel.shape_centre(f)[0])
win.sketch_on_face(side)
pump()
check("on a face now", second.face_ref is not None and not second.plane_ref)
# where on the face it lands is the face's own sketch origin, as for a
# new sketch there; what matters is that it now sticks out sideways
check("the boss stands off the side: 65 wide", box()[0] == 65.0, box())

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
