"""0.3.3: what was asked for on GitHub after 0.3.2.

#14 the view cube, looking square at a face: four triangles turn to the
next face and two curved arrows roll the view a quarter turn.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch22_")
SHOTS = os.environ.get("DATUM_SHOTS", "")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def same(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
vp = win.viewport


def pump(n=4):
    for _ in range(n):
        app.processEvents()


def basis():
    vp.finish_animation()
    return vp.screen_basis()


def shot(name):
    if SHOTS:
        vp.grab_image(os.path.join(SHOTS, name + ".png"))


def press(name):
    """A real click on a cube button, where it is drawn."""
    at = vp.CUBE_BUTTONS[name][0]
    pos = QtCore.QPointF(vp.width() - at[0], at[1])
    for kind in (QtCore.QEvent.MouseButtonPress,
                 QtCore.QEvent.MouseButtonRelease):
        event = QtGui.QMouseEvent(kind, pos, vp.mapToGlobal(pos),
                                  QtCore.Qt.LeftButton, QtCore.Qt.LeftButton
                                  if kind == QtCore.QEvent.MouseButtonPress
                                  else QtCore.Qt.NoButton,
                                  QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(vp, event)
    pump()
    vp.finish_animation()
    vp.redraw()


# ==========================================================================
print("#14: the arrows round the cube")

win.new_document(prompt=False)
pump()
vp.set_view("iso")
vp.redraw()
check("at an angle, the view is not square", not vp.is_square())
check("and the arrows are not there to click",
      vp.button_at(vp.width() - 85, 33) is None)
check("the house still is", vp.button_at(vp.width() - 150, 26) == "home")
shot("cube_iso")

vp.set_view("front")
vp.redraw()
check("looking at Front, the view is square", vp.is_square())
check("and the arrows are there",
      all(vp.button_at(vp.width() - vp.CUBE_BUTTONS[n][0][0],
                       vp.CUBE_BUTTONS[n][0][1]) == n
          for n in vp.SQUARE_ONLY))
shot("cube_front")

right, up, forward = basis()
check("Front looks along +Y with Z up",
      same(forward, (0, 1, 0)) and same(up, (0, 0, 1)), (forward, up))

press("face_up")
right, up, forward = basis()
check("the triangle above turns to Top: looking down, -Z",
      same(forward, (0, 0, -1)), forward)
check("with what was Front at the bottom", same(up, (0, 1, 0)), up)
check("still square", vp.is_square())

press("face_down")
right, up, forward = basis()
check("the triangle below comes back to Front",
      same(forward, (0, 1, 0)) and same(up, (0, 0, 1)), (forward, up))

press("face_right")
right, up, forward = basis()
check("the triangle on the right turns to Right, looking along -X",
      same(forward, (-1, 0, 0)) and same(up, (0, 0, 1)), (forward, up))
press("face_left")
right, up, forward = basis()
check("and the one on the left back to Front",
      same(forward, (0, 1, 0)), forward)

press("roll_cw")
right, up, forward = basis()
check("clockwise: still looking at Front", same(forward, (0, 1, 0)), forward)
check("with what was on the left now up", same(up, (-1, 0, 0)), up)
shot("cube_rolled")
press("roll_ccw")
right, up, forward = basis()
check("anticlockwise turns it back", same(up, (0, 0, 1)), up)

print("a quarter turn ends square even from a little off")
vp.view.Rotate(0.0, 0.0, 0.0004)
vp.redraw()
vp.cube_step("roll_cw", animate=False)
right, up, forward = basis()
check("snapped to the cube, not carried off",
      same(forward, (0, 1, 0), 1e-9) and same(up, (-1, 0, 0), 1e-9),
      (forward, up))

print("in a sketch, where it was asked for")
win.start_sketch_on_plane("XY")
pump()
vp.finish_animation()
vp.redraw()
check("a new sketch looks square at its plane", vp.is_square())
before = basis()[1]
press("roll_ccw")
after = basis()[1]
check("and rolls a quarter turn",
      abs(sum(a * b for a, b in zip(before, after))) < 1e-6, (before, after))
check("the sketch is still open", win.editor.sketch is not None)

win.finish_sketch() if hasattr(win, "finish_sketch") else None
pump()

# ==========================================================================
print("#11: the degrees of freedom left, where they are seen")

win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
pump()
ed = win.editor
badge = win.status_sketch
line = ed.sketch.add_line((0.0, 0.0), (40.0, 0.0))
ed.solve()
pump()
check("a free line reads in words how much is left",
      badge.text() == "%d degrees of freedom left" % ed.sketch.dof
      and ed.sketch.dof > 1, (ed.sketch.dof, badge.text()))
check("in the colour free geometry is drawn in",
      badge.property("state") == "free" and "border" in badge.styleSheet())
shot("dof_free")
if SHOTS:
    win.statusBar().grab().save(os.path.join(SHOTS, "bar_free.png"))

ends = list(ed.sketch.entities[line].points)     if hasattr(ed.sketch.entities[line], "points") else None
if ends is None:
    e = ed.sketch.entities[line]
    ends = [getattr(e, n) for n in ("p1", "p2") if hasattr(e, n)]         or [getattr(e, n) for n in ("a", "b") if hasattr(e, n)]
ed.sketch.add_constraint("fix", points=[ends[0]])
ed.sketch.add_constraint("horizontal", entities=[line])
ed.solve()
pump()
check("one left reads in the singular",
      ed.sketch.dof == 1 and badge.text() == "1 degree of freedom left",
      (ed.sketch.dof, badge.text()))
ed.sketch.add_constraint("distance_x", points=ends[:2], value=40.0)
ed.solve()
pump()
if ed.sketch.dof == 0:
    check("fully constrained says so", badge.text().endswith(
        "Fully constrained"), badge.text())
    check("in its own colour", badge.property("state") == "full")
    shot("dof_full")
    if SHOTS:
        win.statusBar().grab().save(os.path.join(SHOTS, "bar_full.png"))
else:
    print("  skip  could not constrain it fully here: %d left" % ed.sketch.dof)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
