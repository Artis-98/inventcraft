"""The medium ones from 0.2.8.

The SpaceMouse moves the view once a frame however many axes are pushed.
Free Move slides only the dragged part's picture until the mouse is let
go.  The mouse buttons are a preference: orbit and pan on the buttons a
person wants, the wheel either way round.  A centre rectangle and a centre
slot hold their centre on what was clicked, and every rectangle, slot and
arc takes typed sizes at each click.  The origin's planes, axes and centre
point project onto a sketch.  Solid bodies hide and show from the tree.
A hidden plane or sketch shows while it is picked in the tree.  The
selection box is filled, red one way and green the other, in parts,
assemblies and sketches, and in an assembly the components it takes all
get the material.
"""

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost               # noqa: E402

from datum.core import kernel, prefs                               # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import (                                  # noqa: E402
    NEW_BODY, ExtrudeFeature, PrimitiveFeature,
)
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.prefs_ui import PreferencesDialog                    # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch16_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
ed = win.editor
vp = win.viewport
NONE = QtCore.Qt.NoModifier
LEFT, MIDDLE, RIGHT = (QtCore.Qt.LeftButton, QtCore.Qt.MiddleButton,
                       QtCore.Qt.RightButton)
SHIFT = QtCore.Qt.ShiftModifier


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def settle(ms=500):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def fresh_sketch(plane="XY"):
    win.new_document(prompt=False)
    win.start_sketch_on_plane(plane)
    settle(900)
    ed.auto_constrain = True
    ed.snap_grid = False
    return ed.sketch


def type_text(text):
    for ch in text:
        key = (QtCore.Qt.Key_Period if ch == "."
               else getattr(QtCore.Qt, "Key_%s" % ch))
        ed._on_key(key, ch)
    pump(2)


def enter():
    ed._on_key(QtCore.Qt.Key_Return, "\r")
    pump(2)


def tab():
    ed._on_key(QtCore.Qt.Key_Tab, "\t")


def click(u, v, mods=NONE):
    ed._on_move(u, v, mods)
    ed._on_click(u, v, mods)
    pump(2)


def mouse(kind, pos, button, buttons, mods=NONE):
    p = QtCore.QPointF(*pos)
    QtWidgets.QApplication.sendEvent(vp, QtGui.QMouseEvent(
        kind, p, vp.mapToGlobal(p), button, buttons, mods))


