"""The quick ones from 0.2.8: ten small things that each led the wrong way.

The SpaceMouse speed is kept between starts, and starts at three times
what it was.  A polygon takes its number of sides in the heads-up box.
FORGE files are gone.  Origin planes are faintly filled at their true
depth.  A fit asked for by hand glides there.  A rounded corner projected
from a face looking away from the sketch bulges the right way.  Redo
survives a click that changes nothing, and the arrows follow the sketch's
own history.  A dimension can be picked and deleted, or made driven, which
reads in brackets.  The Extrude dialog is laid out the way Inventor's is.

And what trying them turned up: a polygon is held together like
Inventor's; every plane on screen is filled, the picker's and one being
dragged off a face too, and highlights see-through; a fit slides straight
in rather than swinging; dimensions are picked with Ctrl and with a box;
their witness lines stay square to a line that turns; and a dimension
written in terms of a driven one follows it.
"""

import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from OCP.BRepAdaptor import BRepAdaptor_Curve                      # noqa: E402
from OCP.GeomAbs import GeomAbs_CurveType                          # noqa: E402
from OCP.Graphic3d import Graphic3d_ZLayerId_Default               # noqa: E402
from OCP.TopoDS import TopoDS                                      # noqa: E402

from datum.core import fileformat, kernel, prefs                   # noqa: E402
from datum.core.features import (                                  # noqa: E402
    NEW_BODY, OPERATION_LABELS, ExtrudeFeature, plane_from_face,
    reversed_plane,
)
from datum.core.sketch import STANDARD_PLANES                      # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.panels import SpaceMouseDialog                       # noqa: E402
from datum.ui.sheet_canvas import SheetCanvas                      # noqa: E402
from datum.ui.spacemouse import SpaceMouseSettings                 # noqa: E402
from datum.ui.theme import C, stylesheet                           # noqa: E402

FAILS = []


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


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def settle(ms=500):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(done, timeout=12.0):
    end = time.time() + timeout
    while time.time() < end and not done():
        settle(30)
    return done()


def fresh_sketch(plane="XY"):
    win.new_document(prompt=False)
    win.start_sketch_on_plane(plane)
    settle(900)
    ed.auto_constrain = False
    ed.snap_grid = False


def type_text(text):
    for ch in text:
        key = (QtCore.Qt.Key_Period if ch == "."
               else getattr(QtCore.Qt, "Key_%s" % ch))
        ed._on_key(key, ch)
    pump(2)


def lines_of(s):
    return [e for e in s.entities.values() if e.kind == "line"]


# ==========================================================================
print("the SpaceMouse speed is kept, and starts at three")
check("a fresh setting runs three times faster than it did",
      SpaceMouseSettings().sensitivity == 3.0, SpaceMouseSettings().sensitivity)
check("the window starts from the saved settings",
      near(win.spacemouse.settings.sensitivity,
           prefs.prefs().spacemouse.get("sensitivity", 3.0)),
      win.spacemouse.settings.sensitivity)
dialog = SpaceMouseDialog(win.spacemouse, win)
check("the speed slider reaches past the new default",
      dialog.sliders["sensitivity"].maximum() >= 600,
      dialog.sliders["sensitivity"].maximum())
dialog.sliders["sensitivity"].setValue(450)
check("a change is put down to be saved", dialog._save_soon.isActive())
dialog.done(0)
check("and closing writes it at once", not dialog._save_soon.isActive())
prefs.reset()
check("the next start reads it back",
      near(prefs.prefs().spacemouse.get("sensitivity", 0.0), 4.5),
      prefs.prefs().spacemouse)
again = SpaceMouseSettings()
again.load(prefs.prefs().spacemouse)
check("into the settings the puck runs on", near(again.sensitivity, 4.5),
      again.sensitivity)
dialog.deleteLater()

# ==========================================================================
print("a polygon takes its sides in the heads-up box")
fresh_sketch()
s = ed.sketch
ed.set_tool("polygon")
ed._on_click(0.0, 0.0, NONE)
ed._on_move(10.0, 0.0, NONE)
pump()
check("two heads-up fields, sides and size", len(ed.live.fields) == 2,
      len(ed.live.fields))
