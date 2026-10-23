"""The big ones from 0.2.8, and what trying the medium ones turned up.

The Solid Bodies folder is there from one body.  A hidden plane or sketch
shows while the pointer is over it in the tree.  The 3D selection box is
flat on the screen.  The view moves the camera and draws once per turn.
A feature dialog shows the part as it was and what the feature does, see
through.  A fillet round a hole in a cylinder has no seam line, and a
pattern repeats the fillet with the hole.  The quick access row is the
title bar.  Section View cuts the view at a picked plane.  The sketch has
its toggles on the status bar.  A sketch snaps to the model's corners and
edge midpoints.
"""

import gc
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from OCP.BRep import BRep_Tool                                     # noqa: E402
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface  # noqa: E402
from OCP.GeomAbs import GeomAbs_SurfaceType                        # noqa: E402
from OCP.TopoDS import TopoDS                                      # noqa: E402

from datum.core import kernel                                      # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import (                                  # noqa: E402
    CUT, ExtrudeFeature, FilletFeature, PatternFeature, PrimitiveFeature,
    ProfileSelection, SketchFeature,
)
from datum.core.naming import RefSet                               # noqa: E402
from datum.core.sketch import STANDARD_PLANES, Sketch              # noqa: E402
from datum.ui import frame                                         # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import C, stylesheet                           # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch17_")


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
win.resize(1500, 900)
win.show()
app.processEvents()
ed = win.editor
vp = win.viewport
NONE = QtCore.Qt.NoModifier
RIGHT = QtCore.Qt.RightButton


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def settle(ms=500):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def mouse(kind, pos, button, buttons, mods=NONE):
    p = QtCore.QPointF(*pos)
    QtWidgets.QApplication.sendEvent(vp, QtGui.QMouseEvent(
        kind, p, vp.mapToGlobal(p), button, buttons, mods))


def new_box():
    win.new_document(prompt=False)
    win.new_primitive("box")
    pump()
    win._active_dialog.commit()
    pump()
    return win.document


def tree_rows():
    root = win.browser.topLevelItem(0)
    return [root.child(i) for i in range(root.childCount())]


# ==========================================================================
print("the Solid Bodies folder is there from one body")

new_box()
check("one body, one folder",
      any(r.text(0).startswith("Solid Bodies(1)") for r in tree_rows()),
      [r.text(0) for r in tree_rows()])
win.set_body_visibility("hide", win.document.bodies[0].name)
pump()
folder = next((r for r in tree_rows()
               if r.text(0).startswith("Solid Bodies")), None)
check("hidden, it still has its row to show it again from",
      folder is not None and folder.childCount() == 1
      and "hidden" in folder.child(0).text(0))
win.set_body_visibility("all", "")
pump()


# ==========================================================================
print("a hidden plane shows while the pointer is over it in the tree")

doc = win.document
check("the origin planes are put away once there is a body",
      not doc.plane_visible("XZ"))
xz = next(i for i in win.browser._iter_items()
          if i.data(0, QtCore.Qt.UserRole + 1) == "XZ")
win.browser.clearSelection()
pump()
win.browser._entered(xz, 0)
pump()
hover_drawn = list(win._tree_pick_drawn)
check("the pointer over XZ shows it", len(hover_drawn) >= 1,
      len(hover_drawn))
win.browser.leaveEvent(QtCore.QEvent(QtCore.QEvent.Leave))
pump()
check("and leaving the tree puts it away",
      not win._tree_pick_drawn
      and not any(vp.context.IsDisplayed(a) for a in hover_drawn))


# ==========================================================================
print("the 3D selection box sits flat on the screen")

mouse(QtCore.QEvent.MouseButtonPress, (300, 200), QtCore.Qt.LeftButton,
      QtCore.Qt.LeftButton)
mouse(QtCore.QEvent.MouseMove, (500, 350), QtCore.Qt.NoButton,
      QtCore.Qt.LeftButton)
pump()
band = vp._sel_band
persistence = band.TransformPersistence() if band is not None else None
check("the box keeps its screen placement, not a place in the model",
      persistence is not None and persistence.IsTrihedronOr2d())
mouse(QtCore.QEvent.MouseButtonRelease, (500, 350), QtCore.Qt.LeftButton,
      QtCore.Qt.NoButton)
pump()


# ==========================================================================
print("the view moves the camera and draws once a turn")


class CountingView:
    def __init__(self, real):
        self._real = real
        self.redraws = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def Redraw(self):
        self.redraws += 1
        return self._real.Redraw()


