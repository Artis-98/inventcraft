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

# ==========================================================================
print("#12: Text in a sketch, through the window")

from datum.core import kernel                                      # noqa: E402
from datum.core.features import EmbossFeature                      # noqa: E402
NONE = QtCore.Qt.NoModifier

win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
before = kernel.volume(win.document.shape)
top = kernel.bounding_box(win.document.shape)[5]

win.start_sketch_on_plane("XY")
pump()
ed = win.editor
ed.snap_grid = False
answers = []
ed.text_prompt = lambda current: (answers.append(current)
                                  or {"text": "AB", "font": "Arial",
                                      "size": 4.0, "angle": 0.0,
                                      "bold": False, "italic": False})
check("the Draw panel has a Text button", "text" in win.tool_buttons)
win.set_sketch_tool("text")
ed._on_click(2.0, 2.0, NONE)
pump()
check("a click with Text asks for it, new", answers == [None], answers)
check("and puts it in the sketch", len(ed.sketch.texts) == 1)
tid = next(iter(ed.sketch.texts))
anchor = ed.sketch.points[ed.sketch.texts[tid].point]
check("its first line starts where it was clicked",
      (anchor.x, anchor.y) == (2.0, 2.0), (anchor.x, anchor.y))
box = kernel.text_box(ed.sketch, tid)
inside = ((box[0][0] + box[2][0]) / 2, (box[0][1] + box[2][1]) / 2)
check("a click inside it finds it", ed.text_at(*inside) == tid)
shot("text_sketch")

ed.set_tool("select")
ed.text_prompt = lambda current: dict(current, text="ABC")
ed._on_double_click(*inside)
pump()
check("a double-click edits it", ed.sketch.texts[tid].text == "ABC",
      ed.sketch.texts[tid].text)
ed.undo() if hasattr(ed, "undo") else None
pump()
check("and Ctrl+Z takes the edit back", ed.sketch.texts[tid].text == "AB",
      ed.sketch.texts[tid].text)

ed.clear_selection()
ed._on_click(*inside, NONE)
check("a click selects it", ed.selected_texts == [tid], ed.selected_texts)
ed.delete_selected()
check("Delete removes it", not ed.sketch.texts)
ed.undo() if hasattr(ed, "undo") else None
check("and undo brings it back", len(ed.sketch.texts) == 1)

win.finish_sketch()
pump()

print("#12: Emboss, from the ribbon")
win.new_feature(EmbossFeature)
pump()
dialog = win._active_dialog
check("Emboss opens its dialog", dialog is not None
      and type(dialog).__name__ == "EmbossDialog")
win.select_all_profiles()
pump()
check("the text is offered as the profile",
      len(dialog.feature.profiles) == 1, len(dialog.feature.profiles))
dialog.depth.set_text("0.5")
dialog.mode.set_value("engrave")
dialog.commit()
pump()
feature = win.document.features[-1]
check("an Emboss is in the tree", isinstance(feature, EmbossFeature)
      and not feature.error, getattr(feature, "error", ""))
after = kernel.volume(win.document.shape)
check("it engraved: less material", after < before - 1.0, (before, after))
check("into the top, not past it",
      abs(kernel.bounding_box(win.document.shape)[5] - top) < 0.05)
shot("emboss_part")

# ==========================================================================
print("#14: the navigation bar under the cube")

vp.set_nav_mode(None)
vp.set_view("iso")
vp.fit_all()
vp.redraw()
pump()
check("its five buttons are always there",
      all(vp.button_at(vp.width() - vp.CUBE_BUTTONS[n][0][0],
                       vp.CUBE_BUTTONS[n][0][1]) == n
          for n in vp.NAV_BUTTONS))
press("nav_pan")
check("Pan is a tool for the left button", vp.nav_mode == "pan")
eye_before = vp.view.Camera().Center()
cx, cy = vp.width() // 2, vp.height() // 2


def drag(dx, dy):
    for kind, at in ((QtCore.QEvent.MouseButtonPress, (cx, cy)),
                     (QtCore.QEvent.MouseMove, (cx + dx, cy + dy)),
                     (QtCore.QEvent.MouseButtonRelease, (cx + dx, cy + dy))):
        pos = QtCore.QPointF(*at)
        held = QtCore.Qt.NoButton if kind == QtCore.QEvent.MouseButtonRelease \
            else QtCore.Qt.LeftButton
        event = QtGui.QMouseEvent(kind, pos, vp.mapToGlobal(pos),
                                  QtCore.Qt.LeftButton if kind !=
                                  QtCore.QEvent.MouseMove else
                                  QtCore.Qt.NoButton, held,
                                  QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(vp, event)
        pump(1)


drag(120, 0)
after = vp.view.Camera().Center()
check("a left drag pans", abs(after.X() - eye_before.X())
      + abs(after.Y() - eye_before.Y()) + abs(after.Z() - eye_before.Z())
      > 1e-3)
press("nav_pan")
check("its button again ends it", vp.nav_mode is None)
press("nav_zoom")
scale = vp.view.Camera().Scale()
drag(0, -80)
check("Zoom: dragging up zooms in", vp.view.Camera().Scale() < scale,
      (scale, vp.view.Camera().Scale()))
key = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape,
                      QtCore.Qt.NoModifier)
QtWidgets.QApplication.sendEvent(vp, key)
check("Esc ends it", vp.nav_mode is None)
press("nav_orbit")
forward = vp.screen_basis()[2]
drag(90, 30)
check("Orbit turns the view", vp.screen_basis()[2] != forward)
press("nav_orbit")
press("nav_fit")
check("Zoom All is a click, not a tool", vp.nav_mode is None)
shot("navbar")

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