shown = ed.live.fields[0].text() if ed.live.fields else ""
check("the sides read as a whole number", shown.isdigit(), shown)
type_text("8")
ed._on_key(QtCore.Qt.Key_Tab, "\t")
type_text("30")
ed._on_key(QtCore.Qt.Key_Return, "\r")
pump()
check("eight sides, as typed", len(lines_of(s)) == 8, len(lines_of(s)))
corners = [math.hypot(s.points[pid].x, s.points[pid].y)
           for e in lines_of(s) for pid in e.points]
check("30 across the corners",
      corners and all(near(r, 15.0, 1e-3) for r in corners), corners)
rings = [e for e in s.entities.values()
         if e.kind == "circle" and e.construction]
check("on a construction circle, like Inventor's", len(rings) == 1,
      len(rings))
check("whose size is the one typed", any(
    c.kind == "diameter" and near(c.value, 30.0, 1e-6)
    for c in s.constraints.values()), [c.kind for c in s.constraints.values()])
check("every corner held on it", sum(
    1 for c in s.constraints.values() if c.kind == "point_on") == 8)
check("and every side held equal", sum(
    1 for c in s.constraints.values() if c.kind == "equal") == 7)
check("the count is kept for the next one", ed.polygon_sides == 8,
      ed.polygon_sides)
ed._on_click(60.0, 0.0, NONE)
ed._on_click(70.0, 0.0, NONE)
pump()
check("the next polygon has eight too", len(lines_of(s)) == 16,
      len(lines_of(s)))
ed._on_click(120.0, 0.0, NONE)
ed._on_move(130.0, 0.0, NONE)
type_text("2")
ed._on_key(QtCore.Qt.Key_Return, "\r")
pump()
check("fewer than three is held at three", len(lines_of(s)) == 19,
      len(lines_of(s)))
ed.escape()

print("and a polygon drags whole")
fresh_sketch()
s = ed.sketch
sides = s.add_polygon((0.0, 0.0), 10.0, 6, 0.0)
ed.solve()
corner = s.entities[sides[0]].points[0]
s.solve(anchors={corner: (14.0, 6.0)})


def side_lengths():
    out = []
    for eid in sides:
        a, b = (s.points[p] for p in s.entities[eid].points)
        out.append(math.hypot(b.x - a.x, b.y - a.y))
    return out


lengths = side_lengths()
check("pulled by a corner it stays regular",
      max(lengths) - min(lengths) < 1e-4, lengths)
check("and the corner went where it was pulled",
      near(s.points[corner].x, 14.0, 1e-3)
      and near(s.points[corner].y, 6.0, 1e-3),
      (s.points[corner].x, s.points[corner].y))
ring = next(e for e in s.entities.values() if e.kind == "circle")
centre = s.points[ring.points[0]]
s.solve(anchors={ring.points[0]: (30.0, 20.0)})
lengths = side_lengths()
check("moved by its centre it moves whole",
      near(centre.x, 30.0, 1e-3) and max(lengths) - min(lengths) < 1e-4,
      (centre.x, centre.y, lengths))
win.finish_sketch()
pump()

# ==========================================================================
print("FORGE files are gone")
check("no legacy extension any more",
      not hasattr(fileformat, "LEGACY_EXTENSION"))
check("and nothing in the open filter for them",
      "forge" not in fileformat.open_filter().lower())

# ==========================================================================
print("the origin planes are faintly filled, at their true depth")
win.new_document(prompt=False)
pump()
vp.set_view("top")
planes = {"XY": STANDARD_PLANES["XY"]}
vp.hide_planes()
vp.fit_all()
pump()
folder = tempfile.mkdtemp(prefix="datum_planes_")
bare = os.path.join(folder, "bare.png")
vp.grab_image(bare)
vp.show_planes(planes, 45.0)
pump()
ais = vp._plane_display.get("XY")
check("the plane is on show", ais is not None)
if ais is not None:
    check("faint", near(ais.Transparency(), vp.PLANE_FILL, 1e-6),
          ais.Transparency())
    hover = ais.DynamicHilightAttributes()
    check("its highlight is see-through too, not a wall over the model",
          hover is not None and hover.Transparency() > 0.5,
          hover.Transparency() if hover is not None else None)
    check("in the model's own layer, so the part can hide it",
          ais.ZLayer() == Graphic3d_ZLayerId_Default, ais.ZLayer())