real_view = vp.view
counting = CountingView(real_view)
vp.view = counting
try:
    mouse(QtCore.QEvent.MouseButtonPress, (600, 400), RIGHT, RIGHT)
    gc_during = gc.isenabled()
    for i in range(30):
        mouse(QtCore.QEvent.MouseMove, (600 + i * 3, 400 + i), QtCore.Qt.NoButton,
              RIGHT)
    drawn_during = counting.redraws
    pump()
    drawn_after = counting.redraws
    mouse(QtCore.QEvent.MouseButtonRelease, (690, 430), RIGHT,
          QtCore.Qt.NoButton)
    pump()
finally:
    vp.view = real_view
check("thirty moves draw nothing on the spot", drawn_during == 0,
      drawn_during)
check("then one frame shows where they got to", drawn_after == 1,
      drawn_after)
check("garbage collection waits while the view is turned", not gc_during)
check("and is back on after", gc.isenabled())
times = []
vp.frame_timed.connect(times.append)
vp.set_frame_time(True)
vp.redraw()
pump()
check("the frame time readout reports", times and times[-1] >= 0, times)
check("in the status bar", win.status_frame.isVisible()
      and "ms" in win.status_frame.text(), win.status_frame.text())
vp.set_frame_time(False)
check("and goes when switched off", not win.status_frame.isVisible())


# ==========================================================================
print("a feature dialog shows what the feature will do")

doc = new_box()
win.start_sketch_on_plane("XY")
settle(800)
ed.snap_grid = False
ed.set_tool("circle")
ed._on_click(10.0, 8.0, NONE)
ed._on_click(14.0, 8.0, NONE)
win.finish_sketch()
pump()
win.new_feature(ExtrudeFeature)
pump()
dialog = win._active_dialog
win.select_all_profiles()
dialog.operation.set_value(CUT)
dialog.direction.set_value("symmetric")
dialog.distance.set_text("60")
dialog.preview()
pump()
check("the part is shown as it was", win._preview_base is not None
      and kernel.same_shape(vp._model_shape, win._preview_base))
check("uncut", near(kernel.volume(vp._model_shape), 40 * 30 * 20, 1e-6),
      kernel.volume(vp._model_shape))
ghosts = [a for a in win._preview_drawn if a.DisplayMode() == 1]
check("with the cut shown see-through, its whole length",
      len(ghosts) == 1, len(ghosts))
check("in red", ghosts and ghosts[0].Transparency() > 0.3)
check("and the faces picked on are the part as it was",
      win.pick_shape() is win._preview_base)
dialog.commit()
pump()
check("on OK the preview goes and the cut part is drawn",
      not win._preview_drawn and win._preview_base is None
      and kernel.volume(vp._model_shape) < 40 * 30 * 20 - 1)

win.new_feature(FilletFeature)
pump()
dialog = win._active_dialog
upright = []
for e in kernel.edges(doc.shape):
    c = BRepAdaptor_Curve(TopoDS.Edge_s(e))
    a, b = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
    if (near(a.X(), b.X()) and near(a.Y(), b.Y())
            and abs(a.Z() - b.Z()) > 1):
        upright.append(e)
refs = RefSet()
refs.capture_from(doc.shape, "edge", upright[:4])
dialog.feature.refs = refs
dialog.size.set_text("4")
dialog.preview()
pump()
check("a fillet shows the sharp body", win._preview_base is not None
      and near(kernel.volume(vp._model_shape), kernel.volume(
          win._preview_base)))
check("with what it takes away, and its edges picked out",
      len(win._preview_drawn) >= 2, len(win._preview_drawn))
dialog.commit()
pump()

win.new_feature(PatternFeature, mode="circular")
pump()
dialog = win._active_dialog
cut = [f for f in doc.features if isinstance(f, ExtrudeFeature)][-1]
for i in range(dialog.parents.count()):
    item = dialog.parents.item(i)
    if int(item.data(QtCore.Qt.UserRole)) == cut.id:
        item.setCheckState(QtCore.Qt.Checked)
pump()
check("a pattern shows every copy", len(win._preview_drawn) == 1
      and len(kernel.explore(
          win.document.preview_parts(dialog.feature.id)["tool"][0],
          __import__("OCP.TopAbs", fromlist=["x"]).TopAbs_SOLID)) == 2,
      len(win._preview_drawn))
dialog.cancel()
pump()
check("Cancel puts it all back", not win._preview_drawn)


# ==========================================================================
print("fillets round holes in a cylinder: no seam line, and they pattern")

