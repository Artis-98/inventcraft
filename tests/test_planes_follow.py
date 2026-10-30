"""Sketches follow the planes they are on, projections follow the sketches
they came from, and one Work Plane command works a plane out from what is
picked: two lines, three points, a line and a point, or a line at an angle
to a plane.

From a real table skeleton: a work plane offset half the table's depth
off XZ, a sketch of the legs on it, and the sketch staying behind when the
depth changed, with its projected line too.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core.document import Document                         # noqa: E402
from datum.core.features import (                                # noqa: E402
    SketchFeature, WorkPlaneFeature)
from datum.core.sketch import Sketch, SketchPlane                # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_planes_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


def table():
    """The table's top as a rectangle on XY, a work plane half its depth
    off XZ, and a sketch of two legs on that plane with the XY plane's
    line projected onto it."""
    doc = Document()
    top = SketchFeature(name="Top")
    top.sketch = Sketch(SketchPlane(), "Top")
    top.sketch.add_rectangle((-350.0, -250.0), (350.0, 250.0))
    doc.add_feature(top)
    doc.params.add("depth", "500")
    wp = WorkPlaneFeature(name="Front")
    wp.base, wp.offset = "XZ", "depth/2"
    doc.add_feature(wp)
    doc.rebuild()
    legs = SketchFeature(name="Legs")
    legs.sketch = Sketch(SketchPlane(doc.planes["Front"].origin,
                                     doc.planes["Front"].normal,
                                     doc.planes["Front"].xdir, "Front"),
                         "Legs")
    legs.sketch.add_line((-300.0, 0.0), (-300.0, 700.0))
    legs.sketch.add_line((300.0, 0.0), (300.0, 700.0))
    doc.add_feature(legs)
    doc.rebuild()
    return doc, top, wp, legs


print("a sketch follows its plane")
doc, top, wp, legs = table()
legs.plane_ref = "Front"
doc.set_parameter("depth", "800")
doc.rebuild()
y = legs.sketch.plane.origin[1]
check("the depth from 500 to 800: the legs' sketch moves with its plane",
      near(abs(y), 400.0), y)
saved = doc.save(os.path.join(WORK, "kept"))
again = Document.load(saved)
again.rebuild()
check("and keeps its plane through a save",
      next(f for f in again.features if f.name == "Legs").plane_ref
      == "Front")

print("a sketch from before keeps its plane")
doc, top, wp, legs = table()
check("a sketch from before has no plane kept", legs.plane_ref == "Front"
      or legs.sketch.plane.name == "Front")
doc.set_parameter("depth", "800")
doc.rebuild()
check("it is found by the plane's name, and follows it",
      legs.plane_ref == "Front"
      and near(abs(legs.sketch.plane.origin[1]), 400.0),
      (legs.plane_ref, legs.sketch.plane.origin))

print("a projection follows the sketch it came from")
doc, top, wp, legs = table()
s = legs.sketch
# the top's front edge, cast onto the legs' sketch, as Project Geometry
# with no source used to leave it
front = next(eid for eid, e in top.sketch.entities.items()
             if all(near(top.sketch.points[p].y, -250.0) for p in e.points))
ends = [top.sketch.plane.to_3d(top.sketch.points[p].x,
                               top.sketch.points[p].y)
        for p in top.sketch.entities[front].points]
flat = [s.plane.to_2d(p) for p in ends]
line = s.add_line(flat[0], flat[1])
for pid in s.entities[line].points:
    s.points[pid].fixed = True
s.add_projection({}, [line])
doc.rebuild()
record = s.projections[0]
check("one made with no source is tied to the line it lies on",
      record.source == {"sketch": top.id, "entity": front}, record.source)
for point in top.sketch.points.values():
    if near(point.x, 350.0):
        point.x = 500.0
doc.rebuild()
xs = sorted(s.points[p].x for p in s.entities[line].points)
check("the top made wider: the projected line goes with it",
      near(xs[1], 500.0), xs)

print("Work Plane from picks")
doc, top, wp, legs = table()
t = top.sketch
bottom, right, upper, left = [eid for eid in t.entities
                              if t.entities[eid].kind == "line"][:4]
corner = [t.entities[bottom].points[0], t.entities[bottom].points[1],
          t.entities[right].points[1]]
leg = next(iter(legs.sketch.entities))
cases = [
    ("two_lines", [{"sketch": top.id, "entity": bottom},
                   {"sketch": top.id, "entity": upper}], (0, 0, 1)),
    ("three_points", [{"sketch": top.id, "point": p} for p in corner],
     (0, 0, 1)),
    ("line_point", [{"sketch": top.id, "entity": bottom},
                    {"sketch": top.id, "point": corner[1]}], (1, 0, 0)),
    ("line_plane", [{"sketch": top.id, "entity": bottom}, {"plane": "XY"}],
     (0, -1, 0)),
    # a leg at the front and the top's back edge: skew, no plane holds both
    ("two_lines", [{"sketch": top.id, "entity": upper},
                   {"sketch": legs.id, "entity": leg}], None),
]
made = []
for i, (mode, refs, _n) in enumerate(cases):
    plane = WorkPlaneFeature(name="P%d" % i)
    plane.mode, plane.refs, plane.offset, plane.angle = mode, refs, "0", "90"
    doc.add_feature(plane)
    made.append(plane)
report = doc.rebuild()
for (mode, refs, normal), plane in zip(cases[:4], made):
    n = doc.planes[plane.name].normal
    check("%s makes the plane it should" % mode,
          all(near(abs(a), abs(b)) for a, b in zip(n, normal)), n)
check("two lines that do not lie in one plane are told, not guessed",
      any("do not lie in one plane" in m for _i, m in report.errors),
      report.errors)
xs_before = doc.planes["P2"].origin[0]
for point in t.points.values():
    if near(point.x, 350.0):
        point.x = 450.0
doc.rebuild()
check("the plane square to a line through its corner follows the corner",
      near(doc.planes["P2"].origin[0] - xs_before, 100.0),
      doc.planes["P2"].origin)
again = Document.load(doc.save(os.path.join(WORK, "planes")))
again.rebuild()
check("planes from picks keep what they were made from through a save",
      [(f.mode, f.refs) for f in again.features
       if isinstance(f, WorkPlaneFeature) and f.mode != "offset"]
      == [(f.mode, f.refs) for f in made])

print("in the window")
from datum.ui.main_window import MainWindow                      # noqa: E402

app = QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1400, 900)
win.show()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


doc, top, wp, legs = table()
path = doc.save(os.path.join(WORK, "table"))
win.open_path(path)
settle(900)
win.viewport.set_view("iso")
settle(500)
win.viewport.finish_animation()
win.start_sketch_on_plane("Front")
settle(900)
win.viewport.finish_animation()
d = win.viewport.view.Camera().Direction()
check("a sketch started on a plane away from the origin, in a part with no "
      "solid, is looked at square on",
      near(abs(d.Y()), 1.0, 1e-9) and near(d.X(), 0.0, 1e-9),
      (d.X(), d.Y(), d.Z()))
sketch = win.document.features[-1]
check("and keeps that plane", sketch.plane_ref == "Front")
editor = win.editor
snaps = [snap for snap in editor._model_snap_points() if snap[4]]
check("the other sketches' ends and middles are there to snap to",
      len(snaps) >= 12 and {snap[0] for snap in snaps} >= {"corner", "mid"},
      len(snaps))
leg_end = next(i for i, snap in enumerate(editor._model_snap_points())
               if snap[4] and snap[4]["sketch"] == legs.id
               and snap[0] == "corner")
editor.begin_change()
target = editor._take_model_snap(leg_end)
record = editor.sketch.projections[-1]
check("taking one projects its line as construction, tied to it",
      target is not None and record.construction
      and record.source.get("sketch") == legs.id, record.source)
win.finish_sketch()
settle(300)

print("a work plane's right-click: Edit Offset and Redefine")
front = next(f for f in win.document.features if f.name == "Front")
win.set_plane_offset(front.id, "depth/2 + 50")
check("Edit Offset moves it, the sketch on it going too",
      near(abs(win.document.planes["Front"].origin[1]), 300.0)
      and near(abs(sketch.sketch.plane.origin[1]), 300.0),
      win.document.planes["Front"].origin)
t = next(f for f in win.document.features if f.name == "Top")
lines = [eid for eid, e in t.sketch.entities.items() if e.kind == "line"]
win.plane_action("redefine", front.id)
for eid in (lines[0], lines[2]):
    ends = tuple(t.sketch.plane.to_3d(t.sketch.points[q].x,
                                      t.sketch.points[q].y)
                 for q in t.sketch.entities[eid].points)
    win._plane_take_pick(("line", {"sketch": t.id, "entity": eid}, ends))
settle(300)
dialog = win._active_dialog
if dialog is not None:
    dialog.commit() if hasattr(dialog, "commit") else dialog.accept()
settle(300)
check("Redefine makes the same plane from new picks, its name kept",
      front.mode == "two_lines" and front.name == "Front"
      and near(abs(win.document.planes["Front"].normal[2]), 1.0)
      and sum(isinstance(f, WorkPlaneFeature)
              for f in win.document.features) == 1,
      (front.mode, win.document.planes["Front"].normal))

print("a Select button lights up while it takes the picks")
from datum.ui.widgets import SelectionField                      # noqa: E402

field = SelectionField("Select features")
field.set_picking(True)
lit = field.button.styleSheet()
field.set_picking(False)
check("lit while on, plain when off", "background" in lit
      and "background" not in field.button.styleSheet(), lit)

print("a part edited in place")
from datum.core.assembly import AssemblyDocument                 # noqa: E402
from datum.core.features import ExtrudeFeature, MirrorFeature     # noqa: E402
from datum.ui.assembly_browser import ROLE_ID, ROLE_KIND          # noqa: E402

block = Document()
outline = SketchFeature(name="Outline")
outline.sketch = Sketch(SketchPlane(), "Outline")
outline.sketch.add_rectangle((0.0, 0.0), (40.0, 20.0))
block.add_feature(outline)
ex = ExtrudeFeature(name="Block")
ex.sketch_id = outline.id
ex.distance = "10"
block.add_feature(ex)
block.rebuild()
block_path = block.save(os.path.join(WORK, "block"))
asm = AssemblyDocument()
asm.path = os.path.join(WORK, "holder.icasm")
asm.place(block_path)
asm.save(asm.path)
win.open_path(asm.path)
settle(1200)
win.edit_in_place(win.assembly.occurrences[0].id)
settle(1000)
win.new_feature(MirrorFeature)
settle(400)
mirror = win._active_dialog
tree = win.assembly_ui.browser
# mirroring features: the pick for them is on as soon as that is chosen
mirror.scope.set_value("features")
mirror.scope.changed.emit("features")
picker = mirror.armed_picker()
check("choosing features turns their pick on", picker is mirror.parents)
row = None
it = QtWidgets.QTreeWidgetItemIterator(tree)
while it.value():
    item = it.value()
    if item.data(0, ROLE_KIND) == "feature" and item.text(0) == "Block":
        row = item
    it += 1
tree._clicked(row, 0)
check("a feature clicked in the assembly tree goes to Mirror's pick",
      row is not None and ex.id in mirror.picked_features(),
      mirror.picked_features() if mirror else None)
mirror.cancel()
settle(300)
win.start_sketch_on_plane("XY")
settle(600)
win.editor.sketch.add_circle((10.0, 10.0), 3.0)
win.finish_sketch()
settle(600)
names = []
it = QtWidgets.QTreeWidgetItemIterator(tree)
while it.value():
    if it.value().data(0, ROLE_KIND) == "feature":
        names.append(it.value().text(0))
    it += 1
check("a sketch made in it shows in the tree straight away",
      any(n.startswith("Sketch") for n in names), names)

print("Split along a work plane")
from datum.core.features import SplitFeature                     # noqa: E402

win.finish_in_place()
settle(400)
cutter = WorkPlaneFeature(name="Cutter")
cutter.base, cutter.offset = "YZ", "15"
block.add_feature(cutter)
block.rebuild()
block.save(block_path)
win.open_path(block_path)
settle(900)
win.new_feature(SplitFeature)
settle(400)
split = win._active_dialog
split.tool_pick.set_picking(True)
offered = sorted(getattr(win.viewport, "_plane_picker", {}) or {})
check("its plane button offers the planes to click, the work plane too",
      "Cutter" in offered and "XY" in offered, offered)
fid = next(f.id for f in win.document.features if f.name == "Cutter")
win._tree_item_clicked("feature", str(fid))
check("the work plane clicked in the tree is the tool",
      split.plane.currentData() == "Cutter" and not split.tool_pick.picking,
      split.plane.currentData())
split.cancel()
settle(300)
check("and the planes it offered go when it closes",
      not getattr(win.viewport, "_plane_picker", None))

print("Split Solid takes the one solid picked")
from datum.core.features import NEW_BODY, PrimitiveFeature         # noqa: E402
from datum.core import kernel                                      # noqa: E402

two = Document()
for x, name in ((0, "Left"), (100, "Right")):
    box = PrimitiveFeature()
    box.kind = "box"
    box.a, box.b, box.c = "60", "40", "20"
    box.origin = [x, -20, 0]
    box.operation, box.body_name = NEW_BODY, name
    two.add_feature(box)
two.rebuild()
two_path = os.path.join(WORK, "two.pdat")
two.save(two_path)
win.open_path(two_path)
settle(900)
win.new_feature(SplitFeature)
settle(400)
split = win._active_dialog
split.method.set_value("solid")
split.method.changed.emit("solid")
split._take_plane("XZ")
settle(300)
check("Split Solid on two solids has the Solids pick ready",
      split.solids is not None and split.solids.picking
      and win.viewport.selection_mode == "body",
      win.viewport.selection_mode)
right = next(b.shape for b in win.document.bodies if b.name == "Right")
win.viewport.selected_shapes = lambda: [kernel.solids(right)[0]]
win._on_viewport_selection()
del win.viewport.selected_shapes
settle(300)
check("a solid clicked is taken, not the split of the whole part",
      split.picked_solids() == ["Right"], split.picked_solids())
check("and the picked one is lit",
      len(getattr(win.viewport, "_solid_marks", [])) == 1)
split.commit()
settle(400)
names = sorted(b.name for b in win.document.bodies)
check("only that one is split: three solids", len(names) == 3, names)
check("and nothing is lit once it is done",
      not getattr(win.viewport, "_solid_marks", []))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