shown_path = os.path.join(folder, "shown.png")
vp.grab_image(shown_path)
img_bare, img_shown = QtGui.QImage(bare), QtGui.QImage(shown_path)
x, y = vp.project(STANDARD_PLANES["XY"].to_3d(13.0, 13.0))
k = img_bare.width() / float(max(1, vp.width()))
px, py = int(x * k), int(y * k)
if 0 <= px < img_bare.width() and 0 <= py < img_bare.height():
    a, b = img_bare.pixelColor(px, py), img_shown.pixelColor(px, py)
    diff = max(abs(a.red() - b.red()), abs(a.green() - b.green()),
               abs(a.blue() - b.blue()))
    check("the fill is drawn, not only the outline", diff >= 2, diff)
    check("and it is faint", diff <= 60, diff)
else:
    check("the plane's middle is on screen", False, (px, py))
vp.hide_planes()

def fill_at(path):
    img = QtGui.QImage(path)
    return img.pixelColor(px, py)


def differs(a, b):
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()),
               abs(a.blue() - b.blue()))


vp.redraw()
pump()
vp.grab_image(bare)
base = fill_at(bare)
vp.show_plane_picker(planes, 45.0)
pump()
picker = os.path.join(folder, "picker.png")
vp.grab_image(picker)
check("the plane picker's sheets are filled too",
      differs(base, fill_at(picker)) >= 2,
      differs(base, fill_at(picker)))
vp.hide_plane_picker()
vp.draw_plane(STANDARD_PLANES["XY"], 45.0, C.warn, preview=True,
              transparency=0.82)
vp.redraw()
pump()
dragged = os.path.join(folder, "dragged.png")
vp.grab_image(dragged)
check("and so is a plane being dragged off a face",
      differs(base, fill_at(dragged)) >= 2, differs(base, fill_at(dragged)))
vp.clear_preview()
vp.set_view("iso")
pump()

# ==========================================================================
print("a fit asked for by hand glides there")
win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
vp.fit_all()
check("a fit the program does jumps", vp._animation is None)
camera = vp.view.Camera()
fitted = (camera.Center().X(), camera.Center().Y(), camera.Center().Z(),
          camera.Scale())
for _ in range(6):
    vp.view.Pan(600, 0)
vp.view.SetScale(vp.view.Scale() * 4.0)
vp.redraw()
pump()
target = kernel.shape_centre(win.document.shape)
vp.fit_all(animate=True)
check("one asked for glides", vp._animation is not None)
settle(200)
check("and is still on the way a moment later", vp._animation is not None)
trail = []
# the glide counts frames, so a busy machine takes longer over it
end_time = time.time() + 12.0
while vp._animation is not None and time.time() < end_time:
    trail.append(vp.project(target))
    settle(16)
check("it arrives", vp._animation is None)
trail.append(vp.project(target))
if len(trail) >= 3:
    (x0, y0), (x1, y1) = trail[0], trail[-1]
    span = math.hypot(x1 - x0, y1 - y0) or 1.0
    off_line = max(abs((x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)) / span
                   for x, y in trail)
    check("the part slides in along a straight line, not round an arc",
          off_line < 2.0, round(off_line, 2))
else:
    check("enough frames to follow it", False, len(trail))
camera = vp.view.Camera()
check("where a plain fit puts it",
      math.dist(fitted[:3], (camera.Center().X(), camera.Center().Y(),
                             camera.Center().Z())) < 1e-3 * max(1.0, fitted[3])
      and near(camera.Scale() / fitted[3], 1.0, 1e-3),
      (fitted, camera.Scale()))

sheet = SheetCanvas()
sheet.resize(600, 400)
sheet.show()
pump()
sheet._fitted = True
sheet._scale, sheet._pan = 4.0, [120.0, -40.0]
sheet.fit(animate=True)
check("a drawing sheet glides as well", sheet._glide is not None)
check("and settles fitted", wait_until(lambda: sheet._glide is None)
      and near(sheet._scale, 1.0, 1e-6)
      and near(sheet._pan[0], 0.0, 1e-6) and near(sheet._pan[1], 0.0, 1e-6),
      (sheet._scale, sheet._pan))
sheet.close()
sheet.deleteLater()