part = Document()
cylinder = PrimitiveFeature()
cylinder.kind = "cylinder"
cylinder.a, cylinder.b, cylinder.c = "20", "40", "0"
part.add_feature(cylinder)
sketch = SketchFeature()
sketch.sketch = Sketch(plane=STANDARD_PLANES["XZ"])
sketch.sketch.add_circle((0.0, 20.0), 4.0)
part.add_feature(sketch)
hole = ExtrudeFeature()
hole.sketch_id = sketch.id
hole.profiles = ProfileSelection()
hole.operation = CUT
hole.extent = "through_all"
part.add_feature(hole)
part.rebuild()
rims = []
for e in kernel.edges(part.shape):
    c = BRepAdaptor_Curve(TopoDS.Edge_s(e))
    p = c.Value(0.5 * (c.FirstParameter() + c.LastParameter()))
    if abs(p.Z() - 20.0) < 6 and math.hypot(p.X(), p.Y()) > 19.0:
        rims.append(e)
round_off = FilletFeature()
refs = RefSet()
refs.capture_from(part.shape, "edge", rims)
round_off.refs = refs
round_off.radius = "1.5"
part.add_feature(round_off)
part.rebuild()
check("the hole and its fillet built", part.last_report.ok,
      part.last_report.message)
kernel.mark_seams(part.shape)
freeform = [f for f in kernel.faces(part.shape)
            if BRepAdaptor_Surface(f).GetType()
            not in (GeomAbs_SurfaceType.GeomAbs_Plane,
                    GeomAbs_SurfaceType.GeomAbs_Cylinder)]
closed = [e for f in freeform for e in kernel.edges(f)
          if BRep_Tool.IsClosed_s(TopoDS.Edge_s(e), f)]
check("the fillet surfaces close on themselves", closed, len(closed))
check("and that seam is a seam, not drawn and not picked",
      closed and all(kernel.is_seam(e) for e in closed))
pattern = PatternFeature()
pattern.mode = "circular"
pattern.parents = [hole.id, round_off.id]
pattern.count1 = "3"
pattern.axis = "Z"
part.add_feature(pattern)
part.rebuild()
fillets = [f for f in kernel.faces(part.shape)
           if BRepAdaptor_Surface(f).GetType()
           not in (GeomAbs_SurfaceType.GeomAbs_Plane,
                   GeomAbs_SurfaceType.GeomAbs_Cylinder)]
check("the hole and its fillet pattern round the cylinder",
      part.last_report.ok and len(fillets) == 3 * len(freeform),
      (part.last_report.message, len(fillets), len(freeform)))
check("into one sound solid", kernel.is_valid(part.shape))


# ==========================================================================
print("the quick access row is the title bar")

ribbon = win.ribbon
check("the DATUM mark leads the row", ribbon.logo.pixmap() is not None)
check("the program and the document in the row",
      ribbon.document_label.text().startswith("InventCraft"),
      ribbon.document_label.text())
