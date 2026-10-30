"""0.3.1: the ten locked changes.

Every save keeps the file it replaces in OldVersions.  An extrude's
distance is dragged with an arrow in the view.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from datum.core import kernel, oldversions, prefs                  # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import ExtrudeFeature                     # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch20_")


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
LEFT = QtCore.Qt.LeftButton


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


def sketched_rectangle(w=40.0, h=30.0):
    """A new part with one rectangle on XY, and the extrude dialog open."""
    win.new_document(prompt=False)
    pump()
    win.start_sketch_on_plane("XY")
    settle(800)
    ed.snap_grid = False
    ed.set_tool("rect")
    ed._on_click(0.0, 0.0, NONE)
    ed._on_click(w, h, NONE)
    ed.set_tool("select")
    win.finish_sketch()
    pump()
    win.new_feature(ExtrudeFeature)
    pump()
    dialog = win._active_dialog
    win.select_all_profiles()
    pump()
    return dialog


# ==========================================================================
print("#208 every save keeps the file it replaces, in OldVersions")

doc = Document()
target = doc.save(os.path.join(WORK, "Bracket"))
check("the first save makes nothing old", oldversions.versions(target) == [])
doc.save(target)
kept = oldversions.versions(target)
check("the second keeps the first, as Bracket.0001",
      [os.path.basename(p) for _n, p in kept] == ["Bracket.0001.icpart"],
      kept)
check("in an OldVersions folder beside it",
      os.path.dirname(kept[0][1]) == os.path.join(WORK, "OldVersions"))
for _ in range(3):
    doc.save(target)
kept = oldversions.versions(target)
check("by default one is kept, the newest",
      [n for n, _p in kept] == [4], kept)
mine = prefs.prefs()
mine.old_versions = 3
for _ in range(4):
    doc.save(target)
check("Preferences decides how many: three",
      [n for n, _p in oldversions.versions(target)] == [6, 7, 8],
      oldversions.versions(target))
mine.old_versions = 0
doc.save(target)
check("none kept with 0, and the old ones are left alone",
      [n for n, _p in oldversions.versions(target)] == [6, 7, 8])
mine.old_versions = -1
for _ in range(5):
    doc.save(target)
check("every one kept with All",
      len(oldversions.versions(target)) == 8, oldversions.versions(target))
check("an old version still opens",
      Document.load(oldversions.versions(target)[0][1]) is not None)
mine.old_versions = 1
check("the setting round trips", prefs.Preferences.from_dict(
    {"old_versions": -1}).old_versions == -1
      and prefs.Preferences.from_dict({}).old_versions == 1
      and prefs.Preferences.from_dict({"old_versions": "x"}).old_versions
      == 1)
from datum.ui.prefs_ui import PreferencesDialog                     # noqa: E402

dialog = PreferencesDialog()
check("and Preferences offers it", dialog.versions_spin.value() == 1
      and dialog.versions_spin.specialValueText() == "All")
dialog.versions_spin.setValue(5)
dialog.gather()
check("a value set there is kept", dialog.prefs.old_versions == 5)
dialog.prefs.old_versions = 1
dialog.deleteLater()

# ==========================================================================
print("#212 an arrow in the view drags the extrude's distance")

dialog = sketched_rectangle()
dialog.distance.set_text("10")
dialog.preview()
vp.set_view("iso")
vp.fit_all()
settle(600)
dialog.preview()
pump()
check("the arrow is drawn", bool(dialog._handle_drawn))
check("and the view knows it can be grabbed",
      vp.drag_handle == dialog._handle_hit)
axis, tip = dialog._handle_tip()
check("it stands on the end of the extrusion, over the profile's middle",
      axis is not None and near(tip[0], 20.0, 1e-6) and near(tip[1], 15.0)
      and near(tip[2], 10.0), tip)
length = max(2.0, vp.view_span() * 0.11)
grab = vp.project((tip[0], tip[1], tip[2] + length * 0.5))
check("a press on it is a grab", dialog._handle_hit(*grab) is not None)
away = vp.project((tip[0] + 30.0, tip[1] - 30.0, tip[2]))
check("a press away from it is not", dialog._handle_hit(*away) is None)

to = vp.project((tip[0], tip[1], 25.0 + length * 0.5))
mouse(QtCore.QEvent.MouseButtonPress, grab, LEFT, LEFT)
for step in range(1, 6):
    x = grab[0] + (to[0] - grab[0]) * step / 5.0
    y = grab[1] + (to[1] - grab[1]) * step / 5.0
    mouse(QtCore.QEvent.MouseMove, (x, y), QtCore.Qt.NoButton, LEFT)
    pump(2)
mouse(QtCore.QEvent.MouseButtonRelease, to, LEFT, QtCore.Qt.NoButton)
pump()
settle(300)
check("dragging it up sets the distance it is dragged to",
      near(dialog.distance.value(), 25.0, 0.6), dialog.distance.value())
check("written into the field as a plain number",
      dialog.distance.edit.text().replace(".", "", 1).isdigit(),
      dialog.distance.edit.text())
check("and the part being previewed followed",
      near(kernel.volume(win.document.shape), 40 * 30 * 25, 40 * 30 * 0.6),
      kernel.volume(win.document.shape))

back = vp.project((tip[0], tip[1], -12.0 + length * 0.5))
_axis, tip = dialog._handle_tip()
grab = vp.project((tip[0], tip[1], tip[2] + length * 0.5))
mouse(QtCore.QEvent.MouseButtonPress, grab, LEFT, LEFT)
mouse(QtCore.QEvent.MouseMove, back, QtCore.Qt.NoButton, LEFT)
pump(2)
mouse(QtCore.QEvent.MouseButtonRelease, back, LEFT, QtCore.Qt.NoButton)
pump()
settle(300)
check("pulled back through the sketch it turns round, as Inventor's does",
      dialog.direction.value() == "flipped", dialog.direction.value())
check("with the distance it was pulled to",
      near(dialog.distance.value(), 12.0, 0.6), dialog.distance.value())
dialog.direction.set_value("symmetric")
dialog.distance.set_text("20")
dialog.preview()
pump()
_axis, tip = dialog._handle_tip()
check("a symmetric one has its arrow half way out",
      near(tip[2], 10.0, 1e-6), tip)
dialog.extent.setCurrentIndex(dialog.extent.findData("through_all"))
pump()
check("Through All has no distance, so no arrow",
      not dialog._handle_drawn and dialog._handle_hit(*grab) is None)
dialog.extent.setCurrentIndex(dialog.extent.findData("distance"))
dialog.direction.set_value("default")
dialog.distance.set_text("8")
dialog.commit()
pump()
check("OK keeps the dragged feature",
      near(kernel.volume(win.document.shape), 40 * 30 * 8, 1.0),
      kernel.volume(win.document.shape))
check("and the arrow goes with the dialog",
      vp.drag_handle is None and not dialog._handle_drawn)

# ==========================================================================
print("#126 keyboard shortcuts of your own")

from datum.ui import shortcuts                                      # noqa: E402

keys = {c: a.shortcut().toString() for c, a in win._shortcut_actions.items()}
check("every command in the table has its key on",
      all(keys[c] == shortcuts.normal(k) for c, k in shortcuts.DEFAULTS.items()),
      keys)
check("M measures, V and G move and turn, as Inventor's do",
      keys["measure"] == "M" and keys["free_move"] == "V"
      and keys["free_rotate"] == "G")
check("no two commands share a key by default",
      not shortcuts.clashes(shortcuts.DEFAULTS))

mine = prefs.prefs()
mine.shortcuts = {"extrude": "Ctrl+Shift+E", "fillet": ""}
win.apply_shortcuts()
check("one set in Preferences goes on at once",
      win._shortcut_actions["extrude"].shortcut().toString()
      == "Ctrl+Shift+E")
check("and an emptied one has no key",
      win._shortcut_actions["fillet"].shortcut().isEmpty())
check("the rest keep theirs",
      win._shortcut_actions["revolve"].shortcut().toString() == "R")

dialog = PreferencesDialog()
check("Preferences lists every command",
      dialog.shortcut_table.rowCount() == len(shortcuts.COMMANDS))
check("with the keys in use",
      dialog.shortcut_edits["extrude"].keySequence().toString()
      == "Ctrl+Shift+E")
dialog.shortcut_edits["sketch"].setKeySequence(QtGui.QKeySequence("R"))
dialog._shortcut_set("sketch")
check("keys another command had are taken from it",
      dialog.shortcut_edits["revolve"].keySequence().isEmpty()
      and "Revolve" in dialog.shortcut_note.text(),
      dialog.shortcut_note.text())
dialog.gather()
check("only what differs from the defaults is kept",
      dialog.prefs.shortcuts == {"extrude": "Ctrl+Shift+E", "fillet": "",
                                 "sketch": "R", "revolve": ""},
      dialog.prefs.shortcuts)
dialog.reset_shortcuts()
dialog.gather()
check("Reset to defaults keeps nothing", dialog.prefs.shortcuts == {})
check("and the file round trips", prefs.Preferences.from_dict(
    {"shortcuts": {"extrude": "X"}}).shortcuts == {"extrude": "X"}
      and prefs.Preferences.from_dict({"shortcuts": "nonsense"}).shortcuts
      == {})
dialog.deleteLater()
mine.shortcuts = {}
win.apply_shortcuts()

# ==========================================================================
print("#90 Measure, the Inventor way")

from OCP.TopAbs import TopAbs_VERTEX                               # noqa: E402

win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
box = win.document.shape
corners = kernel.explore(box, TopAbs_VERTEX)
low = min(corners, key=lambda v: sum(kernel.shape_centre(v)))
high = max(corners, key=lambda v: sum(kernel.shape_centre(v)))
faces = kernel.faces(box)
top = max(faces, key=lambda f: kernel.shape_centre(f)[2])
bottom = min(faces, key=lambda f: kernel.shape_centre(f)[2])
side = min(faces, key=lambda f: kernel.shape_centre(f)[0])

win._shortcut_actions["measure"].trigger()
pump()
measure = win.measure_dialog
check("M opens Measure", measure is not None and measure.isVisible())
check("and points, edges and faces can all be picked",
      vp.selection_mode == "measure")
check("with nothing picked it says what to do",
      "Select geometry" in measure.readout.toPlainText())

real = vp.selected_shapes


def pick(shape):
    vp.selected_shapes = lambda: [shape]
    win._on_viewport_selection()
    vp.selected_shapes = real
    pump()


pick(high)
text = measure.readout.toPlainText()
check("one point says where it is", "Point" in text and "X 40" in text
      and "Y 30" in text and "Z 20" in text, text)
pick(low)
text = measure.readout.toPlainText()
check("a second point measures straight across to it",
      "Distance  53.85" in text, text)
check("with the X, Y and Z distances",
      "dX 40" in text and "dY 30" in text and "dZ 20" in text, text)
check("and a line between them in the view", bool(measure._drawn))
pick(top)
text = measure.readout.toPlainText()
check("a third pick starts again", text.startswith("First")
      and "Face" in text and "Second" not in text, text)
check("a face says its area", "Area 1200" in text, text)
pick(bottom)
text = measure.readout.toPlainText()
check("two faces: the distance between them", "Distance  20" in text, text)
check("and the angle between them", "Angle     180 deg" in text, text)
pick(side)
pick(top)
text = measure.readout.toPlainText()
check("square faces are at 90", "Angle     90 deg" in text, text)
measure.copy()
check("Copy puts the readout on the clipboard",
      "Angle" in QtWidgets.QApplication.clipboard().text())
measure.restart()
check("Restart forgets both", not measure.picks and not measure._drawn)
measure.close()
pump()
check("closing puts the picking back as it was",
      vp.selection_mode == "face" and win.measure_dialog is None,
      vp.selection_mode)

# ==========================================================================
print("#190 Split: faces, or a solid in two, along a plane or a face")

from datum.core.features import SplitFeature, WorkPlaneFeature     # noqa: E402
from datum.core.naming import RefSet                               # noqa: E402
from datum.ui import icons                                         # noqa: E402

check("it has its icons", all(not icons.icon(n, 24).isNull()
                              for n in ("split", "split_faces",
                                        "split_solid")))
win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
level = WorkPlaneFeature()
level.base, level.offset = "XY", "8"
win.document.add_feature(level)
win.rebuild()
pump()
win.new_feature(SplitFeature)
pump()
split = win._active_dialog
check("the Split dialog opens", type(split).__name__ == "SplitDialog")
split.plane.setCurrentIndex(split.plane.findData(level.name))
split.method.set_value("solid")
split.preview()
pump()
names = [b.name for b in win.document.bodies]
check("Split Solid cuts it in two solids", names == ["Solid1", "Solid2"],
      names)
volumes = sorted(round(kernel.volume(b.shape)) for b in win.document.bodies)
check("at the plane", volumes == [9600, 14400], volumes)
split.method.set_value("faces")
split.all_faces.setChecked(True)
split.preview()
pump()
check("Split Faces with All Faces divides every face it crosses",
      len(win.document.bodies) == 1
      and len(kernel.faces(win.document.shape)) == 10,
      len(kernel.faces(win.document.shape)))
split.all_faces.setChecked(False)
base = win.pick_shape()
left = min(kernel.faces(base), key=lambda f: kernel.shape_centre(f)[0])
real_faces = vp.selected_faces
vp.selected_faces = lambda: [left]
split.faces_pick.set_picking(True)
split.on_selection()
vp.selected_faces = real_faces
pump()
check("or only the faces picked", len(kernel.faces(win.document.shape)) == 7,
      len(kernel.faces(win.document.shape)))
# a flat face of the part as the tool: the left end, cutting along X
split.method.set_value("solid")
vp.selected_faces = lambda: [left]
split.tool_pick.set_picking(True)
split.on_selection()
vp.selected_faces = real_faces
pump()
check("a picked face is the tool, and the plane list stands aside",
      len(split.feature.tool) == 1 and not split.plane.isEnabled())
check("which misses the solid it is a face of, and says so",
      "does not cross" in (split.feature.error or ""), split.feature.error)
split._clear_tool()
split.plane.setCurrentIndex(split.plane.findData(level.name))
split.commit()
pump()
check("OK keeps it, saved and read back", any(
    isinstance(f, SplitFeature) and f.mode == "solid"
    for f in win.document.features))
again = Document()
again.load_dict(win.document.to_dict())
again.rebuild()
check("and builds the same from the file",
      [b.name for b in again.bodies] == ["Solid1", "Solid2"],
      [b.name for b in again.bodies])

# ==========================================================================
print("#195 solids are picked, by a face or in the tree")

from datum.core.features import (                                  # noqa: E402
    CUT, JOIN, NEW_BODY, MirrorFeature, PatternFeature, PrimitiveFeature,
)
from datum.ui.widgets import SelectionField                        # noqa: E402


def block(doc, x, y, z, dx, dy, dz, op=JOIN, name=""):
    feature = PrimitiveFeature()
    feature.kind = "box"
    feature.a, feature.b, feature.c = str(dx), str(dy), str(dz)
    feature.origin = (str(x), str(y), str(z))
    feature.operation = op
    feature.body_name = name
    doc.add_feature(feature)
    return feature


def picked_in_view(dialog, shapes):
    real = vp.selected_shapes
    vp.selected_shapes = lambda: list(shapes)
    try:
        dialog.on_selection()
    finally:
        vp.selected_shapes = real
    pump()


def body(name):
    return next(b for b in win.document.bodies if b.name == name).shape


win.new_document(prompt=False)
block(win.document, 0, 0, 0, 40, 40, 20, name="Left")
block(win.document, 100, 0, 0, 40, 40, 20, op=NEW_BODY, name="Right")
win.rebuild()
pump()
right_face = max(kernel.faces(body("Right")),
                 key=lambda f: kernel.shape_centre(f)[0])
win.new_primitive("box")
pump()
dialog = win._active_dialog
dialog.operation.set_value(CUT)
dialog._sync_solids()
check("the Solids row is a pick field, not a list",
      isinstance(dialog.solids, SelectionField))
dialog.solids.set_picking(True)
check("which picks whole solids in the view", dialog.wants_selection() == "body",
      dialog.wants_selection())
picked_in_view(dialog, [right_face])
check("a face picks the solid it is on", dialog.picked_solids() == ["Right"],
      dialog.picked_solids())
win._tree_item_clicked("body", "Left")
check("and a row under Solid Bodies picks that one",
      dialog.picked_solids() == ["Right", "Left"], dialog.picked_solids())
win._tree_item_clicked("body", "Left")
check("a second click lets it go", dialog.picked_solids() == ["Right"],
      dialog.picked_solids())
check("the field counts them", dialog.solids.count.text() == "1 solid",
      dialog.solids.count.text())
dialog.store()
check("and the feature works on what was picked",
      dialog.feature.solids == ["Right"], dialog.feature.solids)
dialog.cancel()
pump()

# ==========================================================================
print("#191 Pattern and Mirror, the Inventor way")

win.new_document(prompt=False)
block(win.document, 0, 0, 0, 40, 40, 10, name="Plate")
peg = block(win.document, 5, 5, 10, 6, 6, 6)
win.rebuild()
pump()
win.new_feature(PatternFeature, mode="rectangular")
pump()
dialog = win._active_dialog
check("Pattern has its strip down the side: features, rectangular",
      type(dialog).__name__ == "PatternDialog"
      and dialog.of.value() == "features"
      and dialog.kind.value() == "rectangular")
top = max(kernel.faces(win.pick_shape()),
          key=lambda f: kernel.shape_centre(f)[2])
dialog.parents.set_picking(True)
picked_in_view(dialog, [top])
check("a face the peg made picks the peg",
      dialog.picked_features() == [peg.id], dialog.picked_features())
dialog.count1.set_text("3")
dialog.spacing1.set_text("10")
dialog.dir1.buttons["Y"].click()
dialog.preview()
pump()
check("Y is one click", dialog.dir1.name == "Y" and not len(dialog.dir1.ref)
      and dialog.dir1.buttons["Y"].isChecked())
check("three pegs along it", near(kernel.volume(win.document.shape),
                                  16000 + 3 * 216, 1e-3),
      kernel.volume(win.document.shape))


def along_y(edge):
    from datum.core.features import axis_from_shape
    axis = axis_from_shape(edge)
    return (axis is not None and axis.name == "edge"
            and abs(abs(axis.direction[1]) - 1.0) < 1e-9)


edge = next(e for e in kernel.edges(win.pick_shape()) if along_y(e))
dialog.dir1.pick.set_picking(True)
picked_in_view(dialog, [edge])
check("or an edge of the part is the direction",
      len(dialog.dir1.ref) == 1
      and not any(b.isChecked() for b in dialog.dir1.buttons.values()),
      dialog.dir1.pick.count.text())
dialog.preview()
pump()
low = kernel.bounding_box(win.document.shape)[1]
dialog.dir1.flip_button.setChecked(True)
dialog.preview()
pump()
flipped = kernel.bounding_box(win.document.shape)[1]
check("and Flip runs it the other way",
      sorted([round(low), round(flipped)]) == [-15, 0], (low, flipped))
dialog.kind.set_value("circular")
dialog._sync_enabled()
check("Circular swaps the directions for an axis",
      dialog.axis.isVisibleTo(dialog) and not dialog.dir1.isVisibleTo(dialog)
      and dialog.count1.isVisibleTo(dialog))
dialog.kind.set_value("rectangular")
dialog._sync_enabled()
dialog.of.set_value("bodies")
dialog._sync_of()
check("and Solids swaps the features for solids",
      dialog.bodies.isVisibleTo(dialog)
      and not dialog.parents.isVisibleTo(dialog))
dialog.of.set_value("features")
dialog._sync_of()
dialog.commit()
pump()
pattern = win.document.features[-1]
check("OK keeps the picked edge and the flip",
      isinstance(pattern, PatternFeature) and len(pattern.dir1_ref) == 1
      and pattern.flip1)
again = Document()
again.load_dict(win.document.to_dict())
again.rebuild()
check("and the file builds the same",
      near(kernel.volume(again.shape), kernel.volume(win.document.shape),
           1e-3), kernel.volume(again.shape))

before = kernel.volume(win.document.shape)
win.new_feature(MirrorFeature)
pump()
dialog = win._active_dialog
check("Mirror opens with its strip and a plane field",
      type(dialog).__name__ == "MirrorDialog"
      and set(dialog.plane.buttons) == {"XY", "XZ", "YZ"})
dialog.scope.set_value("body")
dialog._sync_enabled()
side = max(kernel.faces(win.pick_shape()),
           key=lambda f: kernel.shape_centre(f)[0])
dialog.plane.pick.set_picking(True)
picked_in_view(dialog, [side])
check("a flat face of the part is the mirror plane",
      len(dialog.plane.ref) == 1
      and dialog.plane.pick.count.text() == "a picked face",
      dialog.plane.pick.count.text())
dialog.preview()
pump()
box = kernel.bounding_box(win.document.shape)
check("the part mirrors about it", near(box[3], 80.0, 1e-3)
      and near(kernel.volume(win.document.shape), 2 * before, 1e-2),
      (box[3], kernel.volume(win.document.shape)))
dialog.scope.set_value("features")
dialog._sync_enabled()
check("Features swaps the solids for a feature pick",
      dialog.parents.isVisibleTo(dialog)
      and not dialog.solids.isVisibleTo(dialog))
dialog.scope.set_value("body")
dialog._sync_enabled()
dialog.commit()
pump()
mirror = win.document.features[-1]
check("OK keeps the picked plane",
      isinstance(mirror, MirrorFeature) and len(mirror.plane_ref) == 1)

# ==========================================================================
print("#210 the rest of Inventor's extents, in the dialog")


def sketch_more(*clicks, tool="rect"):
    win.start_sketch_on_plane("XY")
    settle(800)
    ed.snap_grid = False
    ed.set_tool(tool)
    for x, y in clicks:
        ed._on_click(float(x), float(y), NONE)
    ed.set_tool("select")
    win.finish_sketch()
    pump()


dialog = sketched_rectangle(20.0, 10.0)
check("Direction has Asymmetric", "asymmetric" in dialog.direction._buttons)
check("Distance B stays out of the way until then",
      not dialog.distance2.isVisibleTo(dialog))
dialog.direction.set_value("asymmetric")
dialog._sync_enabled()
check("which brings Distance B and Taper B",
      dialog.distance2.isVisibleTo(dialog) and dialog.taper2.isVisibleTo(dialog))
dialog.distance.set_text("8")
dialog.distance2.set_text("3")
dialog.preview()
pump()
b = kernel.bounding_box(win.document.shape)
check("and builds 8 one way, 3 the other",
      near(b[2], -3, 1e-6) and near(b[5], 8, 1e-6), b)
check("with no arrow, which drags one distance", not dialog._handle_drawn)
dialog.extent.setCurrentIndex(dialog.extent.findData("to_next"))
check("To Next goes one way or the other, not both",
      not dialog.direction._buttons["symmetric"].isEnabled()
      and dialog.direction.value() == "default")
dialog.extent.setCurrentIndex(dialog.extent.findData("distance"))
dialog.distance.set_text("10")
dialog.commit()
pump()

sketch_more((30, 0), (40, 10))
win.new_feature(ExtrudeFeature)
pump()
dialog = win._active_dialog
win.select_all_profiles()
pump()
dialog.extent.setCurrentIndex(dialog.extent.findData("to_plane"))
pump()
check("To shows where it runs to, with Extend Face",
      dialog.to_end.isVisibleTo(dialog)
      and dialog.extend_face.isVisibleTo(dialog)
      and not dialog.distance.isVisibleTo(dialog))
top = max(kernel.faces(win.pick_shape()),
          key=lambda f: kernel.shape_centre(f)[2])
dialog.to_end.pick.set_picking(True)
check("its pick takes faces and corners",
      dialog.wants_selection() == "face_vertex", dialog.wants_selection())
picked_in_view(dialog, [top])
check("a face of the part is picked, and the list stands aside",
      len(dialog.feature.to_ref) == 1
      and dialog.to_end.pick.count.text() == "a picked face"
      and not dialog.to_plane.isEnabled(), dialog.to_end.pick.count.text())
check("it does not cover the profile, and says so",
      "Extend Face" in (dialog.feature.error or ""), dialog.feature.error)
dialog.extend_face.setChecked(True)
pump()
b = kernel.bounding_box(win.document.shape)
check("Extend Face runs it out to the face's height",
      not dialog.feature.error and near(b[5], 10, 1e-6),
      (dialog.feature.error, b))

dialog.extent.setCurrentIndex(dialog.extent.findData("distance"))
dialog.distance.set_text("4")
check("From is there for a distance", dialog.from_end.isVisibleTo(dialog)
      and not dialog.from_end.is_set())
dialog.from_end.pick.set_picking(True)
picked_in_view(dialog, [top])
b = kernel.bounding_box(win.document.shape)
check("From a face: it starts there", not dialog.feature.error
      and near(b[5], 14, 1e-6)
      and near(kernel.volume(win.document.shape), 2000 + 400, 1e-3),
      (dialog.feature.error, b, kernel.volume(win.document.shape)))
dialog.from_end.pick.cleared.emit()
dialog.from_end.pick.set_picking(True)
win._tree_item_clicked("plane", "XZ")
pump()
check("a plane picked in the tree is taken",
      dialog.from_end.name == "XZ" and not len(dialog.from_end.ref))
check("and one alongside the extrude is refused",
      "alongside" in (dialog.feature.error or ""), dialog.feature.error)
dialog.from_end.combo.setCurrentIndex(0)
pump()
check("Sketch plane puts it back", not dialog.feature.error
      and not dialog.from_end.is_set(), dialog.feature.error)
check("no open profile, no Match Shape",
      not dialog.match_row.isVisibleTo(dialog))
dialog.commit()
pump()

before = kernel.volume(win.document.shape)
sketch_more((10, -5), (10, 15), tool="line")
win.new_feature(ExtrudeFeature)
pump()
dialog = win._active_dialog
check("an open profile offers Match Shape",
      dialog.match_row.isVisibleTo(dialog))
dialog.match.setChecked(True)
dialog.operation.set_value(CUT)
dialog.distance.set_text("10")
dialog.preview()
pump()
check("a cut matched to it takes the part on its side", not dialog.feature.error
      and near(kernel.volume(win.document.shape), before - 1000, 1e-3),
      (dialog.feature.error, before - kernel.volume(win.document.shape)))
dialog.match_side.setChecked(True)
pump()
check("and the other side the other",
      not dialog.feature.error
      # the other half of the block, and the 10 x 10 x 4 beside it
      and near(kernel.volume(win.document.shape), before - 1000 - 400,
               1e-3),
      (dialog.feature.error, before - kernel.volume(win.document.shape)))
dialog.commit()
pump()
matched = win.document.features[-1]
again = Document()
again.load_dict(win.document.to_dict())
again.rebuild()
check("OK keeps it, and the file builds the same",
      matched.match_shape and matched.match_flip
      and near(kernel.volume(again.shape), kernel.volume(win.document.shape),
               1e-3))

# ==========================================================================
print("#262 a Home button beside the view cube")


def looking():
    """Which way the camera looks, and which way is up."""
    eye, centre, up = vp.camera_state()[:3]
    look = [centre[i] - eye[i] for i in range(3)]
    size = sum(c * c for c in look) ** 0.5
    return tuple(c / size for c in look), tuple(up)


def along(a, b, tol=1e-4):
    size = sum(c * c for c in b) ** 0.5
    return all(abs(a[i] - b[i] / size) < tol for i in range(3))


win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
vp.set_view("front")
pump()
def spot(name):
    at = vp.CUBE_BUTTONS[name][0]
    return (vp.width() - at[0], at[1])


home = spot("home")
check("the house is drawn, top left of the cube",
      "home" in vp._cube_buttons and vp.over_home(*home))
check("and nowhere else", not vp.over_home(home[0] - 40, home[1] + 40))
check("the cube has no axes of its own", not vp._cube.ToDrawAxes())
mouse(QtCore.QEvent.MouseButtonPress, home, LEFT, LEFT)
mouse(QtCore.QEvent.MouseButtonRelease, home, LEFT, QtCore.Qt.NoButton)
vp.finish_animation()
pump()
look, up = looking()
check("a click on it goes home: the isometric", along(look, (-1, 1, -1))
      and up[2] > 0.5, (look, up))
check("without selecting anything", not vp.selected_shapes())

asked = []
vp.cube_menu_requested.disconnect(win._cube_menu)
vp.cube_menu_requested.connect(asked.append)
arrow = spot("menu")
mouse(QtCore.QEvent.MouseButtonPress, arrow, LEFT, LEFT)
mouse(QtCore.QEvent.MouseButtonRelease, arrow, LEFT, QtCore.Qt.NoButton)
check("the little arrow beside the cube asks for its menu", len(asked) == 1)
mouse(QtCore.QEvent.MouseButtonPress, home, QtCore.Qt.RightButton,
      QtCore.Qt.RightButton)
mouse(QtCore.QEvent.MouseButtonRelease, home, QtCore.Qt.RightButton,
      QtCore.Qt.NoButton)
check("and so does a right click on the house", len(asked) == 2)
vp.cube_menu_requested.disconnect(asked.append)
vp.cube_menu_requested.connect(win._cube_menu)
menu = win.build_cube_menu(QtWidgets.QMenu(win))
offered = [a.text() for a in menu.actions()]
check("which offers Home, Front and Top, as Inventor's does",
      offered[0] == "Go Home" and "Set Current View as Home" in offered
      and "Set Current View as Front" in offered
      and "Set Current View as Top" in offered and "Reset Front" in offered,
      offered)

vp.set_view("top")
pump()
vp.view.SetZoom(0.5)
top_camera = vp.camera_state()
win.set_home(fit=False)
check("Set Current View as Home keeps the camera in the document",
      win.document.view.home is not None
      and win.document.view.home["fit"] is False and win.document.modified)
vp.set_view("front")
win.go_home(animate=False)
pump()
state = vp.camera_state()
check("and Fixed Distance goes back to exactly that",
      all(abs(a - b) < 1e-6 for a, b in zip(state[0], top_camera[0]))
      and abs(state[3] - top_camera[3]) < 1e-9, (state, top_camera))
win.set_home(fit=True)
vp.set_view("front")
win.go_home(animate=False)
pump()
look, _up = looking()
check("Fit to View looks the same way, fitted",
      along(look, (0, 0, -1)) and abs(vp.camera_state()[3] - top_camera[3])
      > 1e-6, (look, vp.camera_state()[3]))
path = os.path.join(WORK, "homed.pdat")
win.document.save(path)
again = Document()
again.load_dict(json.loads(json.dumps(win.document.to_dict())))
check("saved with the part", again.view.home == win.document.view.home)
win.reset_home()
win.go_home(animate=False)
look, _up = looking()
check("Reset Home: the isometric again", win.document.view.home is None
      and along(look, (-1, 1, -1)), look)
vp.set_view("front")
# a copy, since the part itself is open already and only gets its tab back
fresh = os.path.join(WORK, "homed copy.pdat")
__import__("shutil").copyfile(path, fresh)
win.open_path(fresh)
pump()
look, _up = looking()
check("a part opens at the home it was given", along(look, (0, 0, -1)),
      look)

# ==========================================================================
print("#263 any view can be Front, and the cube turns to it")

win.reset_home()            # the copy came with the home it was given
vp.set_view("right")
pump()
win.set_front("front")
pump()
check("Set Current View as Front turns the whole cube: FRONT faces "
      "where Right did",
      along(vp.cube_facing((0, -1, 0)), (1, 0, 0))
      and along(vp.cube_facing((1, 0, 0)), (0, 1, 0))
      and along(vp.cube_facing((0, 0, 1)), (0, 0, 1)),
      [vp.cube_facing(n) for n in ((0, -1, 0), (1, 0, 0), (0, 0, 1))])
vp.set_view("front")
pump()
look, up = looking()
check("Front is that face now", along(look, (-1, 0, 0))
      and along(up, (0, 0, 1)), (look, up))
vp.set_view("right")
pump()
look, _up = looking()
check("and Right the one beside it", along(look, (0, -1, 0)), look)
win.go_home(animate=False)
look, _up = looking()
check("Home's isometric turns with it", along(look, (-1, -1, -1)), look)
check("it is the document's, saved with it",
      along(win.document.view.to_dict()["front"], (1, 0, 0)))


class Face:
    """What OCCT hands over for a click on a face, edge or corner."""

    def __init__(self, orientation):
        self.orientation = orientation

    def MainOrientation(self):
        return self.orientation


from OCP.V3d import V3d_TypeOfOrientation as Side            # noqa: E402

vp.set_view("top")
vp._turned_cube_click(Face(Side.V3d_Yneg))
look, up = looking()
check("a click on the turned cube's FRONT is the new Front",
      along(look, (-1, 0, 0)) and along(up, (0, 0, 1)), (look, up))
vp._turned_cube_click(Face(Side.V3d_XposYnegZpos))
look, up = looking()
check("and a corner looks from that corner of it, its Top up",
      along(look, (-1, -1, -1)) and up[2] > 0.5, (look, up))

print("at any angle at all")
vp.aim((0.6, 0.5, -0.62), (0.3, 0.2, 0.93))
pump()
odd, odd_up = looking()
win.set_front("front")
vp.set_view("iso")
pump()
vp.set_view("front")
pump()
look, up = looking()
check("a view at an odd angle made Front is Front, exactly",
      along(look, odd) and along(up, odd_up), (look, odd))
check("and the cube's FRONT faces the way it looked from",
      along(vp.cube_facing((0, -1, 0)), [-c for c in odd]))

print("Normal To an odd face, then Front, draws it square")
import math                                                    # noqa: E402
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf               # noqa: E402
from datum.core import hlr                                     # noqa: E402
from datum.core.features import plane_from_face                # noqa: E402

slab = kernel.rotate(kernel.box(60, 20, 40), (0, 0, 0), (1, 2, 3), 37.0)
spin = gp_Trsf()
spin.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 2, 3)), math.radians(37))


def spun(v):
    d = gp_Dir(*v).Transformed(spin)
    return (d.X(), d.Y(), d.Z())


def facing(f, want):
    plane = plane_from_face(f)
    # a face's plane can face either way out of it: by line, not sign
    if plane is None:
        return -2.0
    return abs(sum(a * b for a, b in zip(plane.normal, want)))


face = max(kernel.faces(slab), key=lambda f: facing(f, spun((0, -1, 0))))
vp.aim((0.2, 0.9, -0.3), (0.1, 0.3, 0.95))
real = vp.selected_faces
vp.selected_faces = lambda: [face]
win.normal_to_selected_face()
vp.selected_faces = real
vp.finish_animation()
pump()
look, up = looking()
edges = [spun(a) for a in ((1, 0, 0), (0, 0, 1))]
check("Normal To looks square at it, with an edge of it level or upright",
      abs(sum(a * b for a, b in zip(look, spun((0, 1, 0))))) > 1 - 1e-6
      and max(abs(sum(a * b for a, b in zip(up, e))) for e in edges)
      > 1 - 1e-6, (look, up))
win.set_front("front")
drawn = hlr.project(slab, *win.document.view.orientation("front"))
check("and Front made from there draws it square, 60 by 40",
      sorted((round(drawn.width, 3), round(drawn.height, 3))) == [40, 60],
      (drawn.width, drawn.height))

win.reset_front()
pump()
check("Reset Front: the stock cube again",
      along(vp.cube_facing((0, -1, 0)), (0, -1, 0))
      and win.document.view.is_default())
vp.set_view("top")
pump()
win.set_front("top")
check("Set Current View as Top on the top changes nothing",
      win.document.view.is_default(), win.document.view)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 20 tests passed")
sys.exit(0)