def drag(button, a, b, mods=NONE):
    mouse(QtCore.QEvent.MouseButtonPress, a, button, button, mods)
    for i in range(1, 7):
        t = i / 6.0
        mouse(QtCore.QEvent.MouseMove,
              (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
              QtCore.Qt.NoButton, button, mods)
    mouse(QtCore.QEvent.MouseButtonRelease, b, button, QtCore.Qt.NoButton,
          mods)
    pump()


def camera():
    cam = vp.view.Camera()
    c, e = cam.Center(), cam.Eye()
    return ((c.X(), c.Y(), c.Z()), (e.X(), e.Y(), e.Z()), cam.Scale())


def facing(state):
    centre, eye, _scale = state
    d = [centre[i] - eye[i] for i in range(3)]
    length = math.sqrt(sum(x * x for x in d)) or 1.0
    return [x / length for x in d]


def make_part(name, dx, dy, dz):
    doc = Document()
    feature = PrimitiveFeature()
    feature.kind = "box"
    feature.a, feature.b, feature.c = str(dx), str(dy), str(dz)
    doc.add_feature(feature)
    doc.rebuild()
    return doc.save(os.path.join(WORK, name))


# ==========================================================================
print("the SpaceMouse moves the view once a frame")


class CountingView:
    """The real view, counting what a SpaceMouse frame does to it."""

    def __init__(self, real):
        self._real = real
        self.redraws = 0
        self.immediate = True
        self.moves_drawn_at_once = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def Redraw(self):
        self.redraws += 1
        return self._real.Redraw()

    def SetImmediateUpdate(self, on):
        self.immediate = on
        return self._real.SetImmediateUpdate(on)

    def _move(self, name, *args):
        if self.immediate:
            self.moves_drawn_at_once += 1
        return getattr(self._real, name)(*args)

    def Panning(self, *args):
        return self._move("Panning", *args)

    def SetZoom(self, *args):
        return self._move("SetZoom", *args)

    def Rotate(self, *args):
        return self._move("Rotate", *args)


win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
real_view = vp.view
counting = CountingView(real_view)
vp.view = counting
try:
    vp.apply_spacemouse(0.4, 0.3, 0.5, 0.2, 0.3, 0.1)
finally:
    vp.view = real_view
check("all six axes pushed: drawn once", counting.redraws == 1,
      counting.redraws)
check("and no camera move drew on its own", counting.moves_drawn_at_once == 0,
      counting.moves_drawn_at_once)
check("immediate drawing is back on after", real_view.SetImmediateUpdate(True))

fresh_sketch()
key_before = getattr(vp, "_grid_key", None)
counting = CountingView(real_view)
vp.view = counting
try:
    vp.apply_spacemouse(0.4, 0.0, 0.3, 0.2, 0.0, 0.1)
finally:
    vp.view = real_view
check("in a sketch, a pan and a turn still draw once", counting.redraws == 1,
      counting.redraws)
check("and leave the grid alone",
      getattr(vp, "_grid_key", None) == key_before)
win.finish_sketch()
pump()


# ==========================================================================
print("Free Move slides only the picture until the mouse is let go")

PLATE = make_part("plate", 60, 40, 8)
PEG = make_part("peg", 10, 10, 25)
win.new_assembly(prompt=False)
pump()
QtWidgets.QFileDialog.getOpenFileNames = staticmethod(
    lambda *a, **k: ([PLATE, PEG], ""))
win.assembly_ui.place_component()
pump()
asm = win.assembly
peg = asm.occurrences[1]
start = list(peg.placement.position)
win.toggle_component_tool("move")
pump()
shown = []
real_show = win.assembly_ui.show_components


def counting_show(*args, **kwargs):
    shown.append(1)
    return real_show(*args, **kwargs)


win.assembly_ui.show_components = counting_show
vp.component_drag_started.emit(peg.id)
for _ in range(3):
    vp.component_drag_moved.emit((5.0, 0.0, 0.0))
pump()
check("no component was redrawn while dragging", not shown, len(shown))
picture = vp._component_ais[peg.id]
moved_by = picture.LocalTransformation().TranslationPart().X()
check("the dragged picture followed the mouse", near(moved_by, 15.0, 1e-6),
      moved_by)
check("and the placement too", near(peg.placement.position[0] - start[0],
                                    15.0, 1e-6), peg.placement.position)
win.assembly_ui.show_components = real_show
vp.component_drag_finished.emit()
pump()
check("let go, it stays where it was put",
      near(asm.occurrences[1].placement.position[0] - start[0], 15.0, 1e-6),
      asm.occurrences[1].placement.position)
fresh = vp._component_ais[peg.id]
from OCP.TopLoc import TopLoc_Location                             # noqa: E402
drawn_at = kernel.shape_centre(fresh.Shape().Moved(
    TopLoc_Location(fresh.LocalTransformation())))
check("drawn where it landed, without drawing everything again",
      all(near(a, b, 1e-6) for a, b in zip(
          drawn_at, kernel.shape_centre(asm.occurrences[1].placed()))),
      (drawn_at, kernel.shape_centre(asm.occurrences[1].placed())))
win.toggle_component_tool("move")
pump()


# ==========================================================================
print("in an assembly a box picks several, and they all take the material")

check("box selection is on in an assembly", vp.box_select_enabled)
# saved, so its parts are found beside it and their files can be written
asm.save(os.path.join(WORK, "rig.icasm"))
win.assembly_ui.browser.select_occurrences([o.id for o in asm.occurrences])
pump()
check("both picked", sorted(win.assembly_ui.selected_occurrences())
      == sorted(o.id for o in asm.occurrences),
      win.assembly_ui.selected_occurrences())
win.set_material("Brass")
pump()
check("both parts are brass now, in their own files",
      all(Document.load(p).material == "Brass" for p in (PLATE, PEG)),
      [Document.load(p).material for p in (PLATE, PEG)])
check("and it says how many", "2 parts" in win.status_message.text(),
      win.status_message.text())


# ==========================================================================
print("the mouse buttons are a preference")

p = prefs.prefs()
nav = vp.navigation_for
check("out of the box: right orbits, the wheel pans",
      nav(RIGHT, NONE) == "orbit" and nav(MIDDLE, NONE) == "pan"
      and nav(MIDDLE, SHIFT) == "orbit" and nav(LEFT, NONE) is None)

win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
vp.set_view("iso")
vp.fit_all()
pump()

p.mouse_pan = prefs.MOUSE_LEFT
check("set to the left button, the left button pans",
      nav(LEFT, NONE) == "pan")
check("with Shift it is the selection box again", nav(LEFT, SHIFT) is None)
before = camera()
said = []
vp.selection_changed.connect(lambda: said.append(1))
drag(LEFT, (300, 300), (420, 360))
after = camera()
check("a left drag moved the view",
      math.dist(before[0], after[0]) > 1e-3, (before[0], after[0]))
check("without turning it",
      sum(a * b for a, b in zip(facing(before), facing(after))) > 1 - 1e-9)
check("and was no click", not said, len(said))
mouse(QtCore.QEvent.MouseButtonPress, (500, 300), LEFT, LEFT)
mouse(QtCore.QEvent.MouseButtonRelease, (500, 300), LEFT, QtCore.Qt.NoButton)
pump()
check("a plain left click still selects", said, len(said))

p.mouse_orbit, p.mouse_pan = prefs.MOUSE_SHIFT_MIDDLE, prefs.MOUSE_MIDDLE
check("Inventor's: Shift and the wheel orbit, the right button does not",
      nav(MIDDLE, SHIFT) == "orbit" and nav(RIGHT, NONE) is None)
vp._context_menu = lambda pos: None
before = camera()
drag(RIGHT, (400, 300), (520, 330))
check("a right drag leaves the view as it was",
      sum(a * b for a, b in zip(facing(before), facing(camera())))
      > 1 - 1e-9)
drag(MIDDLE, (400, 300), (520, 330), SHIFT)
check("and Shift with the wheel turns it",
      sum(a * b for a, b in zip(facing(before), facing(camera())))
      < 1 - 1e-6)

p.mouse_orbit, p.mouse_pan = prefs.MOUSE_RIGHT, prefs.MOUSE_MIDDLE


def wheel(steps):
    pos = QtCore.QPointF(500, 300)
    QtWidgets.QApplication.sendEvent(vp, QtGui.QWheelEvent(
        pos, vp.mapToGlobal(pos), QtCore.QPoint(0, 0),
        QtCore.QPoint(0, 120 * steps), QtCore.Qt.NoButton, NONE,
        QtCore.Qt.NoScrollPhase, False))
    pump()


scale = camera()[2]
wheel(1)
zoomed_in = camera()[2] < scale
p.zoom_reversed = True
scale = camera()[2]
wheel(1)
check("the wheel zooms in, and the other way when reversed",
      zoomed_in and camera()[2] > scale)
p.zoom_reversed = False

dialog = PreferencesDialog(win)
dialog.scheme_combo.setCurrentIndex(
    dialog.scheme_combo.findText("Pan with the left button"))
check("picking a ready-made set sets both buttons",
      dialog.mouse_orbit_combo.currentData() == prefs.MOUSE_RIGHT
      and dialog.mouse_pan_combo.currentData() == prefs.MOUSE_LEFT)
dialog.mouse_orbit_combo.setCurrentIndex(
    dialog.mouse_orbit_combo.findData(prefs.MOUSE_LEFT))
check("one button cannot do both: pan moves out of the way",
      dialog.mouse_orbit_combo.currentData() == prefs.MOUSE_LEFT
      and dialog.mouse_pan_combo.currentData() != prefs.MOUSE_LEFT,
      dialog.mouse_pan_combo.currentData())
check("and the set reads as your own",
      dialog.scheme_combo.currentText() == "Your own",
      dialog.scheme_combo.currentText())
dialog.gather()
check("it is what gets kept", p.mouse_orbit == prefs.MOUSE_LEFT)
saved = prefs.Preferences.from_dict(p.to_dict())
check("and read back", saved.mouse_orbit == p.mouse_orbit
      and saved.mouse_pan == p.mouse_pan)
dialog.deleteLater()
p.mouse_orbit, p.mouse_pan = prefs.MOUSE_RIGHT, prefs.MOUSE_MIDDLE


# ==========================================================================
print("centre rectangles and slots hold their centre; sizes at every click")

s = fresh_sketch()
ed.set_tool("rect_centre")
click(0.0, 0.0)
ed._on_move(12.0, 7.0, NONE)
type_text("40")
tab()
type_text("20")
enter()
lines = [e for e in s.entities.values() if e.kind == "line"]
check("four sides and two construction diagonals",
      len([e for e in lines if not e.construction]) == 4
      and len([e for e in lines if e.construction]) == 2)
check("centred on the origin and sized, it is fully constrained",
      s.solve_message == "fully constrained", s.solve_message)
win.finish_sketch()
pump()

s = fresh_sketch()
ed.set_tool("slot_centre")
click(0.0, 0.0)
ed._on_move(10.0, 0.2, NONE)
check("the centre slot asks for its length first",
      [lb.text() for lb in ed.live.labels] == ["L"],
      [lb.text() for lb in ed.live.labels])
type_text("60")
enter()
ed._on_move(3.0, 4.0, NONE)
check("then for its width", [lb.text() for lb in ed.live.labels] == ["W"],
      [lb.text() for lb in ed.live.labels])
type_text("10")
enter()
dims = sorted((c.kind, round(c.value, 6)) for c in s.constraints.values()
              if c.is_dimension)
check("both sizes became dimensions",
      dims == [("diameter", 10.0), ("distance", 60.0)], dims)
check("level and on the origin, it is fully constrained",
      s.solve_message == "fully constrained", s.solve_message)
win.finish_sketch()
pump()

s = fresh_sketch()
ed.set_tool("rect3")
click(0.0, 0.0)
ed._on_move(10.0, 0.5, NONE)
type_text("30")
enter()
click(5.0, 6.0)
sides = [e for e in s.entities.values() if e.kind == "line"]
first = math.dist(*[(s.points[q].x, s.points[q].y)
                    for q in sides[0].points])
check("a size typed at the first click, then a plain click",
      near(first, 30.0, 1e-6), first)
check("still leaves its dimension", any(
    c.kind == "distance" and near(c.value, 30.0)
    for c in s.constraints.values()))
win.finish_sketch()
pump()

s = fresh_sketch()
ed.set_tool("arc")
click(0.0, 0.0)
ed._on_move(10.0, 0.0, NONE)
type_text("25")
enter()
ed._on_move(0.0, 10.0, NONE)
check("the arc asks for its sweep in degrees",
      [lb.text() for lb in ed.live.labels] == ["∠"])
type_text("120")
enter()
arcs = [e for e in s.entities.values() if e.kind == "arc"]
if arcs:
    arc = arcs[0]
    centre = s.points[arc.points[0]]
    ends = [s.points[q] for q in arc.points[1:3]]
    angles = sorted(math.degrees(math.atan2(q.y - centre.y, q.x - centre.x))
                    % 360.0 for q in ends)
    check("an arc of radius 25", near(arc.radius, 25.0, 1e-6), arc.radius)
    check("sweeping 120 degrees", near(angles[1] - angles[0], 120.0, 1e-4),
          angles)
    check("with its radius a dimension", any(
        c.kind == "radius" and near(c.value, 25.0)
        for c in s.constraints.values()))
else:
    check("an arc was made", False)
win.finish_sketch()
pump()


# ==========================================================================
print("the origin projects onto a sketch")

s = fresh_sketch()
ed.set_tool("line")
win.project_geometry()
check("Project Geometry starts with no body yet", ed.tool == "project",
      ed.tool)
tree = win.browser
kinds = [tree.topLevelItem(0).child(i) for i in
         range(tree.topLevelItem(0).childCount())]
origin = next(i for i in kinds if i.text(0) == "Origin")
names = [origin.child(i).text(0).replace("   (hidden)", "")
         for i in range(origin.childCount())]
check("the Origin folder has Inventor's axes and centre point",
      names[-4:] == ["X Axis", "Y Axis", "Z Axis", "Center Point"], names)
before = len(s.entities)
tree.item_clicked.emit("axis", "X")
pump()
made = [e for eid, e in s.entities.items() if eid not in range(0)]
x_line = [e for e in s.entities.values() if e.kind == "line"]
check("the X axis lands as a line", len(x_line) == 1, len(x_line))
if x_line:
    a, b = (s.points[q] for q in x_line[0].points)
    check("along the sketch's X, through the origin",
          near(a.y, 0.0) and near(b.y, 0.0) and a.x * b.x < 0,
          (a.x, a.y, b.x, b.y))
    check("as construction, pinned", x_line[0].construction
          and s.points[x_line[0].points[0]].fixed)
count = len(s.entities)
tree.item_clicked.emit("axis", "Z")
pump()
check("the Z axis, end on, is the origin already: nothing added",
      len(s.entities) == count and "already" in win.status_message.text(),
      win.status_message.text())
tree.item_clicked.emit("plane", "XZ")
pump()
check("the XZ plane lands as the line it cuts along",
      len(s.entities) == count + 1, len(s.entities) - count)
count = len(s.entities)
tree.item_clicked.emit("plane", "XY")
pump()
check("the XY plane, lying in the sketch, lands as its outline",
      len(s.entities) == count + 4, len(s.entities) - count)
check("none of it makes a profile", not kernel.sketch_faces(s))
ed.escape()
win.finish_sketch()
pump()


# ==========================================================================
print("solid bodies hide and show from the tree")

doc = Document()
for x, dx, op, name in ((0, 60, None, ""), (200, 30, NEW_BODY, "Cover")):
    feature = PrimitiveFeature()
    feature.kind = "box"
    feature.a, feature.b, feature.c = str(dx), "30", "20"
    feature.origin = [x, 0, 0]
    if op:
        feature.operation = op
        feature.body_name = name
    doc.add_feature(feature)
doc.rebuild()
twobody = doc.save(os.path.join(WORK, "twobody"))
win.open_path(twobody)
pump()
doc = win.document
check("two bodies", len(doc.bodies) == 2, len(doc.bodies))
folder = None
root = win.browser.topLevelItem(0)
for i in range(root.childCount()):
    if root.child(i).text(0).startswith("Solid Bodies"):
        folder = root.child(i)
cover = None
if folder is not None:
    for i in range(folder.childCount()):
        if folder.child(i).text(0).startswith("Cover"):
            cover = folder.child(i)
check("the Solid Bodies folder lists Cover", cover is not None)
if cover is not None:
    menu = win.browser.menu_for(cover)
    actions = {a.text(): a for a in menu.actions()}
    check("its menu: Hide, Hide Others, Show All",
          {"Hide", "Hide Others", "Show All"} <= set(actions), list(actions))
    actions["Hide"].trigger()
    pump()
    check("hidden, it is no longer drawn",
          near(kernel.volume(vp._model_shape), 60 * 30 * 20, 1e-6),
          kernel.volume(vp._model_shape))
    check("but the part is still both", near(kernel.volume(doc.shape),
                                             60 * 30 * 20 + 30 * 30 * 20))
    root = win.browser.topLevelItem(0)
    folder = next(root.child(i) for i in range(root.childCount())
                  if root.child(i).text(0).startswith("Solid Bodies"))
    names = [folder.child(i).text(0) for i in range(folder.childCount())]
    check("and the tree says so", any("Cover" in n and "hidden" in n
                                      for n in names), names)
    win.save_document() if hasattr(win, "save_document") else doc.save(
        doc.path)
    check("kept with the part", Document.load(twobody).hidden_bodies
          == {"Cover"}, Document.load(twobody).hidden_bodies)
    win.set_body_visibility("others", "Cover")
    pump()
    check("Hide Others leaves only Cover",
          near(kernel.volume(vp._model_shape), 30 * 30 * 20, 1e-6))
    win.set_body_visibility("all", "")
    pump()
    check("Show All brings both back",
          near(kernel.volume(vp._model_shape), 60 * 30 * 20 + 30 * 30 * 20,
               1e-6))


# ==========================================================================
print("a hidden plane or sketch shows while it is picked in the tree")

win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
settle(800)
ed.snap_grid = False
ed.set_tool("rect")
click(0.0, 0.0)
click(20.0, 10.0)
win.finish_sketch()
pump()
win.new_feature(ExtrudeFeature)
pump()
win._active_dialog.commit()
pump()
doc = win.document
check("the origin planes are put away once there is a body",
      not doc.plane_visible("XY"))
tree = win.browser


def tree_item(kind, key):
    for item in tree._iter_items():
        if (item.data(0, QtCore.Qt.UserRole + 2) == kind
                and str(item.data(0, QtCore.Qt.UserRole + 1)) == key):
            return item
    return None


tree.clearSelection()
tree_item("plane", "XY").setSelected(True)
pump()
first_drawn = list(win._tree_pick_drawn)
check("picking the hidden XY plane shows it", len(first_drawn) >= 1,
      len(first_drawn))
check("without switching it on", not doc.plane_visible("XY"))
tree.clearSelection()
tree_item("plane", "XZ").setSelected(True)
pump()
check("picking XZ puts XY away again",
      not any(vp.context.IsDisplayed(a) for a in first_drawn))
check("and shows XZ", len(win._tree_pick_drawn) >= 1)
sketch_id = next(f.id for f in doc.sketch_features())
check("the sketch went out of sight with its extrude",
      tree.is_sketch_hidden(sketch_id, doc))
tree.clearSelection()
tree_item("feature", str(sketch_id)).setSelected(True)
pump()
check("picking it shows it, highlighted", len(win._tree_pick_drawn) >= 4,
      len(win._tree_pick_drawn))
tree.clearSelection()
pump()
check("picking nothing shows nothing", not win._tree_pick_drawn)


# ==========================================================================
print("the selection box is filled, red one way and green the other")

check("a box in a part too", vp.box_select_enabled)
red = QtGui.QColor(vp.BOX_WINDOW)
green = QtGui.QColor(vp.BOX_CROSSING)
check("left to right is red", red.red() > red.green() and red.red() > red.blue())
check("right to left is green", green.green() > green.red())
check("see-through", 0.7 <= vp.BOX_FILL < 1.0, vp.BOX_FILL)
mouse(QtCore.QEvent.MouseButtonPress, (300, 200), LEFT, LEFT)
mouse(QtCore.QEvent.MouseMove, (500, 350), QtCore.Qt.NoButton, LEFT)
pump()
band = vp._sel_band
check("dragging draws a filled box", band is not None and band.IsFilling())
mouse(QtCore.QEvent.MouseButtonRelease, (500, 350), LEFT, QtCore.Qt.NoButton)
pump()
check("and it goes when let go", vp._sel_band is None)

s = fresh_sketch()
ed.set_tool("select")
ed._box_start = (-30.0, -20.0)
ed._box_end = (20.0, 15.0)
ed._render_preview()
fills = [a for a in vp._preview if a.ZLayer() == Graphic3d_ZLayerId_Topmost
         and a.DisplayMode() == 1]
check("in a sketch the box is filled as well, over everything",
      len(fills) == 1, len(fills))
ed._box_start = ed._box_end = None
win.finish_sketch()
pump()

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 16 tests passed")
sys.exit(0)