if win._custom_frame:
    check("with minimise, maximise and close at the right end",
          ribbon.window_buttons.isVisible())
    label = ribbon.document_label
    centre = label.mapToGlobal(label.rect().center())
    check("the title drags the window", win.title_hit(centre)
          == frame.HT_CAPTION, win.title_hit(centre))
    button = win.qat_undo
    check("a tool on it is still a tool",
          win.title_hit(button.mapToGlobal(button.rect().center()))
          == frame.HT_CLIENT)
    check("the top edge resizes",
          win.title_hit(win.mapToGlobal(QtCore.QPoint(win.width() // 2, 1)))
          == frame.HT_TOP)
    check("the window and its frame agree, nothing hangs off",
          win.geometry() == win.frameGeometry(),
          (win.geometry(), win.frameGeometry()))
    win.toggle_maximised()
    settle(400)
    check("maximise turns the button into Restore",
          ribbon.maximise_button.toolTip() == "Restore Down")
    win.toggle_maximised()
    settle(400)
    check("and back", ribbon.maximise_button.toolTip() == "Maximise")
else:
    check("off Windows the system's title bar stays",
          not ribbon.window_buttons.isVisible())


# ==========================================================================
print("Section View cuts the view at a picked plane")

new_box()
vp.set_view("iso")
vp.fit_all()
pump()
win.section_btn.setChecked(True)
pump()
check("it asks for a plane", win._section_pick and vp.plane_picker_active)
vp.picked_plane = lambda: "XZ"
vp.selection_changed.emit()
del vp.picked_plane
pump()
check("picked, the view is cut", vp.clip_plane("section") is not None)
check("its toolbar is up", win.section_bar.isVisible())
origin, keep = win._section_frame()
check("the camera side is the side cut away",
      sum(keep[i] * vp.looking()[i] for i in range(3)) > 0)
win.section_bar.value.setValue(6.0)
pump()
moved, _keep = win._section_frame()
check("a typed distance moves the cut", near(math.dist(moved, origin), 6.0))
win.section_bar.flip.click()
pump()
_o, flipped = win._section_frame()
check("Flip keeps the other side",
      all(near(flipped[i], -keep[i]) for i in range(3)))
win.section_bar.rotate_button.setChecked(True)
win.section_bar.value.setValue(30.0)
pump()
_o, turned = win._section_frame()
check("Rotate tips it", near(sum(turned[i] * flipped[i] for i in range(3)),
                             math.cos(math.radians(30.0)), 1e-6))
win.section_bar.accepted.emit()
pump()
check("OK keeps the cut with the button lit",
      vp.clip_plane("section") is not None and win.section_btn.isChecked()
      and not win.section_bar.isVisible())
win.section_btn.setChecked(False)
pump()
check("pressed again, it is gone", vp.clip_plane("section") is None)
win.section_btn.setChecked(True)
pump()
win._on_escape()
pump()
check("Esc while picking stops it", not win.section_btn.isChecked()
      and not win._section_pick)


# ==========================================================================
print("the sketch's toggles are on the status bar")

check("not while modelling", not win.sketch_toggles.isVisible())
win.new_document(prompt=False)
win.new_primitive("cylinder")
pump()
win._active_dialog.commit()
pump()
win.start_sketch_on_plane("XZ")
settle(800)
check("while sketching, they are there", win.sketch_toggles.isVisible())
check("Show Grid and Snap to Grid have moved down from the ribbon",
      win.grid_btn.parent() is win.sketch_toggles
      and win.snap_btn.parent() is win.sketch_toggles)
s = ed.sketch
lid = s.add_line((-5.0, 5.0), (5.0, 5.0), weld=False)
pa, pb = s.entities[lid].points
s.add_constraint("horizontal", entities=[lid])
dim = s.add_constraint("distance", points=[pa, pb], value=10.0)
ed.solve()
texts = []
real_text = vp.draw_text


def recording(text, *args, **kwargs):
    texts.append(text)
    return real_text(text, *args, **kwargs)


def label_in(mode):
    texts.clear()
    vp.draw_text = recording
    try:
        win._dim_display_actions[mode].trigger()
    finally:
        vp.draw_text = real_text
    return list(texts)


name = s.constraints[dim].name
check("dimensions read as a value", any(t.startswith("10") for t in
                                        label_in("value")))
check("or as their name", name in label_in("name"))
check("or name and value together",
      any(t.startswith("%s = 10" % name) for t in label_in("both")))
label_in("value")
ed.clear_selection()
plain = len(ed._badge_layout())
win.all_constraints_btn.setChecked(True)
pump()
check("Show All Constraints shows every glyph, not just the picked",
      len(ed._badge_layout()) > plain, (plain, len(ed._badge_layout())))
win.all_constraints_btn.setChecked(False)
win.slice_btn.setChecked(True)
pump()
check("Slice Graphics cuts the part at the sketch",
      vp.clip_plane("slice") is not None)
win.finish_sketch()
pump()
check("and the cut goes with the sketch", vp.clip_plane("slice") is None
      and not win.sketch_toggles.isVisible())
win.slice_btn.setChecked(False)


# ==========================================================================
print("a sketch snaps to the model's corners and edge midpoints")

doc = new_box()
win.start_sketch_on_plane("XY")
settle(800)
s = ed.sketch
ed.snap_grid = False
ed.auto_constrain = True
before = len(s.entities)
ed.set_tool("line")
ed._on_move(39.85, 29.9, NONE)
check("near the box's corner the cursor latches onto it",
      ed._snap_info == "model corner", ed._snap_info)
check("and nothing is projected yet", len(s.entities) == before)
ed._on_click(39.85, 29.9, NONE)
ed._on_click(10.0, 12.0, NONE)
ed.escape()
pump()
projected = s.projected_entities()
check("clicking it brought the box's edge in", projected,
      len(projected))
drawn = [e for eid, e in s.entities.items()
         if e.kind == "line" and eid not in projected]
start = s.points[drawn[0].points[0]] if drawn else None
check("and the line starts on the corner",
      start is not None and near(start.x, 40.0, 1e-6)
      and near(start.y, 30.0, 1e-6),
      (start.x, start.y) if start else None)
corner_points = {pid for eid in projected for pid in s.entities[eid].points}
check("held there: the same point as the projected corner, or tied to it",
      bool(drawn) and (drawn[0].points[0] in corner_points or any(
          c.kind == "coincident" and drawn[0].points[0] in c.points
          for c in s.constraints.values())))
ed.set_tool("line")
ed._on_move(20.2, 0.3, NONE)
check("the middle of a model edge is a snap too",
      ed._snap_info == "model mid", ed._snap_info)
ed._on_click(20.2, 0.3, NONE)
ed._on_click(20.0, 15.0, NONE)
ed.escape()
pump()
check("tied to the projected edge's middle", any(
    c.kind == "midpoint" for c in s.constraints.values()))
win.finish_sketch()
pump()

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 17 tests passed")
sys.exit(0)