# ==========================================================================
print("rounded corners project the right way round")
block = kernel.box(40.0, 20.0, 10.0)
upright = []
for edge in kernel.edges(block):
    curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    if curve.GetType() != GeomAbs_CurveType.GeomAbs_Line:
        continue
    a = curve.Value(curve.FirstParameter())
    b = curve.Value(curve.LastParameter())
    if near(a.X(), b.X()) and near(a.Y(), b.Y()):
        upright.append(edge)
rounded = kernel.fillet(block, upright, 3.0)
top = None
for face in kernel.faces(rounded):
    plane = plane_from_face(face)
    if plane is not None and near(plane.origin[2], 10.0, 1e-6) \
            and near(abs(plane.normal[2]), 1.0, 1e-9):
        top = face
check("the rounded block has a flat top", top is not None)
if top is not None:
    for label, plane in (("looking down on it", STANDARD_PLANES["XY"]),
                         ("from underneath",
                          reversed_plane(STANDARD_PLANES["XY"]))):
        arcs = [g for kind, g in kernel.project_to_plane(top, plane)
                if kind == "arc"]
        sweeps = [(a1 - a0) % (2 * math.pi) for _c, _r, a0, a1 in arcs]
        check("four quarter arcs %s" % label,
              len(arcs) == 4
              and all(near(w, math.pi / 2, 1e-6) for w in sweeps),
              [round(math.degrees(w), 2) for w in sweeps])

# ==========================================================================
print("Redo survives a click that changes nothing")
fresh_sketch()
s = ed.sketch
ed.set_tool("line")
ed._on_click(0.0, 0.0, NONE)
ed._on_click(30.0, 0.0, NONE)
ed.escape()
pump()
drawn = len(lines_of(s))
check("a line drawn", drawn == 1, drawn)
win.undo()
pump()
s = ed.sketch
check("undone", len(lines_of(s)) == 0, len(lines_of(s)))
check("the Redo arrow is lit in the sketch", win.qat_redo.isEnabled())
ed.set_tool("select")
ed._on_click(80.0, 80.0, NONE)
pump()
check("clicking empty space leaves Redo something to do", ed.can_redo)
win.redo()
pump()
s = ed.sketch
check("and Redo brings the line back", len(lines_of(s)) == 1,
      len(lines_of(s)))
check("then the arrow goes out", not win.qat_redo.isEnabled())
win.undo()
pump()
ed.set_tool("line")
ed._on_click(0.0, 10.0, NONE)
ed._on_click(30.0, 10.0, NONE)
ed.escape()
pump()
check("a real change still clears it", not ed.can_redo)
win.finish_sketch()
pump()

# ==========================================================================
print("a dimension can be picked, deleted, and made driven")
fresh_sketch()
s = ed.sketch
lid = s.add_line((0.0, 0.0), (40.0, 0.0), weld=False)
pa, pb = s.entities[lid].points
s.add_constraint("horizontal", entities=[lid])
s.add_constraint("fix", points=[pa])
cid = s.add_constraint("distance", points=[pa, pb], value=40.0)
ed.solve()
ed.render()
pump()

drawn_text = []
real_draw_text = vp.draw_text


def recording(text, where, colour, *args, **kwargs):
    drawn_text.append((text, colour))
    return real_draw_text(text, where, colour, *args, **kwargs)


vp.draw_text = recording
ed.select_constraint(cid)
vp.draw_text = real_draw_text
check("picked", ed.selected_constraint == cid)
check("and drawn in the picked colour",
      any(colour == C.sketch_picked for _t, colour in drawn_text),
      drawn_text)

vp._menu_pos = None
menu = win.build_sketch_menu(QtWidgets.QMenu())
actions = {a.text(): a for a in menu.actions()}
check("the menu offers Delete Dimension", "Delete Dimension" in actions,
      list(actions))
check("and Driven Dimension, unticked",
      "Driven Dimension" in actions
      and actions["Driven Dimension"].isCheckable()
      and not actions["Driven Dimension"].isChecked(), list(actions))
actions["Driven Dimension"].setChecked(True)
pump()
check("ticking it makes it driven", not s.constraints[cid].driving)
drawn_text = []
vp.draw_text = recording
ed.render()
vp.draw_text = real_draw_text
labels = [t for t, _c in drawn_text]
check("a driven dimension reads in brackets",
      any(t.startswith("(") and t.endswith(")") for t in labels), labels)
s.points[pb].x = 55.0
ed.solve()
check("the line is free to change length", near(s.points[pb].x, 55.0, 1e-6),
      s.points[pb].x)
check("making it driving again holds what it measures",
      ed.set_driven(cid, False) and s.constraints[cid].driving)
check("without the line jumping", near(s.points[pb].x, 55.0, 1e-4),
      s.points[pb].x)
check("and holds that length", near(s.constraints[cid].value, 55.0, 1e-4),
      s.constraints[cid].value)

other = s.add_constraint("distance", points=[pa, pb], value=55.0)
s.constraints[other].driving = False
s.constraints[other].expression = "%s + 5" % s.constraints[cid].name
ed.solve()
check("one that would fight the first stays driven",
      not ed.set_driven(other, False) and not s.constraints[other].driving)
check("and the sketch is left as it was", near(s.points[pb].x, 55.0, 1e-4),
      s.points[pb].x)

ed.select_constraint(cid)
menu = win.build_sketch_menu(QtWidgets.QMenu())
actions = {a.text(): a for a in menu.actions()}
actions["Delete Dimension"].trigger()
pump()
check("Delete Dimension takes the dimension", cid not in s.constraints)
check("and leaves the line", lid in s.entities)
ed.select_constraint(other)
ed.delete_selected()
pump()
check("the Delete key does the same", other not in s.constraints)
win.finish_sketch()
pump()

print("dimensions are picked with Ctrl and with a box")
fresh_sketch()
s = ed.sketch
first = s.add_line((0.0, 0.0), (40.0, 0.0), weld=False)
second = s.add_line((0.0, 30.0), (40.0, 30.0), weld=False)
dims = []
for eid in (first, second):
    a, b = s.entities[eid].points
    dims.append(s.add_constraint("distance", points=[a, b], value=40.0))
    s.constraints[dims[-1]].label_offset = (0.0, -6.0)
ed.solve()
ed.render()
pump()
ed.set_tool("select")


def label(cid):
    return ed._dimension_label_at(s.constraints[cid])


CTRL = QtCore.Qt.ControlModifier
ed._on_click(*label(dims[0]), NONE)
ed._on_click(*label(dims[1]), CTRL)
check("Ctrl adds a second dimension to the pick",
      sorted(ed.selected_dimensions) == sorted(dims), ed.selected_dimensions)
ed._on_click(*label(dims[1]), CTRL)
check("and Ctrl on it again takes it off", ed.selected_dimensions == [dims[0]],
      ed.selected_dimensions)
ed._on_click(*label(dims[1]), CTRL)
ed.delete_selected()
pump()
check("Delete takes both", not any(c in s.constraints for c in dims))
check("and leaves both lines", first in s.entities and second in s.entities)
win.undo()
pump()
s = ed.sketch
check("one Undo brings both back", all(c in s.constraints for c in dims))

ed._box_start = (-5.0, 20.0)
ed._box_end = (45.0, 26.0)
ed._apply_box()
check("a box over a label picks that dimension",
      ed.selected_dimensions == [dims[1]], ed.selected_dimensions)
vp._menu_pos = None
ed._on_click(*label(dims[0]), CTRL)
menu = win.build_sketch_menu(QtWidgets.QMenu())
texts = [a.text() for a in menu.actions()]
check("the menu on a pick of two deletes both", "Delete 2 Dimensions" in texts,
      texts)
ed.clear_selection()

print("witness lines stay square to a line that turns")
a, b = s.entities[first].points
s.add_constraint("fix", points=[a])
ed.solve()
s.solve(anchors={b: (0.0, 40.0)})
ed.render()
c = s.constraints[dims[0]]
ux, uy = s.points[b].x - s.points[a].x, s.points[b].y - s.points[a].y
along = (c.label_offset[0] * ux + c.label_offset[1] * uy) / math.hypot(ux, uy)
check("the label stays square to the line", abs(along) < 1e-6,
      (c.label_offset, (ux, uy)))
check("as far out as it was", near(math.hypot(*c.label_offset), 6.0, 1e-6),
      c.label_offset)
win.finish_sketch()
pump()

print("a dimension written in terms of a driven one follows it")
fresh_sketch()
s = ed.sketch
held = s.add_line((0.0, 0.0), (20.0, 0.0), weld=False)
follows = s.add_line((0.0, 10.0), (30.0, 10.0), weld=False)
ha, hb = s.entities[held].points
fa, fb = s.entities[follows].points
for eid in (held, follows):
    s.add_constraint("horizontal", entities=[eid])
reads = s.add_constraint("distance", points=[ha, hb], value=20.0)
ed.set_driven(reads, True)
name = s.constraints[reads].name
s.add_constraint("distance", points=[fa, fb], value=20.0, expression=name)
ed.solve()
check("it starts the same length",
      near(s.points[fb].x - s.points[fa].x, 20.0, 1e-4),
      s.points[fb].x - s.points[fa].x)
s.solve(anchors={hb: (35.0, 0.0)})
check("drag the driven one's line out and the other follows",
      near(abs(s.points[fb].x - s.points[fa].x), 35.0, 1e-3),
      (s.constraints[reads].value, s.points[fb].x - s.points[fa].x))
win.finish_sketch()
pump()

# ==========================================================================
print("Extrude is laid out the way Inventor's is")
win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
settle(900)
ed.snap_grid = False
ed.set_tool("rect")
ed._on_click(0.0, 0.0, NONE)
ed._on_click(20.0, 10.0, NONE)
win.finish_sketch()
pump()
win.new_feature(ExtrudeFeature)
pump()
dialog = win._active_dialog
win.select_all_profiles()
pump()
grid = dialog.form.grid
sections = []
for row in range(grid.rowCount()):
    item = grid.itemAtPosition(row, 0)
    w = item.widget() if item is not None else None
    if w is not None and w.property("section"):
        sections.append(w.text())
check("Inventor's four sections, in its order",
      sections == ["Input Geometry", "Behavior", "Output", "Advanced"],
      sections)
check("Direction is a row of four buttons, Asymmetric last",
      [k for k, _i, _t in dialog.DIRECTIONS]
      == ["default", "flipped", "symmetric", "asymmetric"])
check("the extents no longer hide Symmetric",
      [dialog.extent.itemData(i) for i in range(dialog.extent.count())]
      == ["distance", "to_next", "to_plane", "from_to", "through_all"])
check("and there is no Flip box any more", not hasattr(dialog, "flip"))

dialog.direction.set_value("flipped")
dialog.direction.changed.emit("flipped")
pump()
check("Flipped is stored the way files always had it",
      dialog.feature.reversed and dialog.feature.extent == "distance")
dialog.direction.set_value("symmetric")
dialog.direction.changed.emit("symmetric")
pump()
check("and Symmetric as the extent it always was",
      dialog.feature.extent == "symmetric" and not dialog.feature.reversed)
check("a taper has no meaning both ways", not dialog.taper.isEnabled())
dialog.extent.setCurrentIndex(dialog.extent.findData("through_all"))
pump()
check("Through All runs both ways, so no direction to pick",
      not dialog.direction.isEnabled())
dialog.extent.setCurrentIndex(dialog.extent.findData("to_plane"))
pump()
check("To swaps the distance for a plane",
      dialog.to_plane.isVisibleTo(dialog)
      and not dialog.distance.isVisibleTo(dialog)
      and not dialog.direction.isEnabled())
dialog.extent.setCurrentIndex(dialog.extent.findData("distance"))
pump()
check("back on Distance it can be steered again",
      dialog.direction.isEnabled() and dialog.distance.isVisibleTo(dialog))
dialog.commit()
pump()
zmin, zmax = kernel.bounding_box(win.document.shape)[2::3]
check("a symmetric 10 runs 5 each way", near(zmin, -5.0, 1e-4)
      and near(zmax, 5.0, 1e-4), (zmin, zmax))
feature = win.document.features[-1]
win.edit_feature(feature.id)
pump()
dialog = win._active_dialog
check("opened again it reads Symmetric as a direction",
      dialog.direction.value() == "symmetric"
      and dialog.extent.currentData() == "distance",
      (dialog.direction.value(), dialog.extent.currentData()))
dialog.cancel()
pump()
check("the boolean says New Solid, like Inventor",
      OPERATION_LABELS[NEW_BODY] == "New Solid")

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 15 tests passed")
sys.exit(0)
